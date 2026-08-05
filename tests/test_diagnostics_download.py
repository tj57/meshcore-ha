"""Diagnostics download payload must expose mcRPC fields without deleting the entry."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "meshcore"


def _load_diagnostics():
    # Stub HA modules diagnostics.py imports.
    for name in (
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.core",
    ):
        sys.modules.setdefault(name, MagicMock())

    # Provide a real package path so `from .const import DOMAIN` works.
    cc = types.ModuleType("custom_components")
    cc.__path__ = [str(ROOT / "custom_components")]
    sys.modules["custom_components"] = cc

    pkg = types.ModuleType("custom_components.meshcore")
    pkg.__path__ = [str(BASE)]
    sys.modules["custom_components.meshcore"] = pkg

    const_spec = importlib.util.spec_from_file_location(
        "custom_components.meshcore.const", BASE / "const.py"
    )
    const = importlib.util.module_from_spec(const_spec)
    sys.modules["custom_components.meshcore.const"] = const
    const_spec.loader.exec_module(const)

    diag_spec = importlib.util.spec_from_file_location(
        "custom_components.meshcore.diagnostics", BASE / "diagnostics.py"
    )
    diag = importlib.util.module_from_spec(diag_spec)
    sys.modules["custom_components.meshcore.diagnostics"] = diag
    diag_spec.loader.exec_module(diag)
    return diag


@pytest.mark.asyncio
async def test_diagnostics_without_coordinator_still_has_node_requests():
    diag = _load_diagnostics()

    class Entry:
        title = "mcCtrl"
        entry_id = "abc"
        data = {
            "connection_type": "ble",
            "name": "mcCtrl",
            "mcrpc_enabled": True,
            "mcrpc_channel": 1,
        }

    class Hass:
        data = {"meshcore": {}}

    out = await diag.async_get_config_entry_diagnostics(Hass(), Entry())
    assert out["entry"]["mcrpc_enabled"] is True
    assert "node_requests" in out
    nr = out["node_requests"]
    assert nr["enabled"] is True
    assert nr["current_channel"] == 1
    assert nr["pending_requests"] == []
    assert "recent_traces" in nr
    assert "parser_statistics" in nr


@pytest.mark.asyncio
async def test_diagnostics_from_bridge_dict_keys():
    """Bridge diagnostics_dict must expose the downloadable field set."""
    # Import bridge with heavy stubs.
    stubs = [
        "homeassistant",
        "homeassistant.core",
        "homeassistant.util",
        "homeassistant.util.dt",
        "meshcore",
        "meshcore.events",
    ]
    for name in stubs:
        sys.modules.setdefault(name, MagicMock())

    # Ensure vendor mcrpc is importable.
    vendor = str(BASE / "vendor")
    if vendor not in sys.path:
        sys.path.insert(0, vendor)

    from custom_components.meshcore import mcrpc_bridge as mb

    # Reload bridge module from file if needed
    if not hasattr(mb, "McRpcBridge"):
        spec = importlib.util.spec_from_file_location(
            "custom_components.meshcore.mcrpc_bridge", BASE / "mcrpc_bridge.py"
        )
        mb = importlib.util.module_from_spec(spec)
        sys.modules["custom_components.meshcore.mcrpc_bridge"] = mb
        spec.loader.exec_module(mb)

    hass = MagicMock()
    hass.data = {}
    coordinator = MagicMock()
    coordinator.api = MagicMock(connected=True)
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.title = "mcCtrl"
    entry.data = {
        "mcrpc_enabled": True,
        "mcrpc_channel": 1,
        "connection_type": "ble",
        "name": "mcCtrl",
    }

    bridge = mb.McRpcBridge(hass, coordinator, entry)
    # Force ready path without full async_setup when possible
    bridge._mcrpc = mb._import_mcrpc()
    d = bridge.diagnostics_dict()
    for key in (
        "current_channel",
        "recent_traces",
        "average_rtt_ms",
        "packet_loss_percent",
        "pending_requests",
        "parser_statistics",
        "tx_pipeline",
    ):
        assert key in d, key


def test_build_answer_unknown_command_not_unsupported():
    vendor = str(BASE / "vendor")
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    import mcrpc

    # Mimic bridge body builder contract
    body = mcrpc.build_error("unknown_command")
    assert body == "err unknown_command"
    assert "unsupported" not in body


def test_ha123_ping_payload_parses_without_mutation():
    """Android font issue: wire payload must remain literal ha#123 ping."""
    vendor = str(BASE / "vendor")
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    import mcrpc

    raw_tx = "ha#123 ping"
    result, req = mcrpc.parse(raw_tx)
    assert result.name == "Ok" or str(result).endswith("Ok")
    assert req.target == "ha"
    assert req.request_id == 123
    assert req.command == "ping"
    # Round-trip builder must preserve request id digits (not markdown-escaped)
    built = mcrpc.build_request("ha", "ping", request_id=123)
    assert "#123" in built
    assert built.startswith("ha")
