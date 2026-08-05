"""Status builder and dynamic status-line parser."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .codec import coerce_number, format_kv, parse_kv_pairs, split_tokens


@dataclass
class ParsedStatus:
    raw: str
    fields: dict[str, str] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    request_id: int | None = None


class StatusBuilder:
    """Assembles ``status key=value …`` (mirror StatusBuilder.h)."""

    def __init__(self) -> None:
        self._fields: list[tuple[str, str]] = []

    def reset(self) -> None:
        self._fields.clear()

    def add(self, key: str, value: Any) -> bool:
        if not key or value is None:
            return False
        if isinstance(value, float):
            rendered = f"{value:.2f}"
        else:
            rendered = str(value)
        self._fields.append((key, rendered))
        return True

    def write(self) -> str:
        if not self._fields:
            return "status"
        return "status " + format_kv(dict(self._fields))

    def field_count(self) -> int:
        return len(self._fields)


def parse_status(raw: str | None) -> ParsedStatus:
    """Parse a status response; unknown keys are preserved in ``fields`` / ``parameters``."""
    text = (raw or "").strip()
    tokens = split_tokens(text)
    rid = None
    if tokens and tokens[0].startswith("#") and tokens[0][1:].isdigit():
        rid = int(tokens[0][1:])
        tokens = tokens[1:]
    if tokens and tokens[0].lower() == "status":
        tokens = tokens[1:]
    fields = parse_kv_pairs(tokens)
    return ParsedStatus(
        raw=text,
        fields=fields,
        parameters={k: coerce_number(v) for k, v in fields.items()},
        request_id=rid,
    )
