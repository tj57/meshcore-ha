"""Discover builder and discover-line parser."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .codec import coerce_number, format_kv, parse_kv_pairs, split_tokens
from .version import PROTOCOL_VERSION, SDK_VERSION


@dataclass
class ParsedDiscover:
    raw: str
    device: str = ""
    profile: str | None = None
    board: str | None = None
    firmware: str | None = None
    protocol: str | None = None
    sdk: str | None = None
    features: dict[str, str] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    request_id: int | None = None


class DiscoverBuilder:
    """Assembles ``<name> key=value …`` (mirror DiscoverBuilder.h)."""

    def __init__(self) -> None:
        self._name = ""
        self._fields: list[tuple[str, str]] = []

    def reset(self) -> None:
        self._name = ""
        self._fields.clear()

    def set_node_name(self, name: str | None) -> None:
        self._name = name or ""

    def add(self, key: str, value: Any) -> bool:
        if not key or value is None:
            return False
        self._fields.append((key, str(value)))
        return True

    def add_versions(self) -> None:
        self.add("protocol", PROTOCOL_VERSION)
        self.add("sdk", SDK_VERSION)

    def write(self) -> str:
        name = self._name or "node"
        if not self._fields:
            return name
        return f"{name} " + format_kv(dict(self._fields))


def parse_discover(raw: str | None) -> ParsedDiscover:
    """Parse a discover reply; unknown fields remain available."""
    text = (raw or "").strip()
    tokens = split_tokens(text)
    rid = None
    if tokens and tokens[0].startswith("#") and tokens[0][1:].isdigit():
        rid = int(tokens[0][1:])
        tokens = tokens[1:]
    if not tokens:
        return ParsedDiscover(raw=text, request_id=rid)

    device = tokens[0]
    fields = parse_kv_pairs(tokens[1:])
    params = {k: coerce_number(v) for k, v in fields.items()}

    # Feature flags often appear as gps=yes / battery=yes
    features = {
        k: v
        for k, v in fields.items()
        if k not in {"profile", "fw", "board", "protocol", "sdk", "name"}
    }
    caps = [k for k, v in features.items() if str(v).lower() in {"yes", "1", "true"}]

    return ParsedDiscover(
        raw=text,
        device=device,
        profile=fields.get("profile"),
        board=fields.get("board"),
        firmware=fields.get("fw") or fields.get("firmware"),
        protocol=fields.get("protocol"),
        sdk=fields.get("sdk"),
        features=features,
        capabilities=caps,
        fields=fields,
        parameters=params,
        request_id=rid,
    )
