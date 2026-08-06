"""Security / listening policy for Mesh Node Requests (inbound).

Protocol-agnostic filters: channel, addressing mode, allowed senders.
RFC-0001: identity name / @id / all only — no role or capability addressing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .const import (
    CONF_MCRPC_ACCEPT_ADDRESSED,
    CONF_MCRPC_ACCEPT_BARE,
    CONF_MCRPC_ACCEPT_BROADCAST,
    CONF_MCRPC_ALLOW_LIST,
    CONF_MCRPC_ANSWER_REQUESTS,
    CONF_MCRPC_CHANNEL,
    CONF_MCRPC_LISTEN_CHANNELS,
    CONF_MCRPC_LISTEN_MODE,
    CONF_MCRPC_REPLY_IDENTITY,
    CONF_MCRPC_SENDER_MODE,
    CONF_NAME,
    DEFAULT_MCRPC_CHANNEL,
    DEFAULT_MCRPC_LISTEN_MODE,
    DEFAULT_MCRPC_REPLY_IDENTITY,
    DEFAULT_MCRPC_SENDER_MODE,
    MCRPC_LISTEN_ALL,
    MCRPC_LISTEN_CURRENT,
    MCRPC_LISTEN_DISABLED,
    MCRPC_LISTEN_SELECTED,
    MCRPC_SENDER_ALLOWLIST,
    MCRPC_SENDER_ANY,
    MCRPC_SENDER_CONTACTS,
    migrate_mcrpc_config,
)


@dataclass(frozen=True)
class InboundDecision:
    allow: bool
    reason: str
    addressing: str  # broadcast | addressed | bare | response | event | none


def _is_hex(s: str) -> bool:
    return bool(s) and all(c in "0123456789abcdef" for c in s)


class McRpcPolicy:
    """Evaluate whether an inbound channel message may be processed / answered."""

    def __init__(
        self,
        entry_data: dict[str, Any],
        *,
        entry_id: str,
        identity_id: str | None = None,
    ) -> None:
        data = migrate_mcrpc_config(entry_data)
        self.entry_id = entry_id
        self.listen_mode = data.get(CONF_MCRPC_LISTEN_MODE, DEFAULT_MCRPC_LISTEN_MODE)
        self.listen_channels = [int(c) for c in data.get(CONF_MCRPC_LISTEN_CHANNELS, [])]
        self.current_channel = int(data.get(CONF_MCRPC_CHANNEL, DEFAULT_MCRPC_CHANNEL))
        self.accept_broadcast = bool(data.get(CONF_MCRPC_ACCEPT_BROADCAST, True))
        self.accept_addressed = bool(data.get(CONF_MCRPC_ACCEPT_ADDRESSED, True))
        self.accept_bare = bool(data.get(CONF_MCRPC_ACCEPT_BARE, False))
        self.sender_mode = data.get(CONF_MCRPC_SENDER_MODE, DEFAULT_MCRPC_SENDER_MODE)
        self.allow_list = {a.lower() for a in data.get(CONF_MCRPC_ALLOW_LIST, [])}
        self.reply_identity = data.get(CONF_MCRPC_REPLY_IDENTITY, DEFAULT_MCRPC_REPLY_IDENTITY)
        self.answer_requests = bool(data.get(CONF_MCRPC_ANSWER_REQUESTS, True))
        self.local_name = (data.get(CONF_NAME) or "").strip()
        # Extra *identity* names only (e.g. companion radio name) — never role labels
        extras = data.get("_mcrpc_name_aliases") or []
        self.name_aliases = {str(a).strip().lower() for a in extras if str(a).strip()}
        self.identity_id = (identity_id or "").strip().lower()

    def identity_names(self) -> set[str]:
        names: set[str] = set(self.name_aliases)
        if self.local_name:
            names.add(self.local_name.lower())
        return names

    def listening_channel_indexes(self) -> list[int] | None:
        """Return concrete indexes, or None meaning all channels."""
        if self.listen_mode == MCRPC_LISTEN_DISABLED:
            return []
        if self.listen_mode == MCRPC_LISTEN_ALL:
            return None
        if self.listen_mode == MCRPC_LISTEN_CURRENT:
            return [self.current_channel]
        return list(self.listen_channels)

    def channel_allowed(self, channel_idx: int | None) -> bool:
        if self.listen_mode == MCRPC_LISTEN_DISABLED:
            return False
        if self.listen_mode == MCRPC_LISTEN_ALL:
            return True
        indexes = self.listening_channel_indexes() or []
        if channel_idx is None:
            return False
        return int(channel_idx) in indexes

    def sender_allowed(
        self,
        sender_name: str | None,
        *,
        contact_names: Iterable[str] | None = None,
    ) -> bool:
        if self.sender_mode == MCRPC_SENDER_ANY:
            return True
        name = (sender_name or "").strip().lower()
        if not name:
            return False
        if self.sender_mode == MCRPC_SENDER_ALLOWLIST:
            return name in self.allow_list
        if self.sender_mode == MCRPC_SENDER_CONTACTS:
            contacts = {c.strip().lower() for c in (contact_names or []) if c}
            return name in contacts
        return False

    def classify_addressing(self, req, parse_ok: bool) -> str:
        """Return broadcast | addressed | bare | none."""
        if not parse_ok or req is None:
            return "bare"
        kind = getattr(req.address_kind, "name", str(req.address_kind))
        if kind in {"All", "Group"}:
            return "broadcast"
        if kind in {"Named", "Self", "Id"}:
            return "addressed"
        return "bare"

    def _id_matches(self, target: str) -> bool:
        """Full or unique-prefix match against local identity_id (case-insensitive)."""
        if not self.identity_id or not _is_hex(self.identity_id):
            return False
        t = (target or "").strip().lower()
        if not t or not _is_hex(t):
            return False
        if t == self.identity_id:
            return True
        # Single local peer ⇒ any matching prefix is unambiguous for *this* node.
        # Clients with multi-node caches must resolve uniqueness before TX.
        return len(t) >= 1 and self.identity_id.startswith(t)

    def addressed_to_us(self, req) -> bool:
        if req is None:
            return False
        kind = getattr(req.address_kind, "name", "")
        if kind == "All":
            return True
        if kind == "Self":
            return True
        if kind == "Id":
            return self._id_matches(getattr(req, "target", "") or "")
        if kind == "Named":
            target = (req.target or "").strip().lower()
            if not target:
                return False
            # Identity names only — never hardcoded role aliases (ha, gateway, …)
            return target in self.identity_names()
        if kind == "Group":
            return False
        return False

    def decide_inbound_request(
        self,
        *,
        channel_idx: int | None,
        sender_name: str | None,
        req,
        parse_ok: bool,
        contact_names: Iterable[str] | None = None,
    ) -> InboundDecision:
        if not self.channel_allowed(channel_idx):
            return InboundDecision(False, "channel_not_listening", "none")
        if not self.sender_allowed(sender_name, contact_names=contact_names):
            return InboundDecision(False, "sender_denied", "none")

        if parse_ok and req is not None and getattr(req.address_kind, "name", "") == "Group":
            return InboundDecision(False, "group_not_supported", "broadcast")

        addressing = self.classify_addressing(req, parse_ok)
        if addressing == "broadcast" and not self.accept_broadcast:
            return InboundDecision(False, "broadcast_disabled", addressing)
        if addressing == "addressed" and not self.accept_addressed:
            return InboundDecision(False, "addressed_disabled", addressing)
        if addressing == "bare" and not self.accept_bare:
            return InboundDecision(False, "bare_disabled", addressing)

        if addressing == "addressed" and parse_ok and not self.addressed_to_us(req):
            return InboundDecision(False, "not_addressed_to_us", addressing)

        return InboundDecision(True, "ok", addressing)

    def decide_inbound_traffic(
        self,
        *,
        channel_idx: int | None,
        sender_name: str | None,
        contact_names: Iterable[str] | None = None,
    ) -> InboundDecision:
        """Filter for response/event correlation (channel + sender only)."""
        if not self.channel_allowed(channel_idx):
            return InboundDecision(False, "channel_not_listening", "response")
        if not self.sender_allowed(sender_name, contact_names=contact_names):
            return InboundDecision(False, "sender_denied", "response")
        return InboundDecision(True, "ok", "response")

    def resolve_reply_entry_id(self, hass_data_domain: dict) -> str:
        """Pick which config entry should send the reply (multi-radio ready)."""
        rid = self.reply_identity or DEFAULT_MCRPC_REPLY_IDENTITY
        if rid == "self" or rid == self.entry_id:
            return self.entry_id
        if rid in hass_data_domain and hasattr(hass_data_domain[rid], "api"):
            return rid
        return self.entry_id

    def summary(self) -> dict[str, Any]:
        return {
            "listen_mode": self.listen_mode,
            "listen_channels": self.listening_channel_indexes(),
            "current_channel": self.current_channel,
            "accept_broadcast": self.accept_broadcast,
            "accept_addressed": self.accept_addressed,
            "accept_bare": self.accept_bare,
            "sender_mode": self.sender_mode,
            "allow_list": sorted(self.allow_list),
            "reply_identity": self.reply_identity,
            "answer_requests": self.answer_requests,
            "local_name": self.local_name,
            "identity_names": sorted(self.identity_names()),
            "identity_id": self.identity_id or None,
            "identity_id_prefix": (self.identity_id[:12] if self.identity_id else None),
        }
