"""Async event lines: ``event <name> [k=v…]``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .builder import build_event
from .codec import coerce_number, parse_kv_pairs, split_tokens


@dataclass
class ParsedEvent:
    name: str
    raw: str
    parameters: dict[str, Any] = field(default_factory=dict)
    fields: dict[str, str] = field(default_factory=dict)


def parse_event(raw: str | None) -> ParsedEvent | None:
    """Return a :class:`ParsedEvent` if ``raw`` is an event line, else ``None``."""
    text = (raw or "").strip()
    tokens = split_tokens(text)
    if not tokens or tokens[0].lower() != "event":
        return None
    if len(tokens) < 2:
        return ParsedEvent(name="", raw=text)
    name = tokens[1]
    kv = parse_kv_pairs(tokens[2:])
    return ParsedEvent(
        name=name,
        raw=text,
        parameters={k: coerce_number(v) for k, v in kv.items()},
        fields=kv,
    )


def is_event_line(raw: str | None) -> bool:
    tokens = split_tokens(raw or "")
    return bool(tokens) and tokens[0].lower() == "event"


# Re-export builder helper for callers that import from event module
event_line = build_event
