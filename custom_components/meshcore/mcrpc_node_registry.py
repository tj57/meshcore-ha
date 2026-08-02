"""In-memory Node Registry for mesh node requests.

Updated from discover / status / battery / events. Unknown fields are kept in
``extra``. Independent from Home Assistant entity creation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


# Default TTLs (seconds) for cached views — avoid unnecessary radio traffic.
DEFAULT_TTL_DISCOVER = 3600
DEFAULT_TTL_CAPS = 3600
DEFAULT_TTL_STATUS = 120
DEFAULT_TTL_BATTERY = 120


@dataclass
class NodeRecord:
    """One known mesh node."""

    node_id: str
    display_name: str = ""
    profile: str | None = None
    capabilities: list[str] = field(default_factory=list)
    firmware: str | None = None
    protocol: str | None = None
    sdk: str | None = None
    board: str | None = None
    battery: dict[str, Any] = field(default_factory=dict)
    last_status: dict[str, Any] = field(default_factory=dict)
    last_seen: float | None = None  # monotonic or wall — we store both
    last_seen_iso: str | None = None
    rssi: float | int | None = None
    channel: int | None = None
    discovered_at: float | None = None
    discovered_at_iso: str | None = None
    features: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    # Cache timestamps (monotonic) per kind
    cached_at: dict[str, float] = field(default_factory=dict)

    def touch(self, *, iso: str | None = None, channel: int | None = None, rssi: Any = None) -> None:
        self.last_seen = time.monotonic()
        if iso:
            self.last_seen_iso = iso
        if channel is not None:
            self.channel = channel
        if rssi is not None:
            self.rssi = rssi

    def is_fresh(self, kind: str, ttl: float) -> bool:
        ts = self.cached_at.get(kind)
        if ts is None:
            return False
        return (time.monotonic() - ts) < ttl

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.display_name or self.node_id,
            "display_name": self.display_name or self.node_id,
            "profile": self.profile,
            "capabilities": list(self.capabilities),
            "firmware": self.firmware,
            "protocol": self.protocol,
            "sdk": self.sdk,
            "board": self.board,
            "battery": dict(self.battery),
            "last_status": dict(self.last_status),
            "last_seen": self.last_seen_iso,
            "rssi": self.rssi,
            "channel": self.channel,
            "discovered": self.discovered_at_iso,
            "features": dict(self.features),
            "extra": dict(self.extra),
            "cache": {k: True for k in self.cached_at},
        }


class NodeRegistry:
    """Registry of mesh nodes discovered via channel replies."""

    def __init__(
        self,
        *,
        ttl_discover: float = DEFAULT_TTL_DISCOVER,
        ttl_caps: float = DEFAULT_TTL_CAPS,
        ttl_status: float = DEFAULT_TTL_STATUS,
        ttl_battery: float = DEFAULT_TTL_BATTERY,
    ) -> None:
        self._nodes: dict[str, NodeRecord] = {}
        self.ttl_discover = ttl_discover
        self.ttl_caps = ttl_caps
        self.ttl_status = ttl_status
        self.ttl_battery = ttl_battery

    def get(self, node_id: str) -> NodeRecord | None:
        return self._nodes.get((node_id or "").strip())

    @staticmethod
    def _canonical_kind(kind: str | None) -> str:
        cmd = (kind or "").strip().lower()
        if cmd == "discover":
            return "discovery"
        return cmd

    def ensure(self, node_id: str) -> NodeRecord:
        key = (node_id or "").strip()
        if not key:
            raise ValueError("node_id is required")
        if key not in self._nodes:
            now = time.monotonic()
            self._nodes[key] = NodeRecord(
                node_id=key,
                display_name=key,
                discovered_at=now,
            )
        return self._nodes[key]

    def all_nodes(self) -> list[NodeRecord]:
        return [self._nodes[k] for k in sorted(self._nodes)]

    def list_dicts(self) -> list[dict[str, Any]]:
        return [n.to_dict() for n in self.all_nodes()]

    def get_capabilities(self, node_id: str) -> list[str]:
        node = self.get(node_id)
        return list(node.capabilities) if node else []

    def has_capability(self, node_id: str, capability: str) -> bool:
        cap = (capability or "").strip().lower()
        return bool(cap) and cap in {c.lower() for c in self.get_capabilities(node_id)}

    def needs_refresh(self, node_id: str, kind: str) -> bool:
        """True when we should send radio traffic for this cache kind."""
        node = self.get(node_id)
        if node is None:
            return True
        cmd = self._canonical_kind(kind)
        ttl = {
            "discovery": self.ttl_discover,
            "discover": self.ttl_discover,
            "caps": self.ttl_caps,
            "status": self.ttl_status,
            "battery": self.ttl_battery,
        }.get(cmd, 0)
        if ttl <= 0:
            return True
        fresh_key = "discover" if cmd == "discovery" else cmd
        return not node.is_fresh(fresh_key, ttl)

    def apply_response(
        self,
        *,
        node_id: str | None,
        command: str | None,
        data: dict[str, Any],
        channel: int | None = None,
        rssi: Any = None,
        timestamp_iso: str | None = None,
    ) -> NodeRecord | None:
        """Update registry from a shaped response payload."""
        name = (node_id or data.get("device") or data.get("name") or "").strip()
        if not name:
            return None
        node = self.ensure(name)
        if not node.discovered_at_iso and timestamp_iso:
            node.discovered_at_iso = timestamp_iso
        node.touch(iso=timestamp_iso, channel=channel, rssi=rssi)
        cmd = self._canonical_kind(command)

        # Merge arbitrary extras
        extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
        for k, v in extra.items():
            node.extra[k] = v

        if cmd == "discovery" or data.get("profile") is not None or data.get("device"):
            if data.get("device"):
                node.display_name = str(data["device"])
            if data.get("profile") is not None:
                node.profile = data.get("profile")
            if data.get("firmware") is not None:
                node.firmware = data.get("firmware")
            if data.get("protocol") is not None:
                node.protocol = data.get("protocol")
            if data.get("sdk") is not None:
                node.sdk = data.get("sdk")
            if data.get("board") is not None:
                node.board = data.get("board")
            if isinstance(data.get("features"), dict):
                node.features.update(data["features"])
            caps = list(data.get("capabilities") or [])
            for feat, val in node.features.items():
                if str(val).lower() in {"yes", "1", "true"} and feat not in caps:
                    caps.append(feat)
            if caps:
                # union with existing
                merged = list(dict.fromkeys([*node.capabilities, *caps]))
                node.capabilities = merged
            # Keep the historic "discover" cache key for compatibility with
            # existing diagnostics/tests while internally using discovery.
            node.cached_at["discovery"] = time.monotonic()
            node.cached_at["discover"] = time.monotonic()

        if cmd == "caps" and data.get("capabilities"):
            merged = list(dict.fromkeys([*node.capabilities, *list(data["capabilities"])]))
            node.capabilities = merged
            node.cached_at["caps"] = time.monotonic()

        if cmd == "status" or data.get("uptime") is not None or data.get("rssi") is not None:
            status = {
                k: v
                for k, v in data.items()
                if k not in {"extra", "parameters", "fields"}
            }
            node.last_status = {**node.last_status, **status}
            if data.get("rssi") is not None:
                node.rssi = data.get("rssi")
            if data.get("name"):
                node.display_name = str(data["name"])
            if data.get("profile"):
                node.profile = data.get("profile")
            if data.get("firmware"):
                node.firmware = data.get("firmware")
            if data.get("battery") is not None:
                node.battery["percentage"] = data.get("battery")
            if data.get("voltage") is not None:
                node.battery["voltage"] = data.get("voltage")
            node.cached_at["status"] = time.monotonic()

        if cmd in {"battery", "voltage", "charging"} or data.get("percentage") is not None:
            batt = {
                k: data.get(k)
                for k in (
                    "percentage",
                    "battery",
                    "voltage",
                    "charging",
                    "temperature",
                    "health",
                    "cycles",
                )
                if data.get(k) is not None
            }
            if isinstance(data.get("extra"), dict):
                batt["extra"] = dict(data["extra"])
            node.battery = {**node.battery, **batt}
            node.cached_at["battery"] = time.monotonic()

        return node

    def apply_event(
        self,
        *,
        node_id: str | None,
        event_name: str | None,
        parameters: dict[str, Any],
        channel: int | None = None,
        timestamp_iso: str | None = None,
    ) -> NodeRecord | None:
        if not node_id:
            return None
        node = self.ensure(node_id)
        node.touch(iso=timestamp_iso, channel=channel)
        if event_name:
            node.extra["last_event"] = event_name
            node.extra["last_event_params"] = dict(parameters or {})
        return node

    # Compat views used by older bridge helpers
    def discover_cache_view(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for n in self.all_nodes():
            if "discover" not in n.cached_at and "discovery" not in n.cached_at and not n.profile:
                continue
            out[n.node_id] = {
                "device": n.display_name or n.node_id,
                "profile": n.profile,
                "board": n.board,
                "firmware": n.firmware,
                "protocol": n.protocol,
                "sdk": n.sdk,
                "features": dict(n.features),
                "capabilities": list(n.capabilities),
                "extra": dict(n.extra),
                "updated": n.last_seen_iso,
            }
        return out

    def capability_cache_view(self) -> dict[str, list[str]]:
        return {n.node_id: list(n.capabilities) for n in self.all_nodes() if n.capabilities}

    def snapshot(self) -> dict[str, Any]:
        return {"nodes": self.list_dicts(), "count": len(self._nodes)}
