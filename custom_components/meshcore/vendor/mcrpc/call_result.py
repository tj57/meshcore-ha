"""Call result helpers — RFC-0002 (mirror CallResult.h)."""

from __future__ import annotations

import re

_PROC_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*$")
_ERR_CODES = frozenset(
    {
        "unsupported",
        "unknown_proc",
        "invalid_argument",
        "denied",
        "timeout",
        "internal",
    }
)


def is_valid_proc(proc: str | None) -> bool:
    if not proc:
        return False
    if proc.count(".") != 1:
        return False
    return bool(_PROC_RE.match(proc))


def build_call_ok(**kwargs: str) -> str:
    parts = ["ok"]
    for k, v in kwargs.items():
        parts.append(f"{k}={v}")
    return " ".join(parts)


def build_call_err(code: str, **kwargs: str) -> str:
    c = code if code else "internal"
    parts = ["err", c]
    for k, v in kwargs.items():
        parts.append(f"{k}={v}")
    return " ".join(parts)


def build_call_busy(**kwargs: str) -> str:
    parts = ["busy"]
    for k, v in kwargs.items():
        parts.append(f"{k}={v}")
    return " ".join(parts)


def build_call_retry(**kwargs: str) -> str:
    parts = ["retry"]
    for k, v in kwargs.items():
        parts.append(f"{k}={v}")
    return " ".join(parts)


def parse_call_result(raw: str | None) -> dict:
    """Parse call result; unknown keys preserved. Free-form prose is invalid."""
    text = (raw or "").strip()
    tokens = text.split()
    rid = None
    if tokens and tokens[0].startswith("#") and tokens[0][1:].isdigit():
        rid = int(tokens[0][1:])
        tokens = tokens[1:]
    if not tokens:
        return {"ok": False, "kind": None, "request_id": rid, "fields": {}, "valid": False}

    kind = tokens[0].lower()
    fields: dict[str, str] = {}
    code = None
    rest = tokens[1:]
    if kind == "err":
        if not rest:
            return {"ok": False, "kind": "err", "code": "internal", "request_id": rid, "fields": {}, "valid": False}
        code = rest[0]
        rest = rest[1:]
    for tok in rest:
        if "=" not in tok:
            return {
                "ok": False,
                "kind": kind,
                "code": code,
                "request_id": rid,
                "fields": fields,
                "valid": False,
                "reason": "non_kv_token",
            }
        k, v = tok.split("=", 1)
        fields[k] = v

    if kind not in {"ok", "err", "busy", "retry"}:
        return {"ok": False, "kind": kind, "request_id": rid, "fields": fields, "valid": False}

    return {
        "ok": kind == "ok",
        "kind": kind,
        "code": code,
        "request_id": rid,
        "fields": fields,
        "valid": True,
        "known_err": code in _ERR_CODES if code else None,
    }
