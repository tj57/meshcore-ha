"""Diagnostics for MeshCore — includes optional node-request status."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    base: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "entry_id": entry.entry_id,
            "connection_type": entry.data.get("connection_type"),
            "name": entry.data.get("name"),
            # Never dump secrets / tokens
            "mcrpc_enabled": entry.data.get("mcrpc_enabled", False),
            "mcrpc_channel": entry.data.get("mcrpc_channel"),
            "mcrpc_timeout": entry.data.get("mcrpc_timeout"),
            "mcrpc_event_bridge": entry.data.get("mcrpc_event_bridge"),
        }
    }

    if coordinator is None:
        base["coordinator"] = None
        return base

    api = getattr(coordinator, "api", None)
    base["connection"] = {
        "connected": bool(api and getattr(api, "connected", False)),
        "pubkey_prefix": (getattr(coordinator, "pubkey", None) or "")[:12] or None,
    }

    bridge = getattr(coordinator, "mcrpc_bridge", None)
    if bridge is not None and getattr(bridge, "enabled", False):
        try:
            base["node_requests"] = bridge.diagnostics_dict()
        except Exception as ex:  # pragma: no cover
            base["node_requests"] = {"error": str(ex)}
    else:
        base["node_requests"] = {"enabled": False}

    return base
