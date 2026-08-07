"""RFC-0002 §8 — broadcast reply stagger (mirror ReplyJitter.h)."""

from __future__ import annotations

BROADCAST_MIN_MS = 250
BROADCAST_MAX_MS = 1750
ADDRESSED_MAX_MS = 120
SLOT_COUNT = 8


def identity_hash(identity: str | None) -> int:
    """FNV-1a 32-bit over identity bytes (matches C++ ReplyJitter::identityHash)."""
    h = 2166136261
    if not identity:
        return h & 0xFFFFFFFF
    for b in identity.encode("utf-8", errors="ignore"):
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return h


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
    """TX delay in milliseconds before publishing a reply.

    ``entropy`` is 0..65535 (optional). Zero → deterministic slot only.
    """
    entropy = int(entropy) & 0xFFFF
    if not broadcast:
        if ADDRESSED_MAX_MS <= 0:
            return 0
        return entropy % (ADDRESSED_MAX_MS + 1)

    span = BROADCAST_MAX_MS - BROADCAST_MIN_MS
    slot_w = span // SLOT_COUNT
    slot = identity_hash(identity) % SLOT_COUNT
    within = (entropy % slot_w) if slot_w > 0 and entropy else 0
    ms = BROADCAST_MIN_MS + slot * slot_w + within
    return min(BROADCAST_MAX_MS, ms)


def delay_seconds(
    *,
    broadcast: bool,
    identity: str | None = None,
    entropy: int | None = None,
) -> float:
    """Same as ``delay_ms`` in seconds (HA / asyncio-friendly)."""
    import random

    ent = int(entropy) if entropy is not None else random.randint(0, 65535)
    return delay_ms(broadcast=broadcast, identity=identity, entropy=ent) / 1000.0
