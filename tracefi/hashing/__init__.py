"""Versioned canonical JSON. Hashes cover redacted, stored snapshots."""
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from decimal import Decimal
from collections.abc import Mapping

CANONICAL_VERSION = "tracefi-json-v1"
SUPPORTED_CANONICAL_VERSIONS = {CANONICAL_VERSION, "agenttrace-json-v1"}
_TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$")


def _timestamp(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonicalize(value):
    """Return deterministic UTF-8 JSON; reject ambiguous/non-finite values.

    Equivalent finite numbers share a representation. Timestamp strings in
    ISO-8601 with an explicit offset are normalized to UTC. Unicode is preserved.
    This is our versioned format, not a claim of RFC 8785 compatibility.
    """
    def encode(item):
        if item is None:
            return "null"
        if isinstance(item, bool):
            return "true" if item else "false"
        if isinstance(item, (int, float, Decimal)):
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("Non-finite numbers are not supported")
            number = Decimal(str(item))
            if not number.is_finite():
                raise ValueError("Non-finite numbers are not supported")
            if number == 0:
                return "0"
            result = format(number, "f")
            return result.rstrip("0").rstrip(".") if "." in result else result
        if isinstance(item, datetime):
            item = _timestamp(item)
        if isinstance(item, str):
            if _TIMESTAMP.fullmatch(item):
                item = _timestamp(datetime.fromisoformat(item.replace("Z", "+00:00")))
            return json.dumps(item, ensure_ascii=False)
        if isinstance(item, Mapping):
            if not all(isinstance(key, str) for key in item):
                raise TypeError("Canonical JSON keys must be strings")
            return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + encode(item[key]) for key in sorted(item)) + "}"
        if isinstance(item, (list, tuple)):
            return "[" + ",".join(encode(part) for part in item) + "]"
        raise TypeError(f"Unsupported canonical JSON value: {type(item).__name__}")
    return encode(value).encode("utf-8")


def state_hash(value):
    return hashlib.sha256(canonicalize(value)).hexdigest()


def snapshot(value):
    return json.loads(canonicalize(value))
