"""Optional mesh node-request bridge (mcRPC is an internal transport).

Home Assistant users interact via ``meshcore.request`` / ``broadcast`` / ``raw``.
Wire protocol details stay inside the standalone ``mcrpc`` package.
"""

from __future__ import annotations

import asyncio
import logging
import time
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
    """Channel transport + correlation for mesh node requests."""

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
        self._last_by_command: dict[str, dict[str, Any]] = {}
        # node name → last discover / caps snapshot
        self.discover_cache: dict[str, dict[str, Any]] = {}
        self.capability_cache: dict[str, list[str]] = {}

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
        if self._timeout_unsub:
            self._timeout_unsub.cancel()
            self._timeout_unsub = None
        for fut in self._waiters.values():
            if not fut.done():
                fut.cancel()
        self._waiters.clear()
        if self._entity_bridge:
            await self._entity_bridge.async_unload()
            self._entity_bridge = None

    def _ensure_ready(self) -> None:
        if not self.enabled:
            raise RuntimeError(
                "Mesh node requests are disabled. Enable them under "
                "MeshCore → Configure → Global Settings."
            )
        if self._mcrpc is None or self._correlator is None:
            self._mcrpc = _import_mcrpc()
            self._correlator = self._mcrpc.RequestCorrelator(default_timeout=self.default_timeout)

    def _schedule_timeout_sweep(self) -> None:
        self.hass.async_create_task(self._async_timeout_sweep())
        self._timeout_unsub = self.hass.loop.call_later(5.0, self._schedule_timeout_sweep)

    async def _async_timeout_sweep(self) -> None:
        if not self._correlator:
            return
        for pending in self._correlator.expire():
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
            self._dispatch_response(payload)
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
            # Compat aliases used by early automations / docs
            "source": node,
            "destination": target,
            "raw_message": raw,
            "error_code": error,
            "parameters": dict(data or {}),
            "kind": (command or "unknown"),
        }
        if data:
            for key, value in data.items():
                if key in payload and key in {
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
            return {k: v for k, v in shaped.items() if k not in {"parameters", "fields", "raw", "request_id"}}

        if response.kind.name == "Discover" or cmd == "discover":
            shaped = self._mcrpc.parse_discover_fields(body)
            return {k: v for k, v in shaped.items() if k not in {"parameters", "fields", "raw", "request_id"}}

        if response.kind.name == "Gps" or cmd == "gps":
            shaped = self._mcrpc.parse_gps(body)
            return {k: v for k, v in shaped.items() if k not in {"parameters", "fields", "raw", "request_id"}}

        if cmd in {"battery", "voltage", "charging"} or response.kind.name in {
            "Battery",
            "Voltage",
            "Charging",
        }:
            shaped = self._mcrpc.parse_battery(body)
            return {k: v for k, v in shaped.items() if k not in {"parameters", "fields", "raw", "request_id"}}

        if response.kind.name == "Caps" or cmd == "caps":
            caps = response.caps or self._mcrpc.parse_caps_blob(body)
            return {"capabilities": caps, "extra": {}}

        if response.kind.name == "Help" or cmd == "help":
            return {"commands": response.help_commands, "extra": {}}

        # Generic: all key=value pairs as data + empty known set → extra = all
        return {
            "extra": dict(response.parameters),
            **response.parameters,
        }

    def _update_caches(self, node: str | None, command: str | None, data: dict[str, Any]) -> None:
        if not node:
            return
        if command == "discover" or data.get("device") or data.get("profile"):
            snapshot = {
                "device": data.get("device") or node,
                "profile": data.get("profile"),
                "board": data.get("board"),
                "firmware": data.get("firmware"),
                "protocol": data.get("protocol"),
                "sdk": data.get("sdk"),
                "features": data.get("features") or {},
                "capabilities": data.get("capabilities") or [],
                "extra": data.get("extra") or {},
                "updated": dt_util.utcnow().isoformat(),
            }
            key = str(snapshot["device"])
            self.discover_cache[key] = snapshot
            caps = list(snapshot["capabilities"] or [])
            for feat, val in (snapshot.get("features") or {}).items():
                if str(val).lower() in {"yes", "1", "true"} and feat not in caps:
                    caps.append(feat)
            if caps:
                self.capability_cache[key] = caps
                snapshot["capabilities"] = caps
        if command == "caps" and data.get("capabilities"):
            self.capability_cache[node] = list(data["capabilities"])
            if node in self.discover_cache:
                self.discover_cache[node]["capabilities"] = list(data["capabilities"])
                self.discover_cache[node]["updated"] = dt_util.utcnow().isoformat()

    def _dispatch_response(self, payload: dict[str, Any]) -> None:
        command = payload.get("command")
        if command:
            self._last_by_command[str(command)] = payload
        self._update_caches(payload.get("node"), command, payload.get("parameters") or payload)

        # Primary HA-native events + legacy aliases (no breaking change)
        self.hass.bus.async_fire(EVENT_NODE_RESPONSE, payload)
        self.hass.bus.async_fire(EVENT_MCRPC_RESPONSE, payload)

        rid = payload.get("request_id")
        if rid is not None and rid in self._waiters:
            fut = self._waiters.pop(rid)
            if not fut.done():
                fut.set_result(payload)

        if self._entity_bridge:
            self._entity_bridge.handle_response(payload)

    def _dispatch_event(self, payload: dict[str, Any]) -> None:
        self.hass.bus.async_fire(EVENT_NODE_EVENT, payload)
        self.hass.bus.async_fire(EVENT_MCRPC_EVENT, payload)
        if self._entity_bridge:
            self._entity_bridge.handle_event(payload)

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
        )

        if self.debug:
            _LOGGER.debug("Node request channel=%s line=%r", channel_idx, line)

        result = await api.mesh_core.commands.send_chan_msg(
            channel_idx, line, timestamp=int(time.time())
        )
        from meshcore.events import EventType

        if result.type == EventType.ERROR:
            self._correlator.take(pending.request_id)
            raise RuntimeError(f"Failed to send node request: {result.payload}")

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
        channel_idx: int | None = None,
        request_id: int | None = None,
        broadcast: bool = False,
    ) -> dict[str, Any]:
        """Ask a node (or all, when broadcast). Waits for reply by default (HA response)."""
        if broadcast:
            return await self.async_broadcast(
                command=command,
                arguments=arguments,
                timeout=timeout,
                wait=wait,
                channel_idx=channel_idx,
                request_id=request_id,
            )

        self._ensure_ready()
        cmd = (command or "").strip().lower()
        if not cmd:
            raise ValueError("command is required")
        dest = (target or "").strip()
        if not dest:
            raise ValueError("target is required")

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

        return await self._await_response(sent["request_id"], to)

    async def async_broadcast(
        self,
        *,
        command: str,
        arguments: Any = None,
        timeout: float | None = None,
        wait: bool = True,
        channel_idx: int | None = None,
        request_id: int | None = None,
    ) -> dict[str, Any]:
        """Ask all listening nodes (target ``all``). Waits for first reply by default."""
        self._ensure_ready()
        cmd = (command or "").strip().lower()
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

        # Broadcast may yield multiple replies; wait returns the first correlated one.
        return await self._await_response(sent["request_id"], to)

    async def async_raw(
        self,
        *,
        message: str,
        timeout: float | None = None,
        wait: bool = False,
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
            sent = await self._async_send_line(
                target=dest,
                command=req.command,
                arguments=list(req.args),
                request_id=req.request_id if req.has_request_id else None,
                timeout=to,
                channel_idx=ch,
                broadcast=req.address_kind.name == "All",
            )
            if wait:
                return await self._await_response(sent["request_id"], to)
            return sent

        # Unparsed: send verbatim without correlation
        api = self.coordinator.api
        if not api or not api.connected:
            raise RuntimeError("MeshCore device is not connected")
        send_result = await api.mesh_core.commands.send_chan_msg(
            ch, text, timestamp=int(time.time())
        )
        from meshcore.events import EventType

        if send_result.type == EventType.ERROR:
            raise RuntimeError(f"Failed to send raw message: {send_result.payload}")
        return {
            "raw_request": text,
            "channel_idx": ch,
            "entry_id": self.entry.entry_id,
            "pending": False,
            "correlated": False,
        }

    async def async_send(self, **kwargs: Any) -> dict[str, Any]:
        """Backward-compatible low-level send (``send_mcrpc``)."""
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

    def list_cached_nodes(self) -> dict[str, Any]:
        """Return discover/capability cache for automations and UI helpers."""
        nodes = []
        keys = sorted(set(self.discover_cache) | set(self.capability_cache))
        for name in keys:
            disc = self.discover_cache.get(name, {})
            nodes.append(
                {
                    "name": name,
                    "profile": disc.get("profile"),
                    "board": disc.get("board"),
                    "firmware": disc.get("firmware"),
                    "protocol": disc.get("protocol"),
                    "sdk": disc.get("sdk"),
                    "features": disc.get("features") or {},
                    "capabilities": self.capability_cache.get(name)
                    or disc.get("capabilities")
                    or [],
                    "extra": disc.get("extra") or {},
                    "updated": disc.get("updated"),
                }
            )
        return {"nodes": nodes, "entry_id": self.entry.entry_id}

    def get_capabilities(self, node: str) -> list[str]:
        """Capability registry lookup (from discover/caps cache)."""
        name = (node or "").strip()
        if not name:
            return []
        if name in self.capability_cache:
            return list(self.capability_cache[name])
        disc = self.discover_cache.get(name) or {}
        caps = list(disc.get("capabilities") or [])
        # Feature flags like gps=yes also count as capabilities
        for key, value in (disc.get("features") or {}).items():
            if str(value).lower() in {"yes", "1", "true"} and key not in caps:
                caps.append(key)
        return caps

    def has_capability(self, node: str, capability: str) -> bool:
        """True when the node advertised this capability (cached)."""
        cap = (capability or "").strip().lower()
        if not cap:
            return False
        return cap in {c.lower() for c in self.get_capabilities(node)}

    @callback
    def _on_meshcore_message(self, event: Event) -> None:
        data = event.data or {}
        raw = data.get("message") or ""
        if not raw or not self._correlator or not self._mcrpc:
            return

        body = self._mcrpc.strip_sender_prefix(raw)
        if self._correlator.is_outbound_echo(body):
            return

        kind, response, evt, pending = self._correlator.classify_inbound(body)
        source = data.get("sender_name")
        channel_idx = data.get("channel_idx", self.default_channel)
        ts = data.get("timestamp") or dt_util.utcnow().isoformat()

        if kind == "event" and evt is not None:
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
            }
            for key, value in evt.parameters.items():
                payload.setdefault(key, value)
            self._dispatch_event(payload)
            if self.debug:
                _LOGGER.debug("Node event %s params=%s", evt.name, evt.parameters)
            return

        if kind == "response" and response is not None:
            if response.kind.name == "Unknown" and pending is None:
                return

            command = (pending.command if pending else None) or response.command_hint
            shaped = self._shape_response_data(command, body, response, pending)
            success = response.kind.name != "Error"
            error = response.error_code if not success else None
            # Prefer device name from discover body when present
            node = source or shaped.get("device") or shaped.get("name")

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
            )
            # Keep parameters as the shaped dict for automations that expect it
            payload["parameters"] = shaped
            self._dispatch_response(payload)
            if self.debug:
                _LOGGER.debug("Node response command=%s id=%s", command, response.request_id)

    def last_response(self, command: str) -> dict[str, Any] | None:
        return self._last_by_command.get(command)
