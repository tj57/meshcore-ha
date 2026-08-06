"""mcRPC — pure-Python protocol library matching the C++ reference."""

from .builder import build_error, build_event, build_ok, build_request, prefix_request_id
from .client import PendingRequest, RequestCorrelator
from .discover import DiscoverBuilder, ParsedDiscover, parse_discover
from .dispatcher import Dispatcher
from .event import ParsedEvent, is_event_line, parse_event
from .parser import parse, strip_sender_prefix
from .request import AddressKind, ParseResult, Request
from .response import ParsedResponse, ResponseKind, parse_caps_blob, parse_response
from .status import ParsedStatus, StatusBuilder, parse_status
from .version import (
    LIBRARY_VERSION,
    PROTOCOL_VERSION,
    SDK_VERSION,
    protocol_version_code,
)

_GPS_WIRE_KEYS = frozenset(
    {
        "lat",
        "lon",
        "alt",
        "acc",
        "hdop",
        "vdop",
        "pdop",
        "sat",
        "sats",
        "speed",
        "heading",
        "course",
        "ts",
        "time",
        "timestamp",
        "status",
        "fix",
        "provider",
    }
)
_BATTERY_WIRE_KEYS = frozenset(
    {
        "value",
        "voltage",
        "percentage",
        "battery",
        "charging",
        "temp",
        "temperature",
        "health",
        "cycles",
    }
)
_STATUS_KNOWN = frozenset(
    {"name", "profile", "fw", "firmware", "uptime", "rssi", "battery", "voltage", "gps", "sat"}
)
_DISCOVER_KNOWN = frozenset(
    {
        "profile",
        "tag",
        "fw",
        "firmware",
        "board",
        "protocol",
        "protocol_min",
        "protocol_max",
        "sdk",
        "name",
        "id",
        "caps",
        "features",
        "uptime",
        "auth",
        "transport",
        "vendor",
    }
)


def _extra_from(params: dict, known_wire: frozenset) -> dict:
    """Return unknown key=value pairs (forward-compatible)."""
    return {k: v for k, v in params.items() if k not in known_wire}


def parse_gps(raw: str | None) -> dict:
    """Parse a GPS response; known fields + ``extra`` for unknown keys."""
    r = parse_response(raw)
    p = r.parameters
    return {
        "raw": r.raw,
        "request_id": r.request_id,
        "latitude": p.get("lat"),
        "longitude": p.get("lon"),
        "altitude": p.get("alt"),
        "accuracy": p.get("acc") if p.get("acc") is not None else p.get("hdop"),
        "hdop": p.get("hdop"),
        "vdop": p.get("vdop"),
        "pdop": p.get("pdop"),
        "satellites": p.get("sat") if p.get("sat") is not None else p.get("sats"),
        "speed": p.get("speed"),
        "heading": p.get("heading") if p.get("heading") is not None else p.get("course"),
        "timestamp": p.get("ts") or p.get("time") or p.get("timestamp"),
        "time": p.get("time") or p.get("ts") or p.get("timestamp"),
        "status": p.get("status"),
        "fix": p.get("fix") if p.get("fix") is not None else p.get("status"),
        "provider": p.get("provider"),
        "extra": _extra_from(p, _GPS_WIRE_KEYS),
        "parameters": p,
        "fields": r.fields,
    }


def parse_battery(raw: str | None) -> dict:
    """Parse battery / voltage / charging; unknown keys in ``extra``."""
    r = parse_response(raw)
    p = r.parameters
    percentage = p.get("percentage")
    if percentage is None:
        percentage = p.get("battery")
    voltage = p.get("voltage")
    charging = p.get("charging")
    if r.kind == ResponseKind.Battery and "value" in p:
        percentage = p["value"]
    elif r.kind == ResponseKind.Voltage and "value" in p:
        voltage = p["value"]
    elif r.kind == ResponseKind.Charging and "value" in p:
        charging = p["value"]
    return {
        "raw": r.raw,
        "request_id": r.request_id,
        "percentage": percentage,
        "battery": percentage,
        "voltage": voltage,
        "charging": charging,
        "temperature": p.get("temp") if p.get("temp") is not None else p.get("temperature"),
        "health": p.get("health"),
        "cycles": p.get("cycles"),
        "extra": _extra_from(p, _BATTERY_WIRE_KEYS),
        "parameters": p,
        "fields": r.fields,
    }


def parse_status_fields(raw: str | None) -> dict:
    """Status with common aliases plus ``extra`` for every other field."""
    s = parse_status(raw)
    p = s.parameters
    return {
        "raw": s.raw,
        "request_id": s.request_id,
        "name": p.get("name"),
        "profile": p.get("profile"),
        "firmware": p.get("fw") or p.get("firmware"),
        "uptime": p.get("uptime"),
        "rssi": p.get("rssi"),
        "battery": p.get("battery"),
        "voltage": p.get("voltage"),
        "gps": p.get("gps"),
        "extra": _extra_from(p, _STATUS_KNOWN),
        "parameters": p,
        "fields": s.fields,
    }


def parse_discover_fields(raw: str | None) -> dict:
    """Discover with common aliases; feature flags and unknowns in ``extra``/lists."""
    d = parse_discover(raw)
    # features that are not core discover fields stay available
    feature_extra = {
        k: v for k, v in d.fields.items() if k not in _DISCOVER_KNOWN
    }
    return {
        "raw": d.raw,
        "request_id": d.request_id,
        "device": d.device,
        "profile": d.profile,
        "board": d.board,
        "firmware": d.firmware,
        "protocol": d.protocol,
        "sdk": d.sdk,
        "features": d.features,
        "capabilities": d.capabilities,
        "extra": {k: coerce_maybe(v) for k, v in feature_extra.items()},
        "parameters": d.parameters,
        "fields": d.fields,
    }


def coerce_maybe(value):
    from .codec import coerce_number

    if isinstance(value, str):
        return coerce_number(value)
    return value

__all__ = [
    "PROTOCOL_VERSION",
    "SDK_VERSION",
    "LIBRARY_VERSION",
    "protocol_version_code",
    "AddressKind",
    "ParseResult",
    "Request",
    "parse",
    "strip_sender_prefix",
    "build_request",
    "build_event",
    "build_ok",
    "build_error",
    "prefix_request_id",
    "ParsedResponse",
    "ResponseKind",
    "parse_response",
    "parse_caps_blob",
    "ParsedEvent",
    "parse_event",
    "is_event_line",
    "ParsedStatus",
    "StatusBuilder",
    "parse_status",
    "ParsedDiscover",
    "DiscoverBuilder",
    "parse_discover",
    "parse_gps",
    "parse_battery",
    "parse_status_fields",
    "parse_discover_fields",
    "Dispatcher",
    "PendingRequest",
    "RequestCorrelator",
]
