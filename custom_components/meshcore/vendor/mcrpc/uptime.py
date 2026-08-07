"""Human-readable uptime (mirror UptimeFormat.h)."""


def format_uptime(seconds: int) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m" if s == 0 else f"{m}m{s}s"
    if seconds < 86400:
        h, rem = divmod(seconds, 3600)
        m = rem // 60
        return f"{h}h" if m == 0 else f"{h}h{m}m"
    d, rem = divmod(seconds, 86400)
    h = rem // 3600
    return f"{d}d" if h == 0 else f"{d}d{h}h"


def short_id8(full_hex: str | None) -> str:
    if not full_hex:
        return ""
    hx = "".join(c for c in str(full_hex).lower() if c in "0123456789abcdef")
    return hx[:8]
