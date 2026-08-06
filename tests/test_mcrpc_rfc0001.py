"""RFC-0001 Phase 3: identity-only TX validation and discovery SoT fields."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

BASE = Path("/data/projects/meshcore-ha/custom_components/meshcore")
_MCRPC_PY = Path("/data/projects/mcrpc/python")
sys.path.insert(0, str(_MCRPC_PY))

# Load registry
reg_path = BASE / "mcrpc_node_registry.py"
spec = importlib.util.spec_from_file_location(
    "custom_components.meshcore.mcrpc_node_registry", reg_path
)
reg_mod = importlib.util.module_from_spec(spec)
sys.modules["custom_components.meshcore.mcrpc_node_registry"] = reg_mod
spec.loader.exec_module(reg_mod)
NodeRegistry = reg_mod.NodeRegistry

# Minimal bridge stub for _validate_rf_target
bridge_path = BASE / "mcrpc_bridge.py"
# Avoid full bridge import (HA deps): copy validate logic via registry-backed fake


class _FakeBridge:
    _CAPABILITY_TARGETS = frozenset(
        {"gps", "battery", "relay", "display", "button", "mqtt", "wifi"}
    )
    _ROLE_LIKE_TARGETS = frozenset({"ha", "gateway", "tracker", "sensor"})

    def __init__(self, registry: NodeRegistry) -> None:
        self.registry = registry

    def _validate_rf_target(self, target: str, *, broadcast: bool = False) -> str:
        dest = (target or "").strip()
        if broadcast or dest.lower() == "all":
            return "all"
        if not dest:
            raise ValueError("target is required")
        low = dest.lower()
        if low == "self" or low.startswith("group:"):
            return dest
        if dest.startswith("@"):
            hexpart = dest[1:]
            if not hexpart or any(c not in "0123456789abcdefABCDEF" for c in hexpart):
                raise ValueError(f"invalid @id target: {dest!r}")
            return dest
        if self.registry.get(dest) is not None:
            return dest
        if low in self._CAPABILITY_TARGETS:
            raise ValueError("capability")
        if low in self._ROLE_LIKE_TARGETS:
            raise ValueError("role")
        return dest


def test_reject_capability_and_role_targets():
    reg = NodeRegistry()
    b = _FakeBridge(reg)
    with pytest.raises(ValueError):
        b._validate_rf_target("gps")
    with pytest.raises(ValueError):
        b._validate_rf_target("ha")
    assert b._validate_rf_target("node1") == "node1"
    assert b._validate_rf_target("@3CBB") == "@3CBB"
    assert b._validate_rf_target("all", broadcast=True) == "all"


def test_allow_ha_when_node_named_ha():
    reg = NodeRegistry()
    reg.ensure("ha")
    b = _FakeBridge(reg)
    assert b._validate_rf_target("ha") == "ha"


def test_discover_sot_and_tag_filter():
    import mcrpc

    line = (
        "node1 id=3CBBF74E profile=ha tag=ha fw=1.0 board=dev "
        "protocol=1.1 sdk=1.1.0 caps=battery,display,gps uptime=9"
    )
    shaped = mcrpc.parse_discover_fields(line)
    assert shaped["identity_id"] == "3CBBF74E"
    assert shaped["tag"] == "ha"
    assert "battery" in shaped["capabilities"]
    assert "gps" in shaped["capabilities"]

    reg = NodeRegistry()
    reg.apply_response(node_id="node1", command="discovery", data=shaped)
    n = reg.get("node1")
    assert n is not None
    assert n.identity_id == "3CBBF74E"
    assert n.tag == "ha"
    assert reg.nodes_with_tag("ha") == [n]
    assert reg.resolve_id_prefix("3CBB") is n
    assert reg.resolve_id_prefix("DEAD") is None
