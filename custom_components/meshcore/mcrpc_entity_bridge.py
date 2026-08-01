"""Optional Entity Bridge stub — disabled by default.

Future work can map mcRPC responses/events onto:
  sensor, switch, button, device_tracker, binary_sensor

Do not auto-create entities until this bridge is explicitly enabled and
upstream UX is agreed.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class McRpcEntityBridge:
    """Reusable abstraction for later entity exposure (no-op for now)."""

    def __init__(self, hass: HomeAssistant, coordinator, entry) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.entry = entry
        self._enabled = False

    async def async_setup(self) -> None:
        self._enabled = True
        _LOGGER.info(
            "mcRPC Entity Bridge enabled (stub — no entities created yet) entry=%s",
            self.entry.entry_id,
        )

    async def async_unload(self) -> None:
        self._enabled = False

    def handle_response(self, payload: dict[str, Any]) -> None:
        """Hook for future sensor / tracker updates."""
        if not self._enabled:
            return
        _LOGGER.debug("EntityBridge (noop) response: %s", payload.get("command"))

    def handle_event(self, payload: dict[str, Any]) -> None:
        """Hook for future binary_sensor / event-driven entities."""
        if not self._enabled:
            return
        _LOGGER.debug("EntityBridge (noop) event: %s", payload.get("event_name"))
