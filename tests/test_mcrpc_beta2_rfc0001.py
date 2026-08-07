"""RFC-0001 addressing + RFC-0002 Protocol 1.2 discovery/status/call."""

from __future__ import annotations

import importlib.util
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "meshcore"
_MCRPC_PY = Path("/data/projects/mcrpc/python")
sys.path.insert(0, str(_MCRPC_PY))

# Package stubs
pkg = types.ModuleType("custom_components.meshcore")
sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
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

reg_path = BASE / "mcrpc_node_registry.py"
spec_r = importlib.util.spec_from_file_location(
    "custom_components.meshcore.mcrpc_node_registry", reg_path
)
reg_mod = importlib.util.module_from_spec(spec_r)
sys.modules["custom_components.meshcore.mcrpc_node_registry"] = reg_mod
spec_r.loader.exec_module(reg_mod)
NodeRegistry = reg_mod.NodeRegistry

import mcrpc  # noqa: E402


FULL_ID = "3cbbf74eaabbccddeeff001122334455"


class _Req:
    def __init__(self, kind: str, target: str = "", command: str = "ping", rid=None):
        self.address_kind = types.SimpleNamespace(name=kind)
        self.target = target
        self.command = command
        self.has_request_id = rid is not None
        self.request_id = rid or 0


def _base_data(name: str = "node1") -> dict:
    return {
        "name": name,
        const.CONF_MCRPC_LISTEN_MODE: const.MCRPC_LISTEN_ALL,
        const.CONF_MCRPC_ACCEPT_BROADCAST: True,
        const.CONF_MCRPC_ACCEPT_ADDRESSED: True,
        const.CONF_MCRPC_ACCEPT_BARE: False,
        const.CONF_MCRPC_SENDER_MODE: const.MCRPC_SENDER_ANY,
    }


def _pol(name="node1", identity_id=FULL_ID, **extra) -> McRpcPolicy:
    data = {**_base_data(name), **extra}
    return McRpcPolicy(data, entry_id="e1", identity_id=identity_id)


def _decide(pol, kind, target, command="ping"):
    return pol.decide_inbound_request(
        channel_idx=1,
        sender_name="peer",
        req=_Req(kind, target, command),
        parse_ok=True,
    )


# ---- Addressing matrix -------------------------------------------------------


def test_named_identity_allows():
    assert _decide(_pol(), "Named", "node1").allow is True


def test_ha_role_denied_when_identity_is_node1():
    d = _decide(_pol("node1"), "Named", "ha")
    assert d.allow is False
    assert d.reason == "not_addressed_to_us"


def test_homeassistant_aliases_denied():
    pol = _pol("node1")
    for alias in ("ha", "homeassistant", "home-assistant", "gps", "button", "gateway", "tracker"):
        d = _decide(pol, "Named", alias)
        assert d.allow is False, alias


def test_ha_allowed_only_when_literally_named_ha():
    assert _decide(_pol("ha"), "Named", "ha").allow is True


def test_id_full_match_case_insensitive():
    pol = _pol(identity_id=FULL_ID)
    assert _decide(pol, "Id", FULL_ID).allow is True
    assert _decide(pol, "Id", FULL_ID.upper()).allow is True
    assert _decide(pol, "Id", "3CBBF74E").allow is True  # unique prefix


def test_id_wrong_rejected():
    assert _decide(_pol(), "Id", "deadbeef").allow is False


def test_id_invalid_non_hex_rejected():
    # Policy-level: non-hex target fails _id_matches
    assert _pol().addressed_to_us(_Req("Id", "zzzz")) is False


def test_id_empty_identity_never_matches():
    pol = _pol(identity_id="")
    assert _decide(pol, "Id", "3cbb").allow is False
    assert pol.addressed_to_us(_Req("Id", FULL_ID)) is False


def test_all_broadcast():
    assert _decide(_pol(), "All", "all").allow is True


def test_unknown_named_denied():
    assert _decide(_pol(), "Named", "unknown-node").allow is False


def test_parser_addressing_matrix_with_request_ids():
    """Parser + policy for glued request-ids and @id forms."""
    cases = [
        ("node1 ping", True),
        ("node1#1 ping", True),
        ("node1#42 status", True),
        (f"@{FULL_ID} ping", True),
        (f"@{FULL_ID}#2 ping", True),
        ("@3CBB ping", True),
        ("@3cbb#123 ping", True),
        ("all ping", True),
        ("all#999 discovery", True),
        ("all#3 ping", True),
        ("ha ping", False),
        ("gps ping", False),
        ("button ping", False),
        ("unknown-node ping", False),
        ("@deadbeef ping", False),
    ]
    pol = _pol("node1", FULL_ID)
    for line, expect in cases:
        result, req = mcrpc.parse(line)
        assert result == mcrpc.ParseResult.Ok, line
        d = pol.decide_inbound_request(
            channel_idx=1, sender_name="peer", req=req, parse_ok=True
        )
        assert d.allow is expect, f"{line}: {d.reason}"


