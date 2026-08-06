"""Discover builder and discover-line parser."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .codec import coerce_number, format_kv, parse_kv_pairs, split_tokens
from .version import PROTOCOL_VERSION, SDK_VERSION

_CORE_KEYS = frozenset(
    {
        "profile",
        "tag",
        "fw",
        "firmware",
        "board",
        "protocol",
        "protocol_min",
        "protocol_max",
        "sdk",
        "name",
        "id",
        "caps",
        "features",
        "uptime",
        "auth",
        "transport",
        "vendor",
    }
)


@dataclass
class ParsedDiscover:
    raw: str
    device: str = ""
    profile: str | None = None
    tag: str | None = None
    identity_id: str | None = None
    board: str | None = None
    firmware: str | None = None
    protocol: str | None = None
    protocol_min: str | None = None
    protocol_max: str | None = None
    sdk: str | None = None
    uptime: Any = None
    features: dict[str, str] = field(default_factory=dict)
    feature_tokens: list[str] = field(default_factory=list)
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


def _canonicalize_csv_tokens(raw: str | None) -> list[str]:
    if not raw:
        return []
    tokens = sorted({p.strip().lower() for p in str(raw).split(",") if p.strip()})
    return tokens


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

    # Legacy feature flags: gps=yes / battery=yes
    features = {k: v for k, v in fields.items() if k not in _CORE_KEYS}
    caps = [k for k, v in features.items() if str(v).lower() in {"yes", "1", "true"}]

    # RFC-0001 caps= CSV
    if fields.get("caps"):
        for part in str(fields["caps"]).split(","):
            c = part.strip().lower()
            if c and c not in caps:
                caps.append(c)
        caps = sorted(set(caps))

    feature_tokens = _canonicalize_csv_tokens(fields.get("features"))

    return ParsedDiscover(
        raw=text,
        device=device,
        profile=fields.get("profile"),
        tag=fields.get("tag") or fields.get("profile"),
        identity_id=fields.get("id"),
        board=fields.get("board"),
        firmware=fields.get("fw") or fields.get("firmware"),
        protocol=fields.get("protocol"),
        protocol_min=fields.get("protocol_min"),
        protocol_max=fields.get("protocol_max"),
        sdk=fields.get("sdk"),
        uptime=params.get("uptime"),
        features=features,
        feature_tokens=feature_tokens,
        capabilities=caps,
        fields=fields,
        parameters=params,
        request_id=rid,
    )
