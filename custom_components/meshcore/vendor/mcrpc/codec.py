"""Token / key=value codec helpers."""

from __future__ import annotations

from typing import Any


def parse_kv_pairs(tokens: list[str] | str) -> dict[str, str]:
    """Parse ``key=value`` tokens. Unknown / non-kv tokens are ignored for the dict.

    Returns a plain dict preserving insertion order. Values keep original case.
    Keys are stored as given (typically lowercase in protocol output).
    """
    if isinstance(tokens, str):
        tokens = [t for t in tokens.split() if t]
    out: dict[str, str] = {}
    for tok in tokens:
        if "=" not in tok:
            continue
        key, _, value = tok.partition("=")
        if key:
            out[key] = value
    return out


def format_kv(kv: dict[str, Any]) -> str:
    """Serialize a dict to space-separated ``key=value`` tokens."""
    parts: list[str] = []
    for key, value in kv.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")
    return " ".join(parts)


def split_tokens(line: str) -> list[str]:
    """Split on ASCII whitespace, collapsing repeats (protocol tokenizer)."""
    return [t for t in line.strip().split() if t]


def coerce_number(value: str) -> int | float | str:
    """Best-effort numeric coercion for HA-friendly attributes."""
    try:
        if "." in value or "e" in value.lower():
            return float(value)
        return int(value)
    except ValueError:
        return value