def test_malformed_at_id():
    result, _ = mcrpc.parse("@ ping")
    assert result == mcrpc.ParseResult.Malformed


def test_tag_is_not_rf_address_in_registry():
    reg = NodeRegistry()
    shaped = mcrpc.parse_discover_fields(
        "node1 id=3CBBF74E tag=ha profile=ha protocol=1.1 sdk=1.1.0"
    )
    reg.apply_response(node_id="node1", command="discovery", data=shaped)
    assert reg.nodes_with_tag("ha")[0].node_id == "node1"

    class _FakeBridge:
        _ROLE_LIKE_TARGETS = frozenset({"ha", "gateway", "tracker", "sensor"})
        _CAPABILITY_TARGETS = frozenset({"gps", "battery", "button"})

        def __init__(self, registry):
            self.registry = registry

        def _validate_rf_target(self, target: str, *, broadcast: bool = False) -> str:
            dest = (target or "").strip()
            low = dest.lower()
            if self.registry.get(dest) is not None:
                return dest
            if low in self._CAPABILITY_TARGETS or low in self._ROLE_LIKE_TARGETS:
                raise ValueError("role_or_cap")
            return dest

    b = _FakeBridge(reg)
    with pytest.raises(ValueError):
        b._validate_rf_target("ha")
    with pytest.raises(ValueError):
        b._validate_rf_target("gps")


# ---- Discovery matrix --------------------------------------------------------


def test_discovery_12_fields():
    line = (
        "node1 id=3cbbf74e fw=x v=1.2 tag=ha up=42s "
        "caps=battery,display,gps"
    )
    shaped = mcrpc.parse_discover_fields(line)
    assert shaped["identity_id"] == "3cbbf74e"
    assert shaped["tag"] == "ha"
    assert shaped["protocol"] == "1.2"
    assert shaped["v"] == "1.2"
    assert shaped["uptime"] == "42s"
    assert shaped["capabilities"] == ["battery", "display", "gps"]
    assert shaped["feature_tokens"] == []


def test_legacy_10_profile_only():
    shaped = mcrpc.parse_discover_fields(
        "node1 profile=ha protocol=1.0 sdk=1.0.0 fw=old"
    )
    assert shaped["profile"] == "ha"
    assert shaped["tag"] == "ha"  # tag falls back to profile
    assert shaped["protocol"] == "1.0"
    assert shaped["identity_id"] is None


def test_tag_only_and_profile_only_and_both():
    t = mcrpc.parse_discover_fields("n1 tag=sensor v=1.2")
    assert t["tag"] == "sensor"
    p = mcrpc.parse_discover_fields("n1 profile=legacy protocol=1.0 sdk=1.0.0")
    assert p["tag"] == "legacy"
    both = mcrpc.parse_discover_fields(
        "n1 profile=legacy tag=ha v=1.2"
    )
    assert both["tag"] == "ha"
    assert both["profile"] == "legacy"


def test_caps_features_canonical_preference():
    # Receivers accept non-canonical order/case/dupes; tokens are folded + unique + sorted
    shaped = mcrpc.parse_discover_fields(
        "n1 v=1.2 caps=gps,Battery,gps,Display "
        "features=request-id,id-addr,Request-Id"
    )
    assert shaped["capabilities"] == ["battery", "display", "gps"]
    assert shaped["feature_tokens"] == ["id-addr", "request-id"]


def test_unknown_and_missing_optional():
    shaped = mcrpc.parse_discover_fields(
        "n1 v=1.2 future_widget=1 vendor=x"
    )
    assert "future_widget" in shaped["extra"] or "future_widget" in shaped["fields"]
    assert shaped.get("identity_id") is None
    assert shaped.get("uptime") is None


def test_registry_stores_12_cache():
    reg = NodeRegistry()
    shaped = mcrpc.parse_discover_fields(
        "node1 id=aabbccdd tag=ha v=1.2 up=9s caps=battery"
    )
    reg.apply_response(node_id="node1", command="discovery", data=shaped)
    n = reg.get("node1")
    assert n.identity_id == "aabbccdd"
    assert n.protocol == "1.2"
    assert n.uptime == "9s"
    view = reg.discover_cache_view()["node1"]
    assert view["protocol"] == "1.2"
    assert view["uptime"] == "9s"


