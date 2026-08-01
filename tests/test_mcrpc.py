"""Unit tests for mcRPC bridge classification helpers (no full HA stack)."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ensure standalone mcrpc package is importable
_MCRPC_PY = Path("/data/projects/mcrpc/python")
if str(_MCRPC_PY) not in sys.path:
    sys.path.insert(0, str(_MCRPC_PY))

import mcrpc  # noqa: E402


def test_build_and_correlate_ping():
    corr = mcrpc.RequestCorrelator(default_timeout=5)
    line, pending = corr.build("tracker", "ping")
    assert line == f"tracker#{pending.request_id} ping"
    kind, resp, evt, matched = corr.classify_inbound(f"#{pending.request_id} pong")
    assert kind == "response"
    assert matched is not None
    assert resp.kind.name == "Pong"


def test_strip_group_not_sender():
    assert mcrpc.strip_sender_prefix("group:sensors ping") == "group:sensors ping"
    assert mcrpc.strip_sender_prefix("Alice: pong") == "pong"


def test_gps_and_battery_helpers():
    g = mcrpc.parse_gps("gps lat=1.5 lon=2.5 sat=7")
    assert g["latitude"] == 1.5 and g["satellites"] == 7
    b = mcrpc.parse_battery("battery value=88")
    assert b["percentage"] == 88


def test_discover_and_status_dynamic():
    d = mcrpc.parse_discover("n profile=p fw=f protocol=1.0 sdk=1.0.0 extra=1")
    assert d.parameters["extra"] == 1
    s = mcrpc.parse_status("status name=n mystery=9")
    assert s.parameters["mystery"] == 9


def test_event_line():
    e = mcrpc.parse_event("event button_pressed count=2")
    assert e.name == "button_pressed"
    assert e.parameters["count"] == 2


def test_outbound_echo_detection():
    corr = mcrpc.RequestCorrelator()
    line, _ = corr.build("tracker", "status")
    assert corr.is_outbound_echo(line)
    assert not corr.is_outbound_echo("status name=x")


def test_const_has_mcrpc_symbols():
    """Load const.py without pulling the whole integration."""
    const_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "custom_components",
        "meshcore",
        "const.py",
    )
    # const imports nothing heavy; load directly
    spec = importlib.util.spec_from_file_location("meshcore_const_mcrpc", const_path)
    mod = importlib.util.module_from_spec(spec)
    # DOMAIN Final needs typing only — execute
    sys.modules["meshcore_const_mcrpc"] = mod
    spec.loader.exec_module(mod)
    assert mod.SERVICE_SEND_MCRPC == "send_mcrpc"
    assert mod.EVENT_MCRPC_RESPONSE == "meshcore_mcrpc_response"
    assert mod.EVENT_MCRPC_EVENT == "meshcore_mcrpc_event"
    assert mod.CONF_MCRPC_ENABLED == "mcrpc_enabled"
