"""Validate browser origins against explicit deployment URLs or direct same-origin requests."""
import os
from urllib.parse import urlparse

def origin_key(value):
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        return None
    try:
        parsed = urlparse(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment):
            return None
        return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None

# AutoDL strips the public :8443 port from the upstream Host header.
# Explicit deployment origins avoid trusting arbitrary X-Forwarded-Host values.
PUBLIC_ORIGINS = frozenset(filter(None, (
    origin_key(value.strip())
    for value in os.environ.get(
        "PORTRAIT_PUBLIC_ORIGINS",
        "https://u55868-7936f251bb5f.westd.seetacloud.com:8443"
    ).split(",")
)))

def is_allowed_origin(origin, scheme, host):
    source = origin_key(origin)
    if source is None:
        return False
    return source in PUBLIC_ORIGINS or source == origin_key(f"{scheme}://{host}")