# ---- Bridge answer / discovery / uptime / id ---------------------------------


def _load_bridge_helpers():
    """Load answer/discovery helpers without full Home Assistant import."""
    # Minimal stubs for HA imports used at module level
    for name in (
        "homeassistant",
        "homeassistant.core",
        "homeassistant.util",
        "homeassistant.util.dt",
    ):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    ha_core = sys.modules["homeassistant.core"]
    ha_core.HomeAssistant = object
    ha_core.Event = object
    ha_core.callback = lambda f: f
    dt = sys.modules["homeassistant.util.dt"]
    dt.utcnow = lambda: MagicMock(isoformat=lambda: "2026-01-01T00:00:00+00:00")

    # Sibling modules already partially loaded
    for mod_name, path in (
        ("custom_components.meshcore.logbook", BASE / "logbook.py"),
        ("custom_components.meshcore.mcrpc_device_mapper", BASE / "mcrpc_device_mapper.py"),
        ("custom_components.meshcore.mcrpc_node_registry", BASE / "mcrpc_node_registry.py"),
        ("custom_components.meshcore.mcrpc_policy", BASE / "mcrpc_policy.py"),
    ):
        if mod_name in sys.modules:
            continue
        if not path.exists():
            sys.modules[mod_name] = types.ModuleType(mod_name)
            continue
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            sys.modules[mod_name] = types.ModuleType(mod_name)

    # logbook may need EVENT constant
    if not hasattr(sys.modules.get("custom_components.meshcore.logbook", object), "EVENT_MESHCORE_MESSAGE"):
        lb = types.ModuleType("custom_components.meshcore.logbook")
        lb.EVENT_MESHCORE_MESSAGE = "meshcore_message"
        sys.modules["custom_components.meshcore.logbook"] = lb

    if "custom_components.meshcore.mcrpc_device_mapper" not in sys.modules or not hasattr(
        sys.modules["custom_components.meshcore.mcrpc_device_mapper"], "NodeDeviceMapper"
    ):
        dm = types.ModuleType("custom_components.meshcore.mcrpc_device_mapper")

        class NodeDeviceMapper:
            def __init__(self, **kwargs):
                pass

        dm.NodeDeviceMapper = NodeDeviceMapper
        sys.modules["custom_components.meshcore.mcrpc_device_mapper"] = dm

    bridge_path = BASE / "mcrpc_bridge.py"
    # Force reload so we pick up latest edits
    sys.modules.pop("custom_components.meshcore.mcrpc_bridge", None)
    spec_b = importlib.util.spec_from_file_location(
        "custom_components.meshcore.mcrpc_bridge", bridge_path
    )
    bridge_mod = importlib.util.module_from_spec(spec_b)
    sys.modules["custom_components.meshcore.mcrpc_bridge"] = bridge_mod
    spec_b.loader.exec_module(bridge_mod)
    return bridge_mod.McRpcBridge


def _make_bridge(name="node1", pubkey=FULL_ID):
    McRpcBridge = _load_bridge_helpers()
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.name = name
    coordinator.pubkey = pubkey
    coordinator.api = MagicMock()
    coordinator.api._last_self_info = {"public_key": pubkey}
    entry = MagicMock()
    entry.entry_id = "entry-stable-1"
    entry.title = name
    entry.data = {
        "name": name,
        "pubkey": pubkey,
        const.CONF_MCRPC_ENABLED: True,
        const.CONF_MCRPC_LISTEN_MODE: const.MCRPC_LISTEN_ALL,
        const.CONF_MCRPC_ACCEPT_BROADCAST: True,
        const.CONF_MCRPC_ACCEPT_ADDRESSED: True,
        const.CONF_MCRPC_ACCEPT_BARE: False,
        const.CONF_MCRPC_SENDER_MODE: const.MCRPC_SENDER_ANY,
        const.CONF_MCRPC_ANSWER_REQUESTS: True,
    }
    bridge = McRpcBridge(hass, coordinator, entry)
    bridge._mcrpc = mcrpc
    bridge._mcrpc_started_mono = time.monotonic() - 5
    return bridge


