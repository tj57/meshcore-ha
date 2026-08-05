"""Request model and parse result enums (mirror McRpcTypes.h)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class ParseResult(Enum):
    Ok = auto()
    Empty = auto()
    MissingTarget = auto()
    MissingCommand = auto()
    Malformed = auto()


class AddressKind(Enum):
    Named = auto()
    All = auto()
    Self = auto()
    Group = auto()


@dataclass
class Request:
    address_kind: AddressKind = AddressKind.Named
    target: str = ""
    has_request_id: bool = False
    request_id: int = 0
    command: str = ""
    args: list[str] = field(default_factory=list)

    @property
    def argc(self) -> int:
        return len(self.args)
