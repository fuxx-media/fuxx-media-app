"""Small security primitives shared by later API and provider code."""

from collections.abc import Mapping, Sequence
from typing import Any

SENSITIVE_MARKERS = ("authorization", "cookie", "password", "secret", "token", "api_key")
REDACTED = "[REDACTED]"


def redact(value: Any, key: str | None = None) -> Any:
    """Recursively redact values whose field name indicates secret material."""

    if key is not None and any(marker in key.lower() for marker in SENSITIVE_MARKERS):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(item_key): redact(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item) for item in value]
    return value
