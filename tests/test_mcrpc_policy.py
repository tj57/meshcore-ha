"""Unit tests for Mesh Node Requests policy, migration, and channel labels."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "meshcore"

# Minimal package stubs
pkg = types.ModuleType("custom_components.meshcore")
sys.modules["custom_components"] = types.ModuleType("custom_components")
sys.modules["custom_components.meshcore"] = pkg

const_path = BASE / "const.py"
spec_c = importlib.util.spec_from_file_location("custom_components.meshcore.const", const_path)
const = importlib.util.module_from_spec(spec_c)
sys.modules["custom_components.meshcore.const"] = const
spec_c.loader.exec_module(const)
pkg.const = const

policy_path = BASE / "mcrpc_policy.py"
spec_p = importlib.util.spec_from_file_location(
    "custom_components.meshcore.mcrpc_policy", policy_path
)
policy_mod = importlib.util.module_from_spec(spec_p)
sys.modules["custom_components.meshcore.mcrpc_policy"] = policy_mod
spec_p.loader.exec_module(policy_mod)

McRpcPolicy = policy_mod.McRpcPolicy


class _Req:
    def __init__(self, kind: str, target: str = "", command: str = "ping"):
        self.address_kind = types.SimpleNamespace(name=kind)
        self.target = target
        self.command = command
        self.has_request_id = False
        self.request_id = 0


def _policy(data: dict, entry_id: str = "e1") -> McRpcPolicy:
    return McRpcPolicy(data, entry_id=entry_id)


def test_secure_defaults_for_new_install():
    data = const.migrate_mcrpc_config({"name": "HomeHA", "mcrpc_enabled": False})
    assert data[const.CONF_MCRPC_LISTEN_MODE] == const.MCRPC_LISTEN_SELECTED
    assert data[const.CONF_MCRPC_LISTEN_CHANNELS] == [const.DEFAULT_MCRPC_CHANNEL]
    assert const.DEFAULT_MCRPC_CHANNEL == 1  # mcCtrl, never Public
    assert data[const.CONF_MCRPC_ACCEPT_BARE] is False
    assert data[const.CONF_MCRPC_ACCEPT_BROADCAST] is True
    assert data[const.CONF_MCRPC_ACCEPT_ADDRESSED] is True


def test_migrate_enabled_preserves_old_channel_including_public():
    data = const.migrate_mcrpc_config(
        {"name": "HomeHA", "mcrpc_enabled": True, "mcrpc_channel": 0}
    )
    assert data[const.CONF_MCRPC_LISTEN_MODE] == const.MCRPC_LISTEN_SELECTED
    assert data[const.CONF_MCRPC_LISTEN_CHANNELS] == [0]
    assert data[const.CONF_MCRPC_ACCEPT_BARE] is True  # prior behaviour


def test_public_channel_denied_by_default_secure_policy():
    data = const.migrate_mcrpc_config({"name": "ha", "mcrpc_enabled": True})
    # Force secure listen without public
    data[const.CONF_MCRPC_LISTEN_CHANNELS] = [1]
    data[const.CONF_MCRPC_ACCEPT_BARE] = False
    pol = _policy(data)
    d = pol.decide_inbound_request(
        channel_idx=0,
        sender_name="nodeA",
        req=_Req("Named", "ha"),
        parse_ok=True,
    )
    assert d.allow is False
    assert d.reason == "channel_not_listening"


def test_private_channel_addressed_allowed():
    data = {
        "name": "ha",
        const.CONF_MCRPC_LISTEN_MODE: const.MCRPC_LISTEN_SELECTED,
        const.CONF_MCRPC_LISTEN_CHANNELS: [1],
        const.CONF_MCRPC_ACCEPT_BROADCAST: True,
        const.CONF_MCRPC_ACCEPT_ADDRESSED: True,
        const.CONF_MCRPC_ACCEPT_BARE: False,
        const.CONF_MCRPC_SENDER_MODE: const.MCRPC_SENDER_ANY,
    }
    pol = _policy(data)
    d = pol.decide_inbound_request(
        channel_idx=1,
        sender_name="nodeA",
        req=_Req("Named", "ha"),
        parse_ok=True,
    )
    assert d.allow is True
    assert d.addressing == "addressed"


def test_broadcast_accepted_when_enabled():
    data = {
        "name": "ha",
        const.CONF_MCRPC_LISTEN_MODE: const.MCRPC_LISTEN_ALL,
        const.CONF_MCRPC_ACCEPT_BROADCAST: True,
        const.CONF_MCRPC_ACCEPT_ADDRESSED: True,
        const.CONF_MCRPC_ACCEPT_BARE: False,
        const.CONF_MCRPC_SENDER_MODE: const.MCRPC_SENDER_ANY,
    }
    pol = _policy(data)
    d = pol.decide_inbound_request(
        channel_idx=2,
        sender_name="nodeA",
        req=_Req("All", "all"),
        parse_ok=True,
    )
    assert d.allow is True
    assert d.addressing == "broadcast"


def test_bare_denied_by_default():
    data = {
        "name": "ha",
        const.CONF_MCRPC_LISTEN_MODE: const.MCRPC_LISTEN_ALL,
        const.CONF_MCRPC_ACCEPT_BROADCAST: True,
        const.CONF_MCRPC_ACCEPT_ADDRESSED: True,
        const.CONF_MCRPC_ACCEPT_BARE: False,
        const.CONF_MCRPC_SENDER_MODE: const.MCRPC_SENDER_ANY,
    }
    pol = _policy(data)
    d = pol.decide_inbound_request(
        channel_idx=1,
        sender_name="nodeA",
        req=_Req("Named", "", "ping"),
        parse_ok=False,
    )
    assert d.allow is False
    assert d.reason == "bare_disabled"


def test_allow_list_sender():
    data = {
        "name": "ha",
        const.CONF_MCRPC_LISTEN_MODE: const.MCRPC_LISTEN_ALL,
        const.CONF_MCRPC_ACCEPT_BROADCAST: True,
        const.CONF_MCRPC_ACCEPT_ADDRESSED: True,
        const.CONF_MCRPC_ACCEPT_BARE: False,
        const.CONF_MCRPC_SENDER_MODE: const.MCRPC_SENDER_ALLOWLIST,
        const.CONF_MCRPC_ALLOW_LIST: ["trusted", "abc123"],
    }
    pol = _policy(data)
    ok = pol.decide_inbound_request(
        channel_idx=1,
        sender_name="Trusted",
        req=_Req("Named", "ha"),
        parse_ok=True,
    )
    bad = pol.decide_inbound_request(
        channel_idx=1,
        sender_name="stranger",
        req=_Req("Named", "ha"),
        parse_ok=True,
    )
    assert ok.allow is True
    assert bad.allow is False
    assert bad.reason == "sender_denied"


def test_wrong_channel_selected():
    data = {
        "name": "ha",
        const.CONF_MCRPC_LISTEN_MODE: const.MCRPC_LISTEN_SELECTED,
        const.CONF_MCRPC_LISTEN_CHANNELS: [3],
        const.CONF_MCRPC_ACCEPT_ADDRESSED: True,
        const.CONF_MCRPC_SENDER_MODE: const.MCRPC_SENDER_ANY,
    }
    pol = _policy(data)
    d = pol.decide_inbound_request(
        channel_idx=1,
        sender_name="nodeA",
        req=_Req("Named", "ha"),
        parse_ok=True,
    )
    assert d.allow is False
    assert d.reason == "channel_not_listening"


def test_not_addressed_to_us():
    data = {
        "name": "HomeHA",
        const.CONF_MCRPC_LISTEN_MODE: const.MCRPC_LISTEN_ALL,
        const.CONF_MCRPC_ACCEPT_ADDRESSED: True,
        const.CONF_MCRPC_SENDER_MODE: const.MCRPC_SENDER_ANY,
    }
    pol = _policy(data)
    d = pol.decide_inbound_request(
        channel_idx=1,
        sender_name="nodeA",
        req=_Req("Named", "othernode"),
        parse_ok=True,
    )
    assert d.allow is False
    assert d.reason == "not_addressed_to_us"


def test_reply_identity_self_and_other():
    data = {
        "name": "ha",
        const.CONF_MCRPC_REPLY_IDENTITY: "other",
        const.CONF_MCRPC_LISTEN_MODE: const.MCRPC_LISTEN_DISABLED,
    }
    pol = _policy(data, entry_id="self")
    domain = {"self": MagicMock(api=object()), "other": MagicMock(api=object())}
    assert pol.resolve_reply_entry_id(domain) == "other"
    assert pol.resolve_reply_entry_id({"self": MagicMock(api=object())}) == "self"


def test_channel_label_helper():
    # Inline the same formatting used by config_flow
    def label(idx, name):
        n = (name or "").strip()
        if not n or n == "(unused)":
            n = "Public" if idx == 0 else f"{idx}"
        if idx == 0 and n.lower() == "public":
            n = "Public"
        return f"Channel {idx} ({n})"

    assert label(0, None) == "Channel 0 (Public)"
    assert label(1, "mcCtrl") == "Channel 1 (mcCtrl)"
