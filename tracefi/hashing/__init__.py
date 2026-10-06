"""Bounded, versioned canonical JSON. Hashes cover redacted stored snapshots."""

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

CANONICAL_VERSION = "tracefi-json-v1"
SUPPORTED_CANONICAL_VERSIONS = {CANONICAL_VERSION, "agenttrace-json-v1"}
MAX_DEPTH = 64
MAX_NODES = 100_000
MAX_BYTES = 8 * 1024 * 1024
MAX_NUMBER_DIGITS = 4096
_TIMESTAMP = re.compile(
    r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.(?P<fraction>\d+))?(?:Z|[+-]\d\d:\d\d)$"
)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonicalize(value: Any) -> bytes:
    """Deterministic UTF-8 JSON; reject cycles, excess size and precision loss.

    Equivalent finite numbers share a representation. Recognized timestamp
    values normalize to UTC microseconds. Object keys and Unicode are preserved.
    This format does not claim RFC 8785 compatibility.
    """
    ancestors: set[int] = set()
    nodes = 0
    output: list[str] = []
    size = 0

    def append(part: str) -> None:
        nonlocal size
        size += len(part.encode("utf-8"))
        if size > MAX_BYTES:
            raise ValueError("Canonical JSON exceeds the byte limit")
        output.append(part)

    def encode(item: Any, depth: int = 0) -> None:
        nonlocal nodes
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise ValueError("Canonical JSON exceeds structural limits")
        if item is None:
            append("null")
        elif isinstance(item, bool):
            append("true" if item else "false")
        elif isinstance(item, (int, float, Decimal)):
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("Non-finite numbers are not supported")
            number = Decimal(str(item))
            if not number.is_finite():
                raise ValueError("Non-finite numbers are not supported")
            if number == 0:
                append("0")
                return
            if number.adjusted() >= MAX_NUMBER_DIGITS:
                raise ValueError("Number exceeds the digit limit")
            exponent = number.as_tuple().exponent
            if not isinstance(exponent, int):
                raise ValueError("Invalid numeric exponent")
            if max(number.adjusted() + 1, 0) + max(-exponent, 0) > MAX_NUMBER_DIGITS:
                raise ValueError("Number exceeds the digit limit")
            result = format(number, "f")
            append(result.rstrip("0").rstrip(".") if "." in result else result)
        elif isinstance(item, (str, datetime)):
            if isinstance(item, datetime):
                item = _timestamp(item)
            if len(item) > MAX_BYTES:
                raise ValueError("String exceeds the byte limit")
            match = _TIMESTAMP.fullmatch(item)
            if match:
                fraction = match.group("fraction") or ""
                if any(digit != "0" for digit in fraction[6:]):
                    raise ValueError("Sub-microsecond timestamp precision is unsupported")
                if fraction:
                    start, end = match.span("fraction")
                    item = item[:start] + fraction[:6].ljust(6, "0") + item[end:]
                item = _timestamp(datetime.fromisoformat(item.replace("Z", "+00:00")))
            append(json.dumps(item, ensure_ascii=False))
        elif isinstance(item, (Mapping, list, tuple)):
            identity = id(item)
            if identity in ancestors:
                raise ValueError("Cyclic values are not JSON")
            ancestors.add(identity)
            try:
                if isinstance(item, Mapping):
                    if not all(isinstance(key, str) for key in item):
                        raise TypeError("Canonical JSON keys must be strings")
                    append("{")
                    for index, key in enumerate(sorted(item)):
                        if len(key) > MAX_BYTES:
                            raise ValueError("Object key exceeds the byte limit")
                        if index:
                            append(",")
                        append(json.dumps(key, ensure_ascii=False))
                        append(":")
                        encode(item[key], depth + 1)
                    append("}")
                else:
                    append("[")
                    for index, part in enumerate(item):
                        if index:
                            append(",")
                        encode(part, depth + 1)
                    append("]")
            finally:
                ancestors.remove(identity)
        else:
            raise TypeError("Unsupported canonical JSON value")

    encode(value)
    return "".join(output).encode("utf-8")


def state_hash(value: Any) -> str:
    return hashlib.sha256(canonicalize(value)).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON constants are unsupported")


def load_json(raw: str | bytes) -> Any:
    """Read bounded JSON, rejecting ambiguous keys and lossy numeric values."""
    if len(raw) > MAX_BYTES:
        raise ValueError("JSON input exceeds the byte limit")
    try:
        parsed = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=Decimal,
        )
    except RecursionError:
        raise ValueError("JSON input exceeds structural limits") from None
    canonical = canonicalize(parsed)
    result = json.loads(canonical)
    if canonicalize(result) != canonical:
        raise ValueError("JSON snapshot would lose numeric precision")
    return result


def snapshot(value: Any) -> Any:
    return load_json(canonicalize(value))
