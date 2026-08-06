"""Wire parser — behaviour must match src/Parser.cpp."""

from __future__ import annotations

from .request import AddressKind, ParseResult, Request

_IDENT_EXTRA = set("_-")


def _is_ident_char(c: str) -> bool:
    return c.isalnum() or c in _IDENT_EXTRA


def _skip_spaces(s: str, i: int) -> int:
    n = len(s)
    while i < n and s[i] in " \t":
        i += 1
    return i


def _read_token(s: str, i: int, *, ident_only: bool) -> tuple[str | None, int]:
    i = _skip_spaces(s, i)
    n = len(s)
    if i >= n:
        return None, i
    start = i
    if ident_only:
        while i < n and _is_ident_char(s[i]):
            i += 1
    else:
        while i < n and s[i] not in " \t\r\n":
            i += 1
    if i == start:
        return None, i
    return s[start:i], i


def strip_sender_prefix(text: str | None) -> str:
    """Strip chat-style ``Name: payload`` prefixes.

    Requires whitespace after ``:``. Protocol tokens such as ``group:sensors``
    are left untouched (same rule as C++ ``Parser::stripSenderPrefix``).
    """
    if text is None:
        return ""
    colon = text.find(":")
    if colon < 0:
        return text
    for c in text[:colon]:
        if c in " \t":
            return text
    if colon + 1 >= len(text) or text[colon + 1] not in " \t":
        return text
    msg = text[colon + 1 :]
    return msg.lstrip(" \t")


def _is_hex_char(c: str) -> bool:
    return c in "0123456789abcdefABCDEF"


def parse(input_text: str | None) -> tuple[ParseResult, Request]:
    """Parse a request line into a :class:`Request`."""
    out = Request()
    if input_text is None:
        return ParseResult.Empty, out

    s = input_text
    i = _skip_spaces(s, 0)
    while i < len(s) and s[i] in "\r\n":
        i += 1
    if i >= len(s):
        return ParseResult.Empty, out

    i = _skip_spaces(s, i)
    if i >= len(s):
        return ParseResult.MissingTarget, out

    lower_rest = s[i:].lower()
    if s[i] == "@":
        i += 1
        start = i
        while i < len(s) and _is_hex_char(s[i]):
            i += 1
        if i == start:
            return ParseResult.Malformed, out
        out.target = s[start:i]
        out.address_kind = AddressKind.Id
    elif lower_rest.startswith("group:"):
        out.address_kind = AddressKind.Group
        i += 6
        token, i = _read_token(s, i, ident_only=True)
        if token is None:
            return ParseResult.Malformed, out
        out.target = token
    else:
        token, i = _read_token(s, i, ident_only=True)
        if token is None:
            return ParseResult.Malformed, out
        out.target = token
        low = token.lower()
        if low == "all":
            out.address_kind = AddressKind.All
        elif low == "self":
            out.address_kind = AddressKind.Self
        else:
            out.address_kind = AddressKind.Named

    # glued #id inside target token: node1#42
    hash_pos = out.target.find("#")
    if hash_pos >= 0 and hash_pos + 1 < len(out.target):
        digits = out.target[hash_pos + 1 :]
        if digits.isdigit():
            out.has_request_id = True
            out.request_id = int(digits)
            out.target = out.target[:hash_pos]

    # separate "#42" token (digits only — not node id)
    i = _skip_spaces(s, i)
    if i < len(s) and s[i] == "#":
        i += 1
        start = i
        while i < len(s) and s[i].isdigit():
            i += 1
        if i == start:
            return ParseResult.Malformed, out
        out.has_request_id = True
        out.request_id = int(s[start:i])

    cmd, i = _read_token(s, i, ident_only=True)
    if cmd is None:
        return ParseResult.MissingCommand, out
    out.command = cmd.lower()
    if out.command == "discover":
        out.command = "discovery"

    while True:
        arg, i = _read_token(s, i, ident_only=False)
        if arg is None:
            break
        out.args.append(arg)

    return ParseResult.Ok, out
