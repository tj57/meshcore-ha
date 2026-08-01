"""Map Node Registry entries to future Home Assistant DeviceInfo dicts.

Does NOT create devices or entities — preparation only for a later stage.
"""

from __future__ import annotations

from typing import Any

from .const import DOMAIN
from .mcrpc_node_registry import NodeRecord


class NodeDeviceMapper:
    """Reusable abstraction: NodeRecord → device registry payload."""

    def __init__(self, *, entry_id: str, hub_name: str | None = None) -> None:
        self.entry_id = entry_id
        self.hub_name = hub_name or "MeshCore"

    def device_identifier(self, node: NodeRecord) -> tuple[str, str]:
        """Stable HA device identifier tuple (domain, unique_id)."""
        return (DOMAIN, f"{self.entry_id}_mcrpc_{node.node_id}")

    def via_device_identifier(self) -> tuple[str, str]:
        """Parent hub device (the companion radio config entry)."""
        return (DOMAIN, self.entry_id)

    def to_device_info(self, node: NodeRecord) -> dict[str, Any]:
        """Return a dict shaped like HA DeviceInfo kwargs (not applied yet)."""
        name = node.display_name or node.node_id
        model = node.profile or node.board or "mesh node"
        sw = node.firmware
        return {
            "identifiers": {self.device_identifier(node)},
            "connections": set(),
            "manufacturer": "MeshCore",
            "model": model,
            "name": name,
            "sw_version": sw,
            "via_device": self.via_device_identifier(),
            # Extra metadata for a future creator — not DeviceInfo fields
            "_mcrpc": {
                "node_id": node.node_id,
                "protocol": node.protocol,
                "sdk": node.sdk,
                "capabilities": list(node.capabilities),
                "board": node.board,
                "channel": node.channel,
            },
        }

    def map_all(self, nodes: list[NodeRecord]) -> list[dict[str, Any]]:
        return [self.to_device_info(n) for n in nodes]
