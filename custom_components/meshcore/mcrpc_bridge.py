"""Optional mcRPC bridge — transport + HA events only (protocol lives in ``mcrpc``)."""

from __future__ import annotations

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
            "mcRPC Python package is not installed. "
            "Install from the mcrpc repository: pip install -e /path/to/mcrpc/python"
        ) from err


class McRpcBridge:
    """Send mcRPC over MeshCore channel text and fire structured HA events."""

    def __init__(self, hass: HomeAssistant, coordinator, entry) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.entry = entry
        self._unsub = None
        self._timeout_unsub = None
        self._mcrpc = None
        self._correlator = None
        self._entity_bridge = None
        self._last_by_command: dict[str, dict[str, Any]] = {}

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
            _LOGGER.debug("mcRPC disabled for entry %s", self.entry.entry_id)
            return

        self._mcrpc = _import_mcrpc()
        self._correlator = self._mcrpc.RequestCorrelator(default_timeout=self.default_timeout)

        if self.event_bridge_enabled:
            self._unsub = self.hass.bus.async_listen(
                EVENT_MESHCORE_MESSAGE, self._on_meshcore_message
            )

        # Periodic timeout sweep (reuse HA async job)
        self._timeout_unsub = self.hass.loop.call_later(5.0, self._schedule_timeout_sweep)

        if self.entry.data.get(CONF_MCRPC_ENTITY_BRIDGE, False):
            from .mcrpc_entity_bridge import McRpcEntityBridge

            self._entity_bridge = McRpcEntityBridge(self.hass, self.coordinator, self.entry)
            await self._entity_bridge.async_setup()

        _LOGGER.info("mcRPC bridge enabled for entry %s", self.entry.entry_id)

    async def async_unload(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._timeout_unsub:
            self._timeout_unsub.cancel()
            self._timeout_unsub = None
        if self._entity_bridge:
            await self._entity_bridge.async_unload()
            self._entity_bridge = None

    def _schedule_timeout_sweep(self) -> None:
        self.hass.async_create_task(self._async_timeout_sweep())
        self._timeout_unsub = self.hass.loop.call_later(5.0, self._schedule_timeout_sweep)

    async def _async_timeout_sweep(self) -> None:
        if not self._correlator:
            return
        for pending in self._correlator.expire():
            payload = {
                "source": None,
                "destination": pending.target,
                "command": pending.command,
                "request_id": pending.request_id,
                "parameters": {"error": "timeout"},
                "timestamp": dt_util.utcnow().isoformat(),
                "raw_message": "",
                "kind": "timeout",
                "error_code": "timeout",
                "channel_idx": pending.channel_idx,
                "entry_id": self.entry.entry_id,
            }
            self.hass.bus.async_fire(EVENT_MCRPC_RESPONSE, payload)
            if self.debug:
                _LOGGER.debug("mcRPC timeout request_id=%s command=%s", pending.request_id, pending.command)

    def _normalize_arguments(self, arguments: Any) -> list[str]:
        if arguments is None:
            return []
        if isinstance(arguments, str):
            return [a for a in arguments.split() if a]
        if isinstance(arguments, (list, tuple)):
            return [str(a) for a in arguments]
        return [str(arguments)]

    async def async_send(
        self,
        *,
        target: str | None,
        command: str,
        arguments: Any = None,
        request_id: int | None = None,
        timeout: float | None = None,
        broadcast: bool = False,
        channel_idx: int | None = None,
    ) -> dict[str, Any]:
        """Build, send, and track an mcRPC request. Response arrives via event."""
        if not self.enabled:
            raise RuntimeError("mcRPC is disabled for this MeshCore entry")
        if self._mcrpc is None or self._correlator is None:
            self._mcrpc = _import_mcrpc()
            self._correlator = self._mcrpc.RequestCorrelator(default_timeout=self.default_timeout)

        api = self.coordinator.api
        if not api or not api.connected:
            raise RuntimeError("MeshCore device is not connected")

        cmd = (command or "").strip().lower()
        if not cmd:
            raise ValueError("command is required")

        args = self._normalize_arguments(arguments)
        # Future-ready gps subcommands: start / stop / once / stream
        if cmd == "gps" and args:
            sub = args[0].lower()
            if sub in {"start", "stop", "once", "stream", "status"}:
                pass  # forwarded as-is to the device

        ch = self.default_channel if channel_idx is None else int(channel_idx)
        dest = "all" if broadcast else (target or "").strip()
        if not dest:
            raise ValueError("target is required unless broadcast=true")

        line, pending = self._correlator.build(
            dest,
            cmd,
            arguments=args,
            request_id=request_id,
            timeout=timeout if timeout is not None else self.default_timeout,
            channel_idx=ch,
            broadcast=broadcast,
        )

        if self.debug:
            _LOGGER.debug("mcRPC send channel=%s line=%r", ch, line)

        result = await api.mesh_core.commands.send_chan_msg(ch, line, timestamp=int(time.time()))
        from meshcore.events import EventType

        if result.type == EventType.ERROR:
            self._correlator.take(pending.request_id)
            raise RuntimeError(f"Failed to send mcRPC: {result.payload}")

        return {
            "raw_request": line,
            "request_id": pending.request_id,
            "target": pending.target,
            "command": pending.command,
            "arguments": pending.arguments,
            "channel_idx": ch,
            "timeout": timeout if timeout is not None else self.default_timeout,
            "entry_id": self.entry.entry_id,
        }

    @callback
    def _on_meshcore_message(self, event: Event) -> None:
        data = event.data or {}
        # Only process messages belonging to this config entry when present
        device = data.get("device") or data.get("entry_id")
        if device and device != self.entry.entry_id:
            # Channel inbound events use entity_id / no device — allow those
            if data.get("message_type") == "channel" and not device:
                pass
            elif device != self.entry.entry_id:
                # Outgoing echoes include device=entry_id; skip our own sends if raw matches
                pass

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
                "source": source,
                "destination": None,
                "command": evt.name,
                "request_id": None,
                "parameters": evt.parameters,
                "timestamp": ts,
                "raw_message": body,
                "channel_idx": channel_idx,
                "entry_id": self.entry.entry_id,
                "event_name": evt.name,
            }
            self.hass.bus.async_fire(EVENT_MCRPC_EVENT, payload)
            if self._entity_bridge:
                self._entity_bridge.handle_event(payload)
            if self.debug:
                _LOGGER.debug("mcRPC event %s params=%s", evt.name, evt.parameters)
            return

        if kind == "response" and response is not None:
            # Ignore unrelated chat unless it looks like protocol output
            if response.kind.name == "Unknown" and pending is None:
                return

            command = (pending.command if pending else None) or response.command_hint
            parameters = dict(response.parameters)
            # Enrich first-wave commands
            if response.kind.name == "Status" or (command == "status"):
                parameters = self._mcrpc.parse_status(body).parameters
            elif response.kind.name == "Discover" or command == "discover":
                disc = self._mcrpc.parse_discover(body)
                parameters = {
                    **disc.parameters,
                    "device": disc.device,
                    "profile": disc.profile,
                    "board": disc.board,
                    "firmware": disc.firmware,
                    "protocol": disc.protocol,
                    "sdk": disc.sdk,
                    "features": disc.features,
                    "capabilities": disc.capabilities,
                }
            elif response.kind.name == "Gps" or command == "gps":
                parameters = self._mcrpc.parse_gps(body)
            elif command in {"battery", "voltage", "charging"} or response.kind.name in {
                "Battery",
                "Voltage",
                "Charging",
            }:
                parameters = self._mcrpc.parse_battery(body)
            elif response.kind.name == "Caps" or command == "caps":
                parameters = {"caps": response.caps or self._mcrpc.parse_caps_blob(body)}
            elif response.kind.name == "Help" or command == "help":
                parameters = {"commands": response.help_commands}
            elif response.kind.name == "Pong":
                parameters = {"pong": True}

            payload = {
                "source": source,
                "destination": pending.target if pending else None,
                "command": command,
                "request_id": response.request_id,
                "parameters": parameters,
                "timestamp": ts,
                "raw_message": body,
                "kind": response.kind.name.lower(),
                "error_code": response.error_code,
                "channel_idx": channel_idx,
                "entry_id": self.entry.entry_id,
            }
            if command:
                self._last_by_command[command] = payload
            self.hass.bus.async_fire(EVENT_MCRPC_RESPONSE, payload)
            if self._entity_bridge:
                self._entity_bridge.handle_response(payload)
            if self.debug:
                _LOGGER.debug("mcRPC response command=%s id=%s", command, response.request_id)

    def last_response(self, command: str) -> dict[str, Any] | None:
        return self._last_by_command.get(command)
