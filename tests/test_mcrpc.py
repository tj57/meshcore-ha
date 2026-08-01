"""Unit tests for mesh node-request helpers (no full HA stack)."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_MCRPC_PY = Path("/data/projects/mcrpc/python")
if str(_MCRPC_PY) not in sys.path:
    sys.path.insert(0, str(_MCRPC_PY))

import mcrpc  # noqa: E402


def test_gps_extended_fields_and_extra():
    g = mcrpc.parse_gps(
        "gps lat=1.5 lon=2.5 alt=10 speed=3 heading=90 hdop=1.1 vdop=1.2 "
        "sat=8 fix=fix time=123 provider=gnss mystery=9"
    )
    assert g["latitude"] == 1.5
    assert g["longitude"] == 2.5
    assert g["altitude"] == 10
    assert g["speed"] == 3
    assert g["heading"] == 90
    assert g["hdop"] == 1.1
    assert g["vdop"] == 1.2
    assert g["satellites"] == 8
    assert g["fix"] == "fix"
    assert g["time"] == 123
    assert g["provider"] == "gnss"
    assert g["extra"]["mystery"] == 9


def test_battery_cycles_and_extra():
    b = mcrpc.parse_battery("battery value=88 voltage=3.9 cycles=12 custom=1")
    assert b["percentage"] == 88
    assert b["battery"] == 88
    assert b["voltage"] == 3.9
    assert b["cycles"] == 12
    assert b["extra"]["custom"] == 1


def test_status_preserves_unknown():
    s = mcrpc.parse_status_fields("status name=n mystery=9 uptime=3")
    assert s["name"] == "n"
    assert s["uptime"] == 3
    assert s["extra"]["mystery"] == 9


def test_const_public_api():
    const_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "custom_components",
        "meshcore",
        "const.py",
    )
    spec = importlib.util.spec_from_file_location("meshcore_const_api", const_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["meshcore_const_api"] = mod
    spec.loader.exec_module(mod)
    assert mod.SERVICE_REQUEST == "request"
    assert mod.SERVICE_BROADCAST == "broadcast"
    assert mod.SERVICE_RAW == "raw"
    assert mod.SERVICE_HAS_CAPABILITY == "has_capability"
    assert mod.EVENT_NODE_RESPONSE == "meshcore_response"
    assert mod.EVENT_NODE_EVENT == "meshcore_event"
    assert mod.ATTR_ARGS == "args"
    assert mod.ATTR_CHANNEL == "channel"


def test_capability_style_discover():
    d = mcrpc.parse_discover_fields(
        "tracker profile=tracker fw=1 gps=yes battery=yes weird=2"
    )
    assert "gps" in d["capabilities"]
    assert d["extra"]["weird"] == 2 or d["extra"].get("weird") == 2
