"""Chat transport vs meshcore.raw — reproduce inbound answer path.

Validates that MeshCore Chat-shaped ``meshcore_message`` / ``message_sent``
events reach the answer pipeline (the gap QA missed when testing services only).
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_MCRPC_PY = Path("/data/projects/mcrpc/python")
sys.path.insert(0, str(_MCRPC_PY))

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "meshcore"

# --- package stubs -----------------------------------------------------------
_cc = types.ModuleType("custom_components")
sys.modules["custom_components"] = _cc
pkg = types.ModuleType("custom_components.meshcore")
pkg.__path__ = [str(BASE)]
sys.modules["custom_components.meshcore"] = pkg

for stub in (
    "homeassistant",
    "homeassistant.core",
    "homeassistant.util",
    "homeassistant.util.dt",
    "meshcore",
    "meshcore.events",
):
    sys.modules.setdefault(stub, MagicMock())

# @callback / Event must be real enough for decorators
_ha_core = sys.modules["homeassistant.core"]
_ha_core.callback = lambda f: f
_ha_core.HomeAssistant = MagicMock
_ha_core.Event = MagicMock

# Minimal dt_util
_dt = sys.modules["homeassistant.util.dt"]
_dt.utcnow = MagicMock(return_value=MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00+00:00")))

# EventType.ERROR must be a distinct sentinel
_ev = sys.modules["meshcore.events"]
_ev.EventType = types.SimpleNamespace(ERROR=object())

# Load const + policy + bridge pieces
spec_c = importlib.util.spec_from_file_location(
    "custom_components.meshcore.const", BASE / "const.py"
)
const = importlib.util.module_from_spec(spec_c)
sys.modules["custom_components.meshcore.const"] = const
spec_c.loader.exec_module(const)
pkg.const = const

# Stub logbook EVENT constant used by bridge
logbook_mod = types.ModuleType("custom_components.meshcore.logbook")
logbook_mod.EVENT_MESHCORE_MESSAGE = "meshcore_message"
sys.modules["custom_components.meshcore.logbook"] = logbook_mod
pkg.logbook = logbook_mod

# Stub device mapper / registry imports
for name, path in (
    ("mcrpc_node_registry", "mcrpc_node_registry.py"),
    ("mcrpc_device_mapper", "mcrpc_device_mapper.py"),
    ("mcrpc_policy", "mcrpc_policy.py"),
):
    mod_name = f"custom_components.meshcore.{name}"
    spec = importlib.util.spec_from_file_location(mod_name, BASE / path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    setattr(pkg, name, mod)

# Reload bridge after stubbing @callback as identity
spec_b = importlib.util.spec_from_file_location(
    "custom_components.meshcore.mcrpc_bridge", BASE / "mcrpc_bridge.py"
)
bridge_mod = importlib.util.module_from_spec(spec_b)
sys.modules["custom_components.meshcore.mcrpc_bridge"] = bridge_mod
# Ensure core.callback is identity before exec
sys.modules["homeassistant.core"].callback = lambda f: f
spec_b.loader.exec_module(bridge_mod)
McRpcBridge = bridge_mod.McRpcBridge
pkg.mcrpc_bridge = bridge_mod

import mcrpc  # noqa: E402


def _entry(data: dict):
    e = MagicMock()
    e.entry_id = "entry1"
    e.data = data
    e.title = data.get("name", "HA")
    return e


def _bridge(data: dict | None = None) -> McRpcBridge:
    cfg = {
        "name": "mcYogi",
        const.CONF_MCRPC_ENABLED: True,
        const.CONF_MCRPC_LISTEN_MODE: const.MCRPC_LISTEN_ALL,
        const.CONF_MCRPC_ACCEPT_BROADCAST: True,
        const.CONF_MCRPC_ACCEPT_ADDRESSED: True,
        const.CONF_MCRPC_ACCEPT_BARE: False,
        const.CONF_MCRPC_SENDER_MODE: const.MCRPC_SENDER_ANY,
        const.CONF_MCRPC_ANSWER_REQUESTS: True,
        const.CONF_MCRPC_CHANNEL: 1,
        const.CONF_MCRPC_DEBUG: True,
        **(data or {}),
    }
    hass = MagicMock()
    hass.data = {const.DOMAIN: {}}
    hass.bus.async_listen = MagicMock(return_value=MagicMock())
    tasks: list = []

    def _create_task(coro):
        # Schedule on the running pytest-asyncio loop
        t = asyncio.get_event_loop().create_task(coro)
        tasks.append(t)
        return t

    hass.async_create_task = _create_task
    hass._mcrpc_tasks = tasks
    coord = MagicMock()
    coord.name = "mcYogi"
    coord.api = MagicMock()
    coord.api.connected = True
    ok = MagicMock()
    ok.type = object()
    coord.api.mesh_core.commands.send_chan_msg = AsyncMock(return_value=ok)

    entry = _entry(cfg)
    b = McRpcBridge(hass, coord, entry)
    b._mcrpc = mcrpc
    b._correlator = mcrpc.RequestCorrelator()
    hass.data[const.DOMAIN][entry.entry_id] = coord
    b._tasks = tasks
    return b


async def _flush(b: McRpcBridge):
    if b._tasks:
        await asyncio.gather(*b._tasks, return_exceptions=True)
        b._tasks.clear()


@pytest.mark.asyncio
async def test_chat_all_ping_answers_via_meshcore_message():
    """Remote Chat shape: sender prefix stripped by logbook, body='all ping'."""
    b = _bridge()
    sent = []

    async def capture(ch, text, timestamp=None):
        sent.append((ch, text))
        return MagicMock(type=object())

    b.coordinator.api.mesh_core.commands.send_chan_msg = capture

    event = MagicMock()
    event.data = {
        "message": "all ping",
        "sender_name": "Phone",
        "channel_idx": 1,
        "message_type": "channel",
        "timestamp": "2026-01-01T00:00:00+00:00",
    }
    b._on_meshcore_message(event)
    await _flush(b)
    assert sent, f"no answer; traces={b.stats.get('recent_traces')}"
    assert sent[0][0] == 1
    assert sent[0][1] == "pong"


@pytest.mark.asyncio
async def test_chat_mcyogi_ping_addressed_to_local_name():
    b = _bridge()
    sent = []

    async def capture(ch, text, timestamp=None):
        sent.append((ch, text))
        return MagicMock(type=object())

    b.coordinator.api.mesh_core.commands.send_chan_msg = capture

    event = MagicMock()
    event.data = {
        "message": "mcYogi ping",
        "sender_name": "Phone",
        "channel_idx": 1,
        "message_type": "channel",
    }
    b._on_meshcore_message(event)
    await _flush(b)
    assert sent and sent[0][1] == "pong"


@pytest.mark.asyncio
async def test_bare_ping_denied_by_default():
    b = _bridge()
    sent = []

    async def capture(ch, text, timestamp=None):
        sent.append((ch, text))
        return MagicMock(type=object())

    b.coordinator.api.mesh_core.commands.send_chan_msg = capture
    event = MagicMock()
    event.data = {
        "message": "ping",
        "sender_name": "Phone",
        "channel_idx": 1,
        "message_type": "channel",
    }
    b._on_meshcore_message(event)
    await _flush(b)
    assert not sent
    assert any(
        d.get("reason") == "bare_disabled"
        for d in (b.stats.get("recent_denials") or [])
    )


@pytest.mark.asyncio
async def test_message_sent_fast_path_for_local_chat():
    """HA Chat / send_channel_message must answer without waiting 4s RX_LOG."""
    b = _bridge()
    sent = []

    async def capture(ch, text, timestamp=None):
        sent.append((ch, text))
        return MagicMock(type=object())

    b.coordinator.api.mesh_core.commands.send_chan_msg = capture
    event = MagicMock()
    event.data = {
        "device": "entry1",
        "message": "all discover",
        "message_type": "channel",
        "channel_idx": 1,
        "send_id": "abcd1234",
        "send_timestamp": 1710000000,
    }
    b._on_message_sent(event)
    await _flush(b)
    assert sent, b.stats.get("recent_traces")
    assert "discover" in sent[0][1]


@pytest.mark.asyncio
async def test_dedup_message_sent_and_meshcore_message():
    b = _bridge()
    sent = []

    async def capture(ch, text, timestamp=None):
        sent.append((ch, text))
        return MagicMock(type=object())

    b.coordinator.api.mesh_core.commands.send_chan_msg = capture
    sid = "deadbeef"
    b._on_message_sent(
        MagicMock(
            data={
                "device": "entry1",
                "message": "all ping",
                "message_type": "channel",
                "channel_idx": 1,
                "send_id": sid,
            }
        )
    )
    b._on_meshcore_message(
        MagicMock(
            data={
                "message": "all ping",
                "sender_name": "mcYogi",
                "channel_idx": 1,
                "outgoing": True,
                "send_id": sid,
                "message_type": "channel",
            }
        )
    )
    await _flush(b)
    assert len(sent) == 1


def test_chat_vs_raw_body_identical_after_strip():
    """Chat wire ``Name: all ping`` normalizes to the same body as meshcore.raw."""
    chat_wire = "Phone: all ping"
    raw_body = "all ping"
    assert mcrpc.strip_sender_prefix(chat_wire) == raw_body
    assert mcrpc.parse(raw_body)[0] == mcrpc.ParseResult.Ok
