"""RFC-0002 §8 — broadcast reply stagger (mirror ReplyJitter.h)."""

from __future__ import annotations

BROADCAST_MIN_MS = 400
BROADCAST_MAX_MS = 3600
ADDRESSED_MAX_MS = 120
SLOT_COUNT = 16

# Companion radios that also TX the request (HA Chat) should listen first.
COMPANION_LISTEN_BIAS_MS = 1200
LOCAL_TX_SETTLE_MS = 400


def identity_hash(identity: str | None) -> int:
    """FNV-1a 32-bit over identity bytes (matches C++ ReplyJitter::identityHash)."""
    h = 2166136261
    if not identity:
        return h & 0xFFFFFFFF
    for b in identity.encode("utf-8", errors="ignore"):
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def slot_seed(identity: str | None) -> str:
    """Prefer discovery-style 8-hex id when identity is pubkey hex (matches C++)."""
    if not identity:
        return ""
    s = identity.strip()
    if len(s) >= 8 and all(c in "0123456789abcdefABCDEF" for c in s):
        return s[:8].lower()
    return s


def needs_broadcast_stagger(*, address_kind: str | None = None, target: str | None = None) -> bool:
    """True when answering ``all`` (multi-responder)."""
    kind = (address_kind or "").strip().lower()
    if kind == "all":
        return True
    return (target or "").strip().lower() == "all"


def delay_ms(
    *,
    broadcast: bool,
    identity: str | None = None,
    entropy: int = 0,
) -> int:
    """TX delay in milliseconds before publishing a reply."""
    entropy = int(entropy) & 0xFFFF
    if not broadcast:
        if ADDRESSED_MAX_MS <= 0:
            return 0
        return entropy % (ADDRESSED_MAX_MS + 1)

    seed = slot_seed(identity) or (identity or "")
    span = BROADCAST_MAX_MS - BROADCAST_MIN_MS
    slot_w = span // SLOT_COUNT
    slot = identity_hash(seed) % SLOT_COUNT
    within = (entropy % slot_w) if slot_w > 0 and entropy else 0
    ms = BROADCAST_MIN_MS + slot * slot_w + within
    return min(BROADCAST_MAX_MS, ms)


def delay_seconds(
    *,
    broadcast: bool,
    identity: str | None = None,
    entropy: int | None = None,
    companion_bias: bool = False,
    local_tx_settle: bool = False,
) -> float:
    """Seconds before TX. Companion bias = listen for peers first (HA)."""
    import random

    ent = int(entropy) if entropy is not None else random.randint(0, 65535)
    ms = delay_ms(broadcast=broadcast, identity=identity, entropy=ent)
    if broadcast and companion_bias:
        ms += COMPANION_LISTEN_BIAS_MS
    if broadcast and local_tx_settle:
        ms += LOCAL_TX_SETTLE_MS
    return ms / 1000.0
