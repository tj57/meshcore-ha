"""Minimal dispatcher for protocol tests (ping + unknown_command).

Production firmware uses the C++ Dispatcher; Python peers are typically
clients. This module exists so golden / compliance suites share behaviour.
"""

from __future__ import annotations

from collections.abc import Callable

from .builder import prefix_request_id
from .parser import parse
from .request import AddressKind, ParseResult, Request

CommandHandler = Callable[[Request], str]


class Dispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}
        self.node_name = ""
        self.group_name = ""

    def register(self, command: str, handler: CommandHandler) -> None:
        self._handlers[command.lower()] = handler

    def set_node_name(self, name: str) -> None:
        self.node_name = name

    def set_group_name(self, name: str) -> None:
        self.group_name = name

    def _addressed(self, req: Request) -> bool:
        if req.address_kind == AddressKind.All:
            return True
        if req.address_kind == AddressKind.Self:
            return True
        if req.address_kind == AddressKind.Group:
            return bool(self.group_name) and req.target.lower() == self.group_name.lower()
        return bool(self.node_name) and req.target.lower() == self.node_name.lower()

    def dispatch(self, line: str) -> str | None:
        result, req = parse(line)
        if result == ParseResult.Empty:
            return None
        if result != ParseResult.Ok:
            return None
        if not self._addressed(req):
            return None

        handler = self._handlers.get(req.command)
        if handler is None:
            body = "err unknown_command"
        else:
            body = handler(req) or "ok"

        rid = req.request_id if req.has_request_id else None
        return prefix_request_id(body, rid)