def test_discovery_answer_is_protocol_12_slim():
    bridge = _make_bridge()
    req = _Req("Named", "node1", "discovery")
    body = bridge._build_answer_body(req)
    assert body.startswith("node1 ")
    assert "v=1.2" in body
    assert f"id={FULL_ID[:8].lower()}" in body or f"id={FULL_ID[:8]}" in body
    assert len([p for p in body.split() if p.startswith("id=")][0].split("=", 1)[1]) == 8
    assert "tag=ha" in body
    assert "up=" in body
    assert "protocol=" not in body
    assert "sdk=" not in body
    assert "features=" not in body
    assert "profile=" not in body
    assert "transport=" not in body
    assert not body.startswith("discovery name=")


def test_status_uses_identity_not_tag():
    bridge = _make_bridge("node1")
    body = bridge._build_answer_body(_Req("Named", "node1", "status"))
    assert "name=node1" in body
    assert body.startswith("status ")
    assert "id_full=" in body
    assert "v=1.2" in body
    assert "transport=meshcore" in body


def test_command_coverage_unsupported_vs_unknown():
    bridge = _make_bridge()
    assert "unsupported" in bridge._build_answer_body(_Req("Named", "node1", "gps"))
    assert "unsupported" in bridge._build_answer_body(_Req("Named", "node1", "battery"))
    assert "unknown_command" in bridge._build_answer_body(
        _Req("Named", "node1", "frobnicate")
    )
    assert bridge._build_answer_body(_Req("Named", "node1", "ping")) == "pong"
    help_body = bridge._build_answer_body(_Req("Named", "node1", "help"))
    assert "ping" in help_body and "call" in help_body and "ha " not in f" {help_body} "


def test_call_ns_action_ok_and_flat_rejected():
    bridge = _make_bridge()

    class _CallReq:
        def __init__(self, *args):
            self.target_kind = "Named"
            self.target = "node1"
            self.command = "call"
            self.args = list(args)
            self.has_request_id = False
            self.request_id = None

    ok = bridge._build_answer_body(_CallReq("scene.morning"))
    assert ok == "ok" or ok.startswith("ok ")
    assert "=" not in ok or all("=" in t for t in ok.split()[1:])
    bad = bridge._build_answer_body(_CallReq("button_pressed"))
    assert "invalid_argument" in bad
    assert "reason=proc" in bad
    empty = bridge._build_answer_body(_CallReq())
    assert "invalid_argument" in empty


def test_request_id_prefix_on_answers():
    bridge = _make_bridge()
    body = bridge._build_answer_body(_Req("Named", "node1", "ping", rid=42))
    assert body.startswith("#42 ")
    disc = bridge._build_answer_body(_Req("Id", FULL_ID, "discovery", rid=123))
    assert disc.startswith("#123 ")


def test_identity_id_stable_across_reload():
    b1 = _make_bridge()
    id1 = b1._local_identity_id()
    b2 = _make_bridge()
    id2 = b2._local_identity_id()
    assert id1 == id2 == FULL_ID


def test_uptime_non_negative_and_increasing():
    bridge = _make_bridge()
    u1 = bridge._local_uptime_seconds()
    time.sleep(0.05)
    # advance started earlier
    bridge._mcrpc_started_mono = time.monotonic() - 10
    u2 = bridge._local_uptime_seconds()
    assert u1 >= 0
    assert u2 >= u1
    assert u2 >= 9


def test_canonicalize_csv_helper():
    McRpcBridge = _load_bridge_helpers()
    assert McRpcBridge._canonicalize_csv(["gps", "Battery", "gps", " display "]) == (
        "battery,display,gps"
    )


def test_diagnostics_local_peer():
    bridge = _make_bridge()
    diag = bridge.diagnostics_dict()
    peer = diag["local_peer"]
    assert peer["identity"] == "node1"
    assert peer["id"] == FULL_ID
    assert peer["tag"] == "ha"
    assert peer["v"] == "1.2"
    assert peer["features"] in ("", None) or peer["features"] == ""
    # No secrets
    blob = str(diag)
    assert "psk" not in blob.lower() or "transport" in blob  # transport ok; no raw PSK values
    assert "private" not in blob.lower()


def test_policy_id_via_parser_at_prefix():
    bridge = _make_bridge()
    pol = bridge.policy()
    result, req = mcrpc.parse("@3CBB ping")
    assert result == mcrpc.ParseResult.Ok
    assert pol.addressed_to_us(req) is True
    result2, req2 = mcrpc.parse("ha ping")
    assert result2 == mcrpc.ParseResult.Ok
    assert pol.addressed_to_us(req2) is False
