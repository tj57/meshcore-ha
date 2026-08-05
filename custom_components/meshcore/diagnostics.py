"""Diagnostics for MeshCore — includes optional node-request status."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


def _entry_snapshot(entry: ConfigEntry) -> dict[str, Any]:
    return {
        "title": entry.title,
        "entry_id": entry.entry_id,
        "connection_type": entry.data.get("connection_type"),
        "name": entry.data.get("name"),
        # Never dump secrets / tokens
        "mcrpc_enabled": entry.data.get("mcrpc_enabled", False),
        "mcrpc_channel": entry.data.get("mcrpc_channel"),
        "mcrpc_timeout": entry.data.get("mcrpc_timeout"),
        "mcrpc_event_bridge": entry.data.get("mcrpc_event_bridge"),
        "mcrpc_listen_mode": entry.data.get("mcrpc_listen_mode"),
        "mcrpc_listen_channels": entry.data.get("mcrpc_listen_channels"),
        "mcrpc_accept_broadcast": entry.data.get("mcrpc_accept_broadcast"),
        "mcrpc_accept_addressed": entry.data.get("mcrpc_accept_addressed"),
        "mcrpc_accept_bare": entry.data.get("mcrpc_accept_bare"),
        "mcrpc_sender_mode": entry.data.get("mcrpc_sender_mode"),
        "mcrpc_reply_identity": entry.data.get("mcrpc_reply_identity"),
        "mcrpc_answer_requests": entry.data.get("mcrpc_answer_requests"),
    }


def _bridge_missing_payload(entry: ConfigEntry, *, reason: str) -> dict[str, Any]:
    """Minimal node_requests block when the bridge is absent."""
    return {
        "enabled": bool(entry.data.get("mcrpc_enabled", False)),
        "node_requests_enabled": bool(entry.data.get("mcrpc_enabled", False)),
        "bridge_missing": True,
        "setup_error": reason,
        "current_channel": entry.data.get("mcrpc_channel"),
        "pending_requests": [],
        "average_rtt_ms": None,
        "packet_loss_percent": None,
        "recent_traces": [],
        "parser_statistics": {},
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry (HA Download diagnostics / REST)."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    base: dict[str, Any] = {"entry": _entry_snapshot(entry)}

    if coordinator is None:
        base["coordinator"] = None
        base["connection"] = {"connected": False, "pubkey_prefix": None}
        base["node_requests"] = _bridge_missing_payload(
            entry, reason="coordinator_not_loaded"
        )
        return base

    api = getattr(coordinator, "api", None)
    base["connection"] = {
        "connected": bool(api and getattr(api, "connected", False)),
        "pubkey_prefix": (getattr(coordinator, "pubkey", None) or "")[:12] or None,
    }

    bridge = getattr(coordinator, "mcrpc_bridge", None)
    if bridge is not None:
        try:
            base["node_requests"] = bridge.diagnostics_dict()
        except Exception as ex:  # pragma: no cover
            base["node_requests"] = _bridge_missing_payload(entry, reason=str(ex))
            base["node_requests"]["error"] = str(ex)
    else:
        base["node_requests"] = _bridge_missing_payload(
            entry, reason="bridge_not_constructed"
        )

    return base
