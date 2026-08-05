"""Inbound response classification and structured parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from .codec import coerce_number, parse_kv_pairs, split_tokens


class ResponseKind(Enum):
    Pong = auto()
    Ok = auto()
    Error = auto()
    Status = auto()
    Discover = auto()
    Caps = auto()
    Help = auto()
    Gps = auto()
    Battery = auto()
    Voltage = auto()
    Charging = auto()
    Event = auto()  # should normally go through event.parse_event
    Data = auto()
    Unknown = auto()


@dataclass
class ParsedResponse:
    kind: ResponseKind
    raw: str
    request_id: int | None = None
    error_code: str | None = None
    ok_detail: str | None = None
    command_hint: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    fields: dict[str, str] = field(default_factory=dict)
    # discover node name / first token when applicable
    device: str | None = None
    caps: list[str] = field(default_factory=list)
    help_commands: list[str] = field(default_factory=list)


def _strip_request_id(tokens: list[str]) -> tuple[int | None, list[str]]:
    if not tokens:
        return None, tokens
    first = tokens[0]
    if first.startswith("#") and len(first) > 1 and first[1:].isdigit():
        return int(first[1:]), tokens[1:]
    return None, tokens


def parse_response(raw: str | None) -> ParsedResponse:
    """Classify and parse a single response / data line (no sender prefix)."""
    text = (raw or "").strip()
    rid, tokens = _strip_request_id(split_tokens(text))
    if not tokens:
        return ParsedResponse(kind=ResponseKind.Unknown, raw=text, request_id=rid)

    head = tokens[0].lower()
    rest = tokens[1:]
    kv = parse_kv_pairs(rest)
    params = {k: coerce_number(v) for k, v in kv.items()}

    if head == "pong" and not rest:
        return ParsedResponse(kind=ResponseKind.Pong, raw=text, request_id=rid, command_hint="ping")

    if head == "ok":
        detail = " ".join(rest) if rest else None
        return ParsedResponse(
            kind=ResponseKind.Ok,
            raw=text,
            request_id=rid,
            ok_detail=detail,
            parameters=params,
            fields=kv,
        )

    if head == "err":
        code = rest[0] if rest else "internal"
        return ParsedResponse(
            kind=ResponseKind.Error,
            raw=text,
            request_id=rid,
            error_code=code,
            command_hint=None,
            parameters=params,
            fields=kv,
        )

    if head == "event":
        return ParsedResponse(
            kind=ResponseKind.Event,
            raw=text,
            request_id=rid,
            command_hint=rest[0] if rest else None,
            parameters=params,
            fields=kv,
        )

    if head == "status":
        return ParsedResponse(
            kind=ResponseKind.Status,
            raw=text,
            request_id=rid,
            command_hint="status",
            parameters=params,
            fields=kv,
        )

    if head == "gps":
        return ParsedResponse(
            kind=ResponseKind.Gps,
            raw=text,
            request_id=rid,
            command_hint="gps",
            parameters=params,
            fields=kv,
        )

    if head == "battery":
        return ParsedResponse(
            kind=ResponseKind.Battery,
            raw=text,
            request_id=rid,
            command_hint="battery",
            parameters=params,
            fields=kv,
        )

    if head == "voltage":
        return ParsedResponse(
            kind=ResponseKind.Voltage,
            raw=text,
            request_id=rid,
            command_hint="voltage",
            parameters=params,
            fields=kv,
        )

    if head == "charging":
        return ParsedResponse(
            kind=ResponseKind.Charging,
            raw=text,
            request_id=rid,
            command_hint="charging",
            parameters=params,
            fields=kv,
        )

    # caps: one capability per line OR space-separated on one line
    if head == "caps" or (not kv and all("=" not in t for t in tokens) and head not in {"help"}):
        # Multi-line caps replies are handled by the bridge; single-line list:
        if head == "caps":
            return ParsedResponse(
                kind=ResponseKind.Caps,
                raw=text,
                request_id=rid,
                command_hint="caps",
                caps=rest,
            )

    if head == "help":
        return ParsedResponse(
            kind=ResponseKind.Help,
            raw=text,
            request_id=rid,
            command_hint="help",
            help_commands=rest,
        )

    # Discover: `<name> profile=… fw=… protocol=… sdk=…`
    if "profile" in kv or "protocol" in kv or "sdk" in kv:
        return ParsedResponse(
            kind=ResponseKind.Discover,
            raw=text,
            request_id=rid,
            command_hint="discover",
            device=tokens[0],
            parameters=params,
            fields=kv,
        )

    # Generic data line: `<cmd> key=value…`
    if kv:
        return ParsedResponse(
            kind=ResponseKind.Data,
            raw=text,
            request_id=rid,
            command_hint=head,
            parameters=params,
            fields=kv,
        )

    # Caps multi-name single line without "caps" keyword (CapabilityRegistry
    # writes one name per line — see parse_caps_blob).
    return ParsedResponse(
        kind=ResponseKind.Unknown,
        raw=text,
        request_id=rid,
        command_hint=head,
        parameters=params,
        fields=kv,
    )


def parse_caps_blob(text: str) -> list[str]:
    """Parse CapabilityRegistry output (one capability name per line)."""
    caps: list[str] = []
    for line in (text or "").splitlines():
        name = line.strip()
        if name and " " not in name and "=" not in name:
            caps.append(name)
    if not caps:
        # fallback: space-separated on one line after optional "caps"
        tokens = split_tokens(text or "")
        if tokens and tokens[0].lower() == "caps":
            tokens = tokens[1:]
        caps = [t for t in tokens if "=" not in t]
    return caps
