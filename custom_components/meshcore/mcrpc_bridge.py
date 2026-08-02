"""Optional mesh node-request bridge (mcRPC is an internal transport).

Home Assistant users interact via ``meshcore.request`` / ``broadcast`` / ``raw``.
Wire protocol details stay inside the standalone ``mcrpc`` package.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_MCRPC_CHANNEL,
    CONF_MCRPC_DEBUG,
    CONF_MCRPC_ENABLED,
    CONF_MCRPC_ENTITY_BRIDGE,
    CONF_MCRPC_EVENT_BRIDGE,
    CONF_MCRPC_TIMEOUT,
    DEFAULT_MCRPC_CHANNEL,
    DEFAULT_MCRPC_TIMEOUT,
    DOMAIN,
    EVENT_MCRPC_EVENT,
    EVENT_MCRPC_RESPONSE,
    EVENT_NODE_EVENT,
    EVENT_NODE_RESPONSE,
)
from .logbook import EVENT_MESHCORE_MESSAGE
from .mcrpc_device_mapper import NodeDeviceMapper
from .mcrpc_node_registry import NodeRegistry
from .mcrpc_policy import McRpcPolicy

_LOGGER = logging.getLogger(__name__)


def _import_mcrpc():
    """Import the standalone mcrpc package (never duplicate protocol here)."""
    try:
        import mcrpc  # type: ignore
        return mcrpc
    except ImportError as err:  # pragma: no cover - env dependent
        raise RuntimeError(
            "Mesh node requests require the mcrpc Python package. "
            "Install: pip install -e /path/to/mcrpc/python"
        ) from err


class McRpcBridge:
    """Channel transport + correlation + node registry for mesh node requests."""

    def __init__(self, hass: HomeAssistant, coordinator, entry) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.entry = entry
        self._unsub = None
        self._timeout_unsub = None
        self._mcrpc = None
        self._correlator = None
        self._entity_bridge = None
        self._waiters: dict[int, asyncio.Future] = {}
        # broadcast request_id → collected response payloads
        self._broadcast_buckets: dict[int, list[dict[str, Any]]] = {}
        self._last_by_command: dict[str, dict[str, Any]] = {}
        self.registry = NodeRegistry()
        self.device_mapper = NodeDeviceMapper(
            entry_id=entry.entry_id,
            hub_name=entry.data.get("name") or entry.title,
        )
        # Diagnostics / stats
        self.stats: dict[str, Any] = {
            "tx_count": 0,
            "rx_count": 0,
            "parse_ok": 0,
            "parse_unknown": 0,
            "parser_errors": 0,
            "timeouts": 0,
            "errors": 0,
            "denied": 0,
            "answered": 0,
            "rtt_sum_ms": 0.0,
            "rtt_count": 0,
            "tx_wait_expected": 0,
            "rx_matched": 0,
            "last_tx": None,
            "last_rx": None,
            "last_error": None,
            "recent_errors": [],
            "recent_denials": [],
            "recent_traces": [],
        }
        # Dedup keys for (channel, body, send_id/timestamp) recently answered
        self._recent_answer_keys: dict[str, float] = {}
        self._unsub_sent = None

    # ---- compat cache views (list_nodes / has_capability) --------------------
    @property
    def discover_cache(self) -> dict[str, dict[str, Any]]:
        return self.registry.discover_cache_view()

    @property
    def capability_cache(self) -> dict[str, list[str]]:
        return self.registry.capability_cache_view()

    @property
    def enabled(self) -> bool:
        return bool(self.entry.data.get(CONF_MCRPC_ENABLED, False))

    @property
    def event_bridge_enabled(self) -> bool:
        return bool(self.entry.data.get(CONF_MCRPC_EVENT_BRIDGE, True))

    @property
    def debug(self) -> bool:
        return bool(self.entry.data.get(CONF_MCRPC_DEBUG, False))

    @property
    def default_timeout(self) -> float:
        return float(self.entry.data.get(CONF_MCRPC_TIMEOUT, DEFAULT_MCRPC_TIMEOUT))

    @property
    def default_channel(self) -> int:
        return int(self.entry.data.get(CONF_MCRPC_CHANNEL, DEFAULT_MCRPC_CHANNEL))

    def policy(self) -> McRpcPolicy:
        data = dict(self.entry.data)
        aliases = []
        coord_name = getattr(self.coordinator, "name", None)
        if coord_name:
            aliases.append(str(coord_name))
        data["_mcrpc_name_aliases"] = aliases
        return McRpcPolicy(data, entry_id=self.entry.entry_id)

    def _trace(self, stage: str, **fields: Any) -> None:
        """Structured receive-pipeline trace (always at INFO when debug, else DEBUG)."""
        payload = {"stage": stage, **fields}
        recent = list(self.stats.get("recent_traces") or [])
        recent.append({"time": dt_util.utcnow().isoformat(), **payload})
        self.stats["recent_traces"] = recent[-50:]
        msg = "mcRPC TRACE %s %s", stage, {k: v for k, v in fields.items() if k != "raw_payload"}
        if self.debug:
            _LOGGER.info(*msg)
        else:
            _LOGGER.debug(*msg)

    def _contact_names(self) -> list[str]:
        names: list[str] = []
        contacts = getattr(self.coordinator, "get_all_contacts", None)
        if callable(contacts):
            for c in contacts() or []:
                if isinstance(c, dict):
                    n = c.get("name") or c.get("adv_name")
                    if n:
                        names.append(str(n))
        return names

    def _note_denial(self, reason: str, *, source: str | None, channel_idx: Any) -> None:
        self.stats["denied"] = int(self.stats["denied"]) + 1
        recent = list(self.stats.get("recent_denials") or [])
        recent.append(
            {
                "time": dt_util.utcnow().isoformat(),
                "reason": reason,
                "source": source,
                "channel": channel_idx,
            }
        )
        self.stats["recent_denials"] = recent[-20:]
        if self.debug:
            _LOGGER.debug(
                "mcRPC denied reason=%s source=%s channel=%s",
                reason,
                source,
                channel_idx,
            )

    def _record_rtt(self, latency_ms: float | None) -> None:
        if latency_ms is None:
            return
        self.stats["rtt_sum_ms"] = float(self.stats["rtt_sum_ms"]) + float(latency_ms)
        self.stats["rtt_count"] = int(self.stats["rtt_count"]) + 1
        self.stats["rx_matched"] = int(self.stats["rx_matched"]) + 1

    async def async_setup(self) -> None:
        if not self.enabled:
            _LOGGER.debug("Node requests disabled for entry %s", self.entry.entry_id)
            return

        self._mcrpc = _import_mcrpc()
        self._correlator = self._mcrpc.RequestCorrelator(default_timeout=self.default_timeout)

        if self.event_bridge_enabled:
            self._unsub = self.hass.bus.async_listen(
                EVENT_MESHCORE_MESSAGE, self._on_meshcore_message
            )
            # Immediate path for Chat / send_channel_message (do not wait for
            # outgoing meshcore_message terminal re-fire after RX_LOG).
            self._unsub_sent = self.hass.bus.async_listen(
                f"{DOMAIN}_message_sent", self._on_message_sent
            )

        self._timeout_unsub = self.hass.loop.call_later(5.0, self._schedule_timeout_sweep)

        if self.entry.data.get(CONF_MCRPC_ENTITY_BRIDGE, False):
            from .mcrpc_entity_bridge import McRpcEntityBridge

            self._entity_bridge = McRpcEntityBridge(self.hass, self.coordinator, self.entry)
            await self._entity_bridge.async_setup()

        _LOGGER.info("Mesh node requests enabled for entry %s", self.entry.entry_id)

    async def async_unload(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._unsub_sent:
            self._unsub_sent()
            self._unsub_sent = None
        if self._timeout_unsub:
            self._timeout_unsub.cancel()
            self._timeout_unsub = None
        for fut in self._waiters.values():
            if not fut.done():
                fut.cancel()
        self._waiters.clear()
        self._broadcast_buckets.clear()
        if self._entity_bridge:
            await self._entity_bridge.async_unload()
            self._entity_bridge = None

    def _ensure_ready(self) -> None:
        if not self.enabled:
            raise RuntimeError(
                "Mesh node requests are disabled. Enable them under "
                "MeshCore → Configure → Mesh Node Requests (mcRPC)."
            )
        if self._mcrpc is None or self._correlator is None:
            self._mcrpc = _import_mcrpc()
            self._correlator = self._mcrpc.RequestCorrelator(default_timeout=self.default_timeout)

    def _note_error(self, message: str) -> None:
        self.stats["errors"] = int(self.stats["errors"]) + 1
        self.stats["last_error"] = message
        recent = list(self.stats.get("recent_errors") or [])
        recent.append({"time": dt_util.utcnow().isoformat(), "error": message})
        self.stats["recent_errors"] = recent[-20:]

    def _schedule_timeout_sweep(self) -> None:
        self.hass.async_create_task(self._async_timeout_sweep())
        self._timeout_unsub = self.hass.loop.call_later(5.0, self._schedule_timeout_sweep)

    async def _async_timeout_sweep(self) -> None:
        if not self._correlator:
            return
        for pending in self._correlator.expire():
            self.stats["timeouts"] = int(self.stats["timeouts"]) + 1
            # Finalize broadcast buckets if any
            if pending.request_id in self._broadcast_buckets:
                bucket = self._broadcast_buckets.pop(pending.request_id, [])
                if pending.request_id in self._waiters:
                    fut = self._waiters.pop(pending.request_id)
                    if not fut.done():
                        fut.set_result(self._broadcast_result(pending, bucket))
                continue
            payload = self._base_payload(
                node=None,
                target=pending.target,
                command=pending.command,
                request_id=pending.request_id,
                channel_idx=pending.channel_idx,
                raw="",
                success=False,
                error="timeout",
            )
            self._dispatch_response(payload, resolve_waiter=True)
            if self.debug:
                _LOGGER.debug(
                    "Node request timeout id=%s command=%s",
                    pending.request_id,
                    pending.command,
                )

    def _normalize_arguments(self, arguments: Any) -> list[str]:
        if arguments is None:
            return []
        if isinstance(arguments, str):
            return [a for a in arguments.split() if a]
        if isinstance(arguments, (list, tuple)):
            return [str(a) for a in arguments]
        return [str(arguments)]

    @staticmethod
    def _canonical_command(command: str | None) -> str:
        cmd = (command or "").strip().lower()
        if cmd == "discover":
            return "discovery"
        return cmd

    def _base_payload(
        self,
        *,
        node: str | None,
        target: str | None,
        command: str | None,
        request_id: int | None,
        channel_idx: int,
        raw: str,
        success: bool,
        error: str | None = None,
        data: dict[str, Any] | None = None,
        timestamp: str | None = None,
        latency_ms: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "node": node,
            "target": target,
            "command": command,
            "request_id": request_id,
            "success": success,
            "error": error,
            "timestamp": timestamp or dt_util.utcnow().isoformat(),
            "raw": raw,
            "channel_idx": channel_idx,
            "entry_id": self.entry.entry_id,
            "source": node,
            "destination": target,
            "raw_message": raw,
            "error_code": error,
            "parameters": dict(data or {}),
            "kind": (command or "unknown"),
            "latency_ms": latency_ms,
        }
        if data:
            for key, value in data.items():
                if key in {
                    "node",
                    "target",
                    "command",
                    "request_id",
                    "success",
                    "error",
                    "timestamp",
                    "raw",
                    "channel_idx",
                    "entry_id",
                }:
                    continue
                payload[key] = value
        return payload

    def _shape_response_data(
        self, command: str | None, body: str, response, pending
    ) -> dict[str, Any]:
        """Build flat, HA-friendly data; preserve unknowns under ``extra``."""
        assert self._mcrpc is not None
        cmd = (pending.command if pending else None) or command or response.command_hint

        if response.kind.name == "Pong" or cmd == "ping":
            return {"pong": True, "extra": {}}

        if response.kind.name == "Error":
            return {"extra": dict(response.parameters), "detail": response.error_code}

        if response.kind.name == "Ok":
            return {
                "ok": True,
                "detail": response.ok_detail,
                "extra": dict(response.parameters),
            }

        if response.kind.name == "Status" or cmd == "status":
            shaped = self._mcrpc.parse_status_fields(body)
            return {
                k: v
                for k, v in shaped.items()
                if k not in {"parameters", "fields", "raw", "request_id"}
            }

        if response.kind.name == "Discover" or cmd in {"discover", "discovery"}:
            shaped = self._mcrpc.parse_discover_fields(body)
            return {
                k: v
                for k, v in shaped.items()
                if k not in {"parameters", "fields", "raw", "request_id"}
            }

        if response.kind.name == "Gps" or cmd == "gps":
            shaped = self._mcrpc.parse_gps(body)
            return {
                k: v
                for k, v in shaped.items()
                if k not in {"parameters", "fields", "raw", "request_id"}
            }

        if cmd in {"battery", "voltage", "charging"} or response.kind.name in {
            "Battery",
            "Voltage",
            "Charging",
        }:
            shaped = self._mcrpc.parse_battery(body)
            return {
                k: v
                for k, v in shaped.items()
                if k not in {"parameters", "fields", "raw", "request_id"}
            }

        if response.kind.name == "Caps" or cmd == "caps":
            caps = response.caps or self._mcrpc.parse_caps_blob(body)
            return {"capabilities": caps, "extra": {}}

        if response.kind.name == "Help" or cmd == "help":
            return {"commands": response.help_commands, "extra": {}}

        return {"extra": dict(response.parameters), **response.parameters}

    def _strip_parsed(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a raw-only view when parse=false."""
        keep = {
            "node",
            "source",
            "target",
            "destination",
            "command",
            "request_id",
            "success",
            "error",
            "error_code",
            "timestamp",
            "raw",
            "raw_message",
            "channel_idx",
            "entry_id",
            "latency_ms",
            "kind",
        }
        return {k: payload.get(k) for k in keep}

    def _dispatch_response(
        self, payload: dict[str, Any], *, resolve_waiter: bool = True
    ) -> None:
        command = payload.get("command")
        if command:
            self._last_by_command[str(command)] = payload

        shaped = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else payload
        self.registry.apply_response(
            node_id=payload.get("node"),
            command=command,
            data=shaped or {},
            channel=payload.get("channel_idx"),
            rssi=payload.get("rssi"),
            timestamp_iso=payload.get("timestamp"),
        )

        self.hass.bus.async_fire(EVENT_NODE_RESPONSE, payload)
        self.hass.bus.async_fire(EVENT_MCRPC_RESPONSE, payload)

        rid = payload.get("request_id")
        if resolve_waiter and rid is not None and rid in self._waiters:
            # Unicast waiters only — broadcast uses buckets
            if rid not in self._broadcast_buckets:
                fut = self._waiters.pop(rid)
                if not fut.done():
                    fut.set_result(payload)

        if self._entity_bridge:
            self._entity_bridge.handle_response(payload)

    def _dispatch_event(self, payload: dict[str, Any]) -> None:
        self.registry.apply_event(
            node_id=payload.get("node"),
            event_name=payload.get("event") or payload.get("event_name"),
            parameters=payload.get("parameters") or {},
            channel=payload.get("channel_idx"),
            timestamp_iso=payload.get("timestamp"),
        )
        self.hass.bus.async_fire(EVENT_NODE_EVENT, payload)
        self.hass.bus.async_fire(EVENT_MCRPC_EVENT, payload)
        if self._entity_bridge:
            self._entity_bridge.handle_event(payload)

    def _broadcast_result(self, pending, responses: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "request_id": pending.request_id,
            "target": pending.target,
            "command": pending.command,
            "arguments": pending.arguments,
            "channel_idx": pending.channel_idx,
            "entry_id": self.entry.entry_id,
            "raw_request": pending.raw_request,
            "responses": responses,
            "count": len(responses),
            "success": len(responses) > 0,
            "error": None if responses else "timeout",
        }
        # Soft compat: expose first response fields at top level
        if responses:
            first = responses[0]
            for key in ("source", "node", "raw", "latency_ms", "success"):
                if key in first:
                    result[key] = first[key]
            result["parameters"] = first.get("parameters") or {}
        return result

    async def _async_send_line(
        self,
        *,
        target: str,
        command: str,
        arguments: list[str],
        request_id: int | None,
        timeout: float,
        channel_idx: int,
        broadcast: bool,
    ) -> dict[str, Any]:
        self._ensure_ready()
        api = self.coordinator.api
        if not api or not api.connected:
            raise RuntimeError("MeshCore device is not connected")

        line, pending = self._correlator.build(
            target,
            command,
            arguments=arguments,
            request_id=request_id,
            timeout=timeout,
            channel_idx=channel_idx,
            broadcast=broadcast,
            meta={
                "broadcast": broadcast,
                "sent_at": time.monotonic(),
            },
        )

        if self.debug:
            _LOGGER.debug("Node request channel=%s line=%r", channel_idx, line)

        result = await api.mesh_core.commands.send_chan_msg(
            channel_idx, line, timestamp=int(time.time())
        )
        from meshcore.events import EventType

        if result.type == EventType.ERROR:
            self._correlator.take(pending.request_id)
            self._note_error(str(result.payload))
            raise RuntimeError(f"Failed to send node request: {result.payload}")

        self.stats["tx_count"] = int(self.stats["tx_count"]) + 1
        self.stats["last_tx"] = {
            "time": dt_util.utcnow().isoformat(),
            "raw": line,
            "channel": channel_idx,
            "request_id": pending.request_id,
            "command": pending.command,
        }

        if broadcast:
            self._broadcast_buckets[pending.request_id] = []

        return {
            "request_id": pending.request_id,
            "target": pending.target,
            "command": pending.command,
            "arguments": pending.arguments,
            "channel_idx": channel_idx,
            "timeout": timeout,
            "entry_id": self.entry.entry_id,
            "raw_request": line,
            "pending": True,
        }

    async def async_request(
        self,
        *,
        target: str | None = None,
        command: str,
        arguments: Any = None,
        timeout: float | None = None,
        wait: bool = True,
        parse: bool = True,
        channel_idx: int | None = None,
        request_id: int | None = None,
        broadcast: bool = False,
    ) -> dict[str, Any]:
        """Ask a node (or all, when broadcast). Waits for reply by default."""
        if broadcast:
            return await self.async_broadcast(
                command=command,
                arguments=arguments,
                timeout=timeout,
                wait=wait,
                parse=parse,
                channel_idx=channel_idx,
                request_id=request_id,
            )

        self._ensure_ready()
        cmd = self._canonical_command(command)
        if not cmd:
            raise ValueError("command is required")
        dest = (target or "").strip()
        if not dest:
            raise ValueError("target is required")

        # Serve from cache when fresh (discover/status/battery/caps)
        if wait and cmd in {"discovery", "status", "battery", "caps"}:
            if not self.registry.needs_refresh(dest, cmd):
                node = self.registry.get(dest)
                if node:
                    cached = self._cached_response(dest, cmd, node)
                    return cached if parse else self._strip_parsed(cached)

        to = float(timeout if timeout is not None else self.default_timeout)
        ch = self.default_channel if channel_idx is None else int(channel_idx)
        args = self._normalize_arguments(arguments)

        sent = await self._async_send_line(
            target=dest,
            command=cmd,
            arguments=args,
            request_id=request_id,
            timeout=to,
            channel_idx=ch,
            broadcast=False,
        )
        if not wait:
            return sent

        self.stats["tx_wait_expected"] = int(self.stats["tx_wait_expected"]) + 1
        result = await self._await_response(sent["request_id"], to)
        return result if parse else self._strip_parsed(result)

    def _cached_response(self, target: str, command: str, node) -> dict[str, Any]:
        data: dict[str, Any]
        if command in {"discover", "discovery"}:
            data = {
                "device": node.display_name,
                "profile": node.profile,
                "board": node.board,
                "firmware": node.firmware,
                "protocol": node.protocol,
                "sdk": node.sdk,
                "features": dict(node.features),
                "capabilities": list(node.capabilities),
                "extra": dict(node.extra),
                "cached": True,
            }
        elif command == "status":
            data = {**node.last_status, "extra": dict(node.extra), "cached": True}
        elif command == "battery":
            data = {**node.battery, "cached": True}
        elif command == "caps":
            data = {"capabilities": list(node.capabilities), "cached": True}
        else:
            data = {"cached": True}
        return self._base_payload(
            node=target,
            target=target,
            command=command,
            request_id=None,
            channel_idx=node.channel if node.channel is not None else self.default_channel,
            raw="",
            success=True,
            data=data,
            timestamp=node.last_seen_iso,
        )

    async def async_broadcast(
        self,
        *,
        command: str,
        arguments: Any = None,
        timeout: float | None = None,
        wait: bool = True,
        parse: bool = True,
        channel_idx: int | None = None,
        request_id: int | None = None,
    ) -> dict[str, Any]:
        """Ask all listening nodes. When wait=true, collect responses[] until timeout."""
        self._ensure_ready()
        cmd = self._canonical_command(command)
        if not cmd:
            raise ValueError("command is required")

        to = float(timeout if timeout is not None else self.default_timeout)
        ch = self.default_channel if channel_idx is None else int(channel_idx)
        args = self._normalize_arguments(arguments)

        sent = await self._async_send_line(
            target="all",
            command=cmd,
            arguments=args,
            request_id=request_id,
            timeout=to,
            channel_idx=ch,
            broadcast=True,
        )
        if not wait:
            return sent

        self.stats["tx_wait_expected"] = int(self.stats["tx_wait_expected"]) + 1
        pending = self._correlator.peek(sent["request_id"])
        result = await self._await_broadcast(sent["request_id"], to, pending)
        if not parse:
            raw_responses = []
            for item in result.get("responses") or []:
                raw_responses.append(self._strip_parsed(item))
            result = {**result, "responses": raw_responses}
            if "parameters" in result:
                result["parameters"] = {}
        return result

    async def async_raw(
        self,
        *,
        message: str,
        timeout: float | None = None,
        wait: bool = False,
        parse: bool = True,
        channel_idx: int | None = None,
    ) -> dict[str, Any]:
        """Send a raw channel line (debug / advanced)."""
        self._ensure_ready()
        text = (message or "").strip()
        if not text:
            raise ValueError("message is required")

        to = float(timeout if timeout is not None else self.default_timeout)
        ch = self.default_channel if channel_idx is None else int(channel_idx)

        result, req = self._mcrpc.parse(text)

        if result == self._mcrpc.ParseResult.Ok:
            dest = req.target
            if req.address_kind.name == "Group":
                dest = f"group:{req.target}"
            elif req.address_kind.name == "All":
                dest = "all"
            elif req.address_kind.name == "Self":
                dest = "self"
            is_broadcast = req.address_kind.name == "All"
            sent = await self._async_send_line(
                target=dest,
                command=self._canonical_command(req.command),
                arguments=list(req.args),
                request_id=req.request_id if req.has_request_id else None,
                timeout=to,
                channel_idx=ch,
                broadcast=is_broadcast,
            )
            if not wait:
                return sent
            if is_broadcast:
                pending = self._correlator.peek(sent["request_id"])
                out = await self._await_broadcast(sent["request_id"], to, pending)
            else:
                out = await self._await_response(sent["request_id"], to)
            if not parse:
                if "responses" in out:
                    out = {
                        **out,
                        "responses": [self._strip_parsed(r) for r in out["responses"]],
                    }
                else:
                    out = self._strip_parsed(out)
            return out

        api = self.coordinator.api
        if not api or not api.connected:
            raise RuntimeError("MeshCore device is not connected")
        send_result = await api.mesh_core.commands.send_chan_msg(
            ch, text, timestamp=int(time.time())
        )
        from meshcore.events import EventType

        if send_result.type == EventType.ERROR:
            self._note_error(str(send_result.payload))
            raise RuntimeError(f"Failed to send raw message: {send_result.payload}")
        self.stats["tx_count"] = int(self.stats["tx_count"]) + 1
        self.stats["last_tx"] = {
            "time": dt_util.utcnow().isoformat(),
            "raw": text,
            "channel": ch,
        }
        return {
            "raw_request": text,
            "channel_idx": ch,
            "entry_id": self.entry.entry_id,
            "pending": False,
            "correlated": False,
        }

    async def async_send(self, **kwargs: Any) -> dict[str, Any]:
        """Backward-compatible low-level send."""
        broadcast = bool(kwargs.get("broadcast", False))
        if broadcast:
            return await self.async_broadcast(
                command=kwargs.get("command", ""),
                arguments=kwargs.get("arguments"),
                timeout=kwargs.get("timeout"),
                wait=False,
                channel_idx=kwargs.get("channel_idx"),
                request_id=kwargs.get("request_id"),
            )
        return await self.async_request(
            target=kwargs.get("target") or "",
            command=kwargs.get("command", ""),
            arguments=kwargs.get("arguments"),
            timeout=kwargs.get("timeout"),
            wait=False,
            channel_idx=kwargs.get("channel_idx"),
            request_id=kwargs.get("request_id"),
        )

    async def _await_response(self, request_id: int, timeout: float) -> dict[str, Any]:
        loop = self.hass.loop
        fut: asyncio.Future = loop.create_future()
        self._waiters[request_id] = fut
        try:
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError:
            self._waiters.pop(request_id, None)
            if self._correlator:
                self._correlator.take(request_id)
            self.stats["timeouts"] = int(self.stats["timeouts"]) + 1
            return self._base_payload(
                node=None,
                target=None,
                command=None,
                request_id=request_id,
                channel_idx=self.default_channel,
                raw="",
                success=False,
                error="timeout",
            )

    async def _await_broadcast(
        self, request_id: int, timeout: float, pending
    ) -> dict[str, Any]:
        """Collect all replies until the timeout window elapses."""
        loop = self.hass.loop
        fut: asyncio.Future = loop.create_future()
        self._waiters[request_id] = fut
        self._broadcast_buckets.setdefault(request_id, [])
        try:
            # Prefer completing via timeout sweep / sleep
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            raise
        finally:
            self._waiters.pop(request_id, None)
            bucket = self._broadcast_buckets.pop(request_id, [])
            if self._correlator:
                self._correlator.take(request_id)
        if not bucket:
            self.stats["timeouts"] = int(self.stats["timeouts"]) + 1
        if pending is None:
            # Minimal pending stub for result shape
            class _P:
                pass

            pending = _P()
            pending.request_id = request_id
            pending.target = "all"
            pending.command = None
            pending.arguments = []
            pending.channel_idx = self.default_channel
            pending.raw_request = ""
        return self._broadcast_result(pending, bucket)

    def list_cached_nodes(self) -> dict[str, Any]:
        mapped = self.device_mapper.map_all(self.registry.all_nodes())
        return {
            "nodes": self.registry.list_dicts(),
            "devices_preview": [
                {
                    "identifiers": list(d["identifiers"]),
                    "name": d["name"],
                    "model": d["model"],
                    "sw_version": d.get("sw_version"),
                    "capabilities": d.get("_mcrpc", {}).get("capabilities"),
                }
                for d in mapped
            ],
            "entry_id": self.entry.entry_id,
            "count": len(self.registry.all_nodes()),
        }

    def get_capabilities(self, node: str) -> list[str]:
        return self.registry.get_capabilities(node)

    def has_capability(self, node: str, capability: str) -> bool:
        return self.registry.has_capability(node, capability)

    def diagnostics_dict(self) -> dict[str, Any]:
        """Payload for Home Assistant Diagnostics download."""
        api = getattr(self.coordinator, "api", None)
        connected = bool(api and getattr(api, "connected", False))
        conn_type = self.entry.data.get("connection_type")
        pending = []
        if self._correlator:
            for p in self._correlator._pending.values():  # noqa: SLF001 — diagnostics
                pending.append(
                    {
                        "request_id": p.request_id,
                        "target": p.target,
                        "command": p.command,
                        "broadcast": bool(p.meta.get("broadcast")),
                        "raw": p.raw_request,
                    }
                )
        pol = self.policy()
        rtt_count = int(self.stats.get("rtt_count") or 0)
        avg_rtt = (
            round(float(self.stats.get("rtt_sum_ms") or 0.0) / rtt_count, 1)
            if rtt_count
            else None
        )
        expected = int(self.stats.get("tx_wait_expected") or 0)
        matched = int(self.stats.get("rx_matched") or 0)
        timeouts = int(self.stats.get("timeouts") or 0)
        packet_loss = None
        if expected > 0:
            packet_loss = round(max(0.0, 1.0 - (matched / expected)) * 100.0, 1)
        elif timeouts > 0 and matched == 0:
            packet_loss = 100.0

        listen = pol.listening_channel_indexes()
        return {
            "enabled": self.enabled,
            "node_requests_enabled": self.enabled,
            "listening_channels": "all" if listen is None else listen,
            "listen_mode": pol.listen_mode,
            "accepted_addressing": {
                "broadcast": pol.accept_broadcast,
                "addressed": pol.accept_addressed,
                "bare": pol.accept_bare,
            },
            "allowed_senders_mode": pol.sender_mode,
            "allow_list": sorted(pol.allow_list),
            "reply_identity": pol.reply_identity,
            "answer_requests": pol.answer_requests,
            "pending_requests": pending,
            "known_nodes": self.registry.list_dicts(),
            "average_rtt_ms": avg_rtt,
            "packet_loss_percent": packet_loss,
            "last_rx": self.stats.get("last_rx"),
            "last_tx": self.stats.get("last_tx"),
            "parser_errors": self.stats.get("parser_errors"),
            "connected": connected,
            "transport": conn_type,
            "current_channel": self.default_channel,
            "default_timeout": self.default_timeout,
            "capabilities": self.capability_cache,
            "outstanding_timeouts": timeouts,
            "denied_requests": self.stats.get("denied"),
            "answered_requests": self.stats.get("answered"),
            "recent_denials": self.stats.get("recent_denials"),
            "recent_protocol_errors": self.stats.get("recent_errors"),
            "parser_statistics": {
                "parse_ok": self.stats.get("parse_ok"),
                "parse_unknown": self.stats.get("parse_unknown"),
                "parser_errors": self.stats.get("parser_errors"),
                "rx_count": self.stats.get("rx_count"),
                "tx_count": self.stats.get("tx_count"),
                "errors": self.stats.get("errors"),
            },
            "policy": pol.summary(),
            "recent_traces": self.stats.get("recent_traces"),
            "device_mapper_preview": self.list_cached_nodes().get("devices_preview"),
        }

    def _build_answer_body(self, req) -> str:
        """Minimal HA-side answers for inbound mesh requests."""
        assert self._mcrpc is not None
        cmd = (req.command or "").lower()
        rid = req.request_id if getattr(req, "has_request_id", False) else None
        name = self.policy().local_name or "ha"

        if cmd == "ping":
            body = "pong"
        elif cmd == "status":
            body = f"status name={name} profile=ha"
        elif cmd in {"discover", "discovery"}:
            body = (
                f"discovery name={name} profile=ha protocol=1.0 "
                f"sdk={getattr(self._mcrpc, 'SDK_VERSION', '1.0.0')}"
            )
        elif cmd in {"help", "caps"}:
            body = "ok ha ping status discovery"
        else:
            body = self._mcrpc.build_error("unsupported")
        return self._mcrpc.prefix_request_id(body, rid)

    async def _async_send_answer(self, channel_idx: int, text: str) -> None:
        """Send a reply using the configured reply identity (multi-radio ready)."""
        pol = self.policy()
        domain_data = self.hass.data.get(DOMAIN, {})
        reply_entry_id = pol.resolve_reply_entry_id(domain_data)
        coordinator = domain_data.get(reply_entry_id) or self.coordinator
        api = getattr(coordinator, "api", None)
        if not api or not getattr(api, "connected", False):
            self._note_error("reply_identity_offline")
            return
        fallback_timestamp = int(time.time())
        result = await api.mesh_core.commands.send_chan_msg(
            int(channel_idx), text, timestamp=fallback_timestamp
        )
        from meshcore.events import EventType

        if getattr(result, "type", None) == EventType.ERROR:
            self._note_error(str(getattr(result, "payload", "send_error")))
            self._trace(
                "tx_error",
                channel_idx=channel_idx,
                transmitted_payload=text,
                error=str(getattr(result, "payload", "")),
            )
            return
        self.stats["answered"] = int(self.stats["answered"]) + 1
        self.stats["tx_count"] = int(self.stats["tx_count"]) + 1
        self.stats["last_tx"] = {
            "time": dt_util.utcnow().isoformat(),
            "raw": text,
            "channel": channel_idx,
            "reply": True,
            "reply_entry_id": reply_entry_id,
        }
        self._trace(
            "tx",
            channel_idx=channel_idx,
            transmitted_payload=text,
            reply_entry_id=reply_entry_id,
        )

        send_timestamp = fallback_timestamp
        payload = getattr(result, "payload", None)
        if isinstance(payload, dict):
            device_ts = payload.get("timestamp")
            if isinstance(device_ts, (int, float)):
                send_timestamp = int(device_ts)

        # Keep chat history and radio transport synchronized: every transmitted
        # mcRPC auto-reply must flow through the same outgoing message pipeline.
        self.hass.bus.async_fire(
            f"{DOMAIN}_message_sent",
            {
                "origin": "mcrpc_answer",
                "device": reply_entry_id,
                "message_type": "channel",
                "message": text,
                "channel_idx": int(channel_idx),
                "timestamp": int(time.time()),
                "send_timestamp": send_timestamp,
                "send_id": f"mcrpc_{uuid.uuid4().hex[:8]}",
            },
        )

    _BARE_COMMANDS = frozenset(
        {
            "ping",
            "status",
            "discover",
            "discovery",
            "gps",
            "battery",
            "help",
            "caps",
            "voltage",
            "charging",
        }
    )

    def _answer_dedup_key(
        self, *, channel_idx: int, body: str, send_id: str | None, timestamp: str | None
    ) -> str:
        # Prefer send_id so message_sent + immediate meshcore_message collapse
        if send_id:
            return f"{channel_idx}|{body}|sid:{send_id}"
        return f"{channel_idx}|{body}|ts:{timestamp or ''}"

    def _already_answered(self, key: str) -> bool:
        now = time.monotonic()
        # Drop stale keys (>30s)
        stale = [k for k, t in self._recent_answer_keys.items() if now - t > 30.0]
        for k in stale:
            self._recent_answer_keys.pop(k, None)
        return key in self._recent_answer_keys

    def _mark_answered(self, key: str) -> None:
        self._recent_answer_keys[key] = time.monotonic()

    def _maybe_answer_inbound(
        self,
        *,
        body: str,
        source: str | None,
        channel_idx: int,
        message_type: str | None = None,
        outgoing: bool = False,
        send_id: str | None = None,
        timestamp: str | None = None,
        transport: str = "meshcore_message",
    ) -> None:
        """Evaluate policy and answer inbound requests when allowed."""
        assert self._mcrpc is not None
        pol = self.policy()
        self._trace(
            "answer_eval",
            transport=transport,
            raw_payload=body,
            sender=source,
            destination=None,
            channel_idx=channel_idx,
            message_type=message_type,
            outgoing=outgoing,
            normalized_text=body,
        )
        if not pol.answer_requests:
            self._trace("drop", reason="answer_requests_disabled", channel_idx=channel_idx)
            return

        dedup = self._answer_dedup_key(
            channel_idx=int(channel_idx), body=body, send_id=send_id, timestamp=timestamp
        )
        if self._already_answered(dedup):
            self._trace("drop", reason="duplicate", channel_idx=channel_idx, body=body)
            return

        parse_result, req = self._mcrpc.parse(body)
        parse_ok = parse_result == self._mcrpc.ParseResult.Ok

        # Bare: "ping" alone is parsed as MissingCommand with target=ping
        if not parse_ok:
            if (
                parse_result == self._mcrpc.ParseResult.MissingCommand
                and (req.target or "").lower() in self._BARE_COMMANDS
            ):
                req.command = req.target
                req.target = ""
                req.has_request_id = False
            elif parse_result == self._mcrpc.ParseResult.MissingTarget:
                tokens = body.strip().split()
                if not tokens:
                    self._trace("drop", reason="empty_bare", channel_idx=channel_idx)
                    return
                cmd_token = tokens[0]
                if cmd_token.startswith("#") and len(tokens) > 1:
                    cmd_token = tokens[1]
                req = self._mcrpc.Request()
                req.command = cmd_token
                req.has_request_id = False
            else:
                self.stats["parser_errors"] = int(self.stats["parser_errors"]) + 1
                self.stats["parse_unknown"] = int(self.stats["parse_unknown"]) + 1
                self._trace(
                    "drop",
                    reason="parser_reject",
                    parser_result=parse_result.name,
                    channel_idx=channel_idx,
                    body=body,
                )
                return

        self._trace(
            "parser",
            parser_result=parse_result.name if parse_ok else f"bare:{parse_result.name}",
            destination=getattr(req, "target", None) or ("all" if parse_ok and getattr(req.address_kind, "name", "") == "All" else None),
            command=getattr(req, "command", None),
            address_kind=getattr(getattr(req, "address_kind", None), "name", None),
            channel_idx=channel_idx,
        )

        req.command = self._canonical_command(getattr(req, "command", ""))

        decision = pol.decide_inbound_request(
            channel_idx=channel_idx,
            sender_name=source,
            req=req,
            parse_ok=parse_ok,
            contact_names=self._contact_names(),
        )
        self._trace(
            "dispatcher",
            dispatcher_result=decision.reason,
            addressing=decision.addressing,
            allow=decision.allow,
            channel_idx=channel_idx,
            selected_handler=req.command if decision.allow else None,
        )
        if not decision.allow:
            self._note_denial(
                decision.reason, source=source, channel_idx=channel_idx
            )
            return

        reply = self._build_answer_body(req)
        self._mark_answered(dedup)
        self._trace(
            "response",
            generated_response=reply,
            transmitted_payload=reply,
            channel_idx=channel_idx,
            selected_handler=req.command,
        )
        self.hass.async_create_task(self._async_send_answer(int(channel_idx), reply))

    @callback
    def _on_message_sent(self, event: Event) -> None:
        """Fast path: HA Chat / send_channel_message → answer without 4s delay."""
        data = event.data or {}
        if data.get("origin") == "mcrpc_answer":
            return
        if data.get("device") != self.entry.entry_id:
            return
        if data.get("message_type") != "channel":
            return
        if not self._correlator or not self._mcrpc:
            return
        raw = (data.get("message") or "").strip()
        if not raw:
            return
        body = self._mcrpc.strip_sender_prefix(raw)
        if self._correlator.is_outbound_echo(body):
            self._trace("drop", reason="outbound_echo", transport="message_sent", body=body)
            return
        self._trace(
            "rx",
            transport="message_sent",
            raw_payload=raw,
            sender=self.entry.data.get("name"),
            channel_idx=data.get("channel_idx", self.default_channel),
            message_type="channel",
            outgoing=True,
            normalized_text=body,
        )
        self._maybe_answer_inbound(
            body=body,
            source=self.entry.data.get("name"),
            channel_idx=int(data.get("channel_idx", self.default_channel)),
            message_type="channel",
            outgoing=True,
            send_id=data.get("send_id"),
            timestamp=str(data.get("send_timestamp") or data.get("timestamp") or ""),
            transport="message_sent",
        )

    @callback
    def _on_meshcore_message(self, event: Event) -> None:
        data = event.data or {}
        raw = data.get("message") or ""
        if not raw or not self._correlator or not self._mcrpc:
            return

        # Terminal outgoing re-fire after RX_LOG — already handled via message_sent
        if data.get("outgoing") and data.get("rx_log_data") is not None:
            self._trace(
                "drop",
                reason="outgoing_terminal_refire",
                channel_idx=data.get("channel_idx"),
                body=raw,
            )
            return

        body = self._mcrpc.strip_sender_prefix(raw)
        if self._correlator.is_outbound_echo(body):
            self._trace("drop", reason="outbound_echo", transport="meshcore_message", body=body)
            return

        kind, response, evt, pending = self._correlator.classify_inbound(body)
        source = data.get("sender_name")
        channel_idx = data.get("channel_idx", self.default_channel)
        ts = data.get("timestamp") or dt_util.utcnow().isoformat()
        rssi = data.get("rssi") or data.get("RSSI")

        self._trace(
            "rx",
            transport="meshcore_message",
            raw_payload=raw,
            sender=source,
            destination=None,
            channel_idx=channel_idx,
            message_type=data.get("message_type"),
            outgoing=bool(data.get("outgoing")),
            normalized_text=body,
            classify_kind=kind,
            response_kind=getattr(getattr(response, "kind", None), "name", None),
            pending=bool(pending),
        )

        self.stats["rx_count"] = int(self.stats["rx_count"]) + 1
        self.stats["last_rx"] = {
            "time": ts,
            "raw": body,
            "source": source,
            "channel": channel_idx,
        }

        if kind == "event" and evt is not None:
            traffic = self.policy().decide_inbound_traffic(
                channel_idx=channel_idx,
                sender_name=source,
                contact_names=self._contact_names(),
            )
            if not traffic.allow:
                self._note_denial(
                    traffic.reason, source=source, channel_idx=channel_idx
                )
                return
            self.stats["parse_ok"] = int(self.stats["parse_ok"]) + 1
            payload = {
                "node": source,
                "event": evt.name,
                "event_name": evt.name,
                "command": evt.name,
                "request_id": None,
                "success": True,
                "error": None,
                "timestamp": ts,
                "raw": body,
                "raw_message": body,
                "channel_idx": channel_idx,
                "entry_id": self.entry.entry_id,
                "parameters": evt.parameters,
                "extra": dict(evt.parameters),
                "source": source,
                "rssi": rssi,
            }
            for key, value in evt.parameters.items():
                payload.setdefault(key, value)
            self._dispatch_event(payload)
            return

        if kind == "response" and response is not None:
            # Correlated replies to our outbound requests always accepted.
            # Unmatched Unknown → may be an inbound request instead.
            if response.kind.name == "Unknown" and pending is None:
                self._maybe_answer_inbound(
                    body=body,
                    source=source,
                    channel_idx=int(channel_idx),
                    message_type=data.get("message_type"),
                    outgoing=bool(data.get("outgoing")),
                    send_id=data.get("send_id"),
                    timestamp=ts,
                    transport="meshcore_message",
                )
                return

            self.stats["parse_ok"] = int(self.stats["parse_ok"]) + 1
            command = (pending.command if pending else None) or response.command_hint
            shaped = self._shape_response_data(command, body, response, pending)
            success = response.kind.name != "Error"
            error = response.error_code if not success else None
            if error:
                self._note_error(error)
            node = source or shaped.get("device") or shaped.get("name")

            latency_ms = None
            if pending and pending.meta.get("sent_at") is not None:
                latency_ms = round(
                    (time.monotonic() - float(pending.meta["sent_at"])) * 1000, 1
                )
            self._record_rtt(latency_ms)

            payload = self._base_payload(
                node=node,
                target=pending.target if pending else None,
                command=command,
                request_id=response.request_id,
                channel_idx=channel_idx,
                raw=body,
                success=success,
                error=error,
                data=shaped,
                timestamp=ts,
                latency_ms=latency_ms,
            )
            payload["parameters"] = shaped
            payload["rssi"] = rssi
            payload["parsed"] = shaped
            payload["raw_payload"] = body

            # Broadcast: accumulate; unicast: resolve waiter
            rid = response.request_id
            if rid is not None and rid in self._broadcast_buckets:
                item = {
                    "source": node,
                    "node": node,
                    "request_id": rid,
                    "latency_ms": latency_ms,
                    "parsed": shaped,
                    "raw": body,
                    "raw_payload": body,
                    "success": success,
                    "error": error,
                    "command": command,
                    "parameters": shaped,
                    "channel_idx": channel_idx,
                    "rssi": rssi,
                    "timestamp": ts,
                }
                # Flatten known fields for convenience
                for k, v in shaped.items():
                    if k not in item:
                        item[k] = v
                self._broadcast_buckets[rid].append(item)
                # Still fire per-response events for automations
                self._dispatch_response(payload, resolve_waiter=False)
            else:
                self._dispatch_response(payload, resolve_waiter=True)

            if self.debug:
                _LOGGER.debug("Node response command=%s id=%s", command, response.request_id)
            return

        # Not classified as response/event — try inbound request
        self._maybe_answer_inbound(
            body=body,
            source=source,
            channel_idx=int(channel_idx),
            message_type=data.get("message_type"),
            outgoing=bool(data.get("outgoing")),
            send_id=data.get("send_id"),
            timestamp=ts,
            transport="meshcore_message",
        )

    def last_response(self, command: str) -> dict[str, Any] | None:
        return self._last_by_command.get(command)
