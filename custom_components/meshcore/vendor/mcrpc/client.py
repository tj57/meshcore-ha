"""Client-side request correlation helpers for Home Assistant / apps."""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any

from .builder import build_request
from .event import ParsedEvent, parse_event
from .parser import ParseResult, parse, strip_sender_prefix
from .response import ParsedResponse, ResponseKind, parse_response

# Commands that are always inbound *requests* when parse() succeeds.
# Prevents ``name#id call proc entity=…`` being treated as ResponseKind.Data.
_REQUEST_COMMANDS = frozenset(
    {
        "ping",
        "status",
        "call",
        "discovery",
        "discover",
        "gps",
        "battery",
        "voltage",
        "charging",
        "help",
        "caps",
        "button",
        "button_state",
        "reboot",
        "set",
        "get",
    }
)


@dataclass
class PendingRequest:
    request_id: int
    target: str
    command: str
    arguments: list[str]
    channel_idx: int
    deadline: float
    raw_request: str
    meta: dict[str, Any] = field(default_factory=dict)


class RequestCorrelator:
    """Allocate request IDs and match inbound replies / events."""

    def __init__(self, *, default_timeout: float = 15.0, start_id: int = 1) -> None:
        self.default_timeout = default_timeout
        self._next_id = itertools.count(start_id)
        self._pending: dict[int, PendingRequest] = {}

    def next_request_id(self) -> int:
        return next(self._next_id)

    def build(
        self,
        target: str,
        command: str,
        *,
        arguments: list[str] | None = None,
        request_id: int | None = None,
        timeout: float | None = None,
        channel_idx: int = 0,
        broadcast: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> tuple[str, PendingRequest]:
        rid = request_id if request_id is not None else self.next_request_id()
        dest = "all" if broadcast else target
        line = build_request(dest, command, request_id=rid, args=arguments or [])
        pending = PendingRequest(
            request_id=rid,
            target=dest,
            command=command,
            arguments=list(arguments or []),
            channel_idx=channel_idx,
            deadline=time.monotonic() + (timeout if timeout is not None else self.default_timeout),
            raw_request=line,
            meta=dict(meta or {}),
        )
        self._pending[rid] = pending
        return line, pending

    def expire(self) -> list[PendingRequest]:
        now = time.monotonic()
        expired = [p for p in self._pending.values() if p.deadline <= now]
        for p in expired:
            self._pending.pop(p.request_id, None)
        return expired

    def take(self, request_id: int | None) -> PendingRequest | None:
        if request_id is None:
            return None
        return self._pending.pop(request_id, None)

    def peek(self, request_id: int | None) -> PendingRequest | None:
        if request_id is None:
            return None
        return self._pending.get(request_id)

    def is_outbound_echo(self, body: str) -> bool:
        """True when ``body`` matches a still-pending request line we sent."""
        return any(p.raw_request == body for p in self._pending.values())

    @staticmethod
    def looks_like_request(body: str) -> bool:
        """True when ``body`` parses as a known inbound command (not a reply)."""
        pr, req = parse(body)
        if pr != ParseResult.Ok:
            return False
        return (req.command or "").lower() in _REQUEST_COMMANDS

    def classify_inbound(
        self, raw_message: str, *, consume: bool = True
    ) -> tuple[str, ParsedResponse | None, ParsedEvent | None, PendingRequest | None]:
        """Return ``(kind, response, event, pending)`` where kind is response|event|other.

        When the pending request is a broadcast (``meta["broadcast"]``), the pending
        entry is peeked (not consumed) so multiple replies can share one request_id.
        Pass ``consume=False`` to never remove pending.

        Known request lines (``call … entity=``, ``all ping``, …) return ``other``
        so hosts answer them — they must not be classified as ``ResponseKind.Data``.
        """
        body = strip_sender_prefix(raw_message)
        event = parse_event(body)
        if event is not None:
            return "event", None, event, None

        # Request grammar wins over generic ``<token> key=value`` Data responses.
        if self.looks_like_request(body):
            return "other", None, None, None

        resp = parse_response(body)
        if resp.request_id is None:
            return "response", resp, None, None
        pending = self.peek(resp.request_id)
        if pending is None:
            return "response", resp, None, None
        is_broadcast = bool(pending.meta.get("broadcast"))
        if consume and not is_broadcast:
            pending = self.take(resp.request_id)
        return "response", resp, None, pending
