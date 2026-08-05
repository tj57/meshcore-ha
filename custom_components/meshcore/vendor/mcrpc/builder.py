"""Outbound line builders — mirror OutboundBuilder.h."""

from __future__ import annotations


def build_request(
    target: str,
    command: str,
    *,
    request_id: int | None = None,
    args: list[str] | None = None,
) -> str:
    """Build ``target[#id] command [args…]``."""
    if not target or not command:
        raise ValueError("target and command are required")
    parts = [target]
    if request_id is not None:
        parts[0] = f"{target}#{int(request_id)}"
    line = f"{parts[0]} {command}"
    if args:
        line = line + " " + " ".join(a for a in args if a is not None)
    return line


def build_event(name: str, kv: str | None = None) -> str:
    """Build ``event <name> [kv]``."""
    if not name:
        raise ValueError("event name is required")
    if kv:
        return f"event {name} {kv}"
    return f"event {name}"


def build_error(code: str | None = None) -> str:
    return f"err {code or 'internal'}"


def build_ok(detail: str | None = None) -> str:
    if detail:
        return f"ok {detail}"
    return "ok"


def prefix_request_id(body: str, request_id: int | None) -> str:
    """Prefix a reply body with ``#id `` when correlating (Dispatcher::writePrefixed)."""
    if request_id is None:
        return body
    return f"#{int(request_id)} {body}"
