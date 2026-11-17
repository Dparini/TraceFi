import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.helpers import JSON, TEXT
from tracefi.hashing import (
    MAX_BYTES,
    MAX_DEPTH,
    MAX_NODES,
    canonicalize,
    finite_number,
    load_json,
    snapshot,
    state_hash,
)


def test_golden_bytes_and_value_types():
    assert (
        canonicalize({"é": [True, None, -0.0, 1.0, Decimal("0.10")], "a": "x\n"})
        == '{"a":"x\\n","é":[true,null,0,1,0.1]}'.encode()
    )
    assert state_hash(False) != state_hash(0)
    assert state_hash("é") != state_hash("é")
    assert state_hash([1, 2]) != state_hash([2, 1])


def test_precision_is_never_silently_lost():
    for value in (Decimal("1.0000000000000000001"), Decimal("1e-400")):
        with pytest.raises(ValueError):
            snapshot(value)
    with pytest.raises(ValueError):
        load_json('{"price":1.0000000000000000001}')
    assert snapshot(Decimal("0.10")) == 0.1


def test_timestamp_precision_naive_values_and_invalid_dates():
    for value in (
        "2026-10-06T10:00:00.1234567Z",
        "2026-10-06T10:00:00.1234568Z",
        "2026-02-30T10:00:00Z",
        "2026-10-06T10:00:00+25:00",
        datetime(2026, 10, 6),
    ):
        with pytest.raises(ValueError):
            canonicalize(value)
    assert canonicalize("2026-10-06T10:00:00.123456000Z") == canonicalize(
        "2026-10-06T10:00:00.123456Z"
    )
    assert snapshot("2026-10-06T10:00:00") == "2026-10-06T10:00:00"


def test_timestamp_object_keys_are_not_normalized():
    state = {"2026-10-06T12:00:00+02:00": 1, "2026-10-06T10:00:00Z": 2}
    assert json.loads(canonicalize(state)) == state


def test_nonfinite_unsupported_and_surrogate_values():
    for value in (float("nan"), float("inf"), Decimal("NaN"), Decimal("Infinity"), "\ud800"):
        with pytest.raises(ValueError):
            canonicalize(value)
    for value in ({1: "key"}, b"bytes", {1, 2}, object()):
        with pytest.raises(TypeError):
            canonicalize(value)
    for raw in ('{"x":1,"x":2}', '{"x":NaN}', "1e1000000000"):
        with pytest.raises(ValueError):
            load_json(raw)


def test_cycles_depth_size_and_decimal_exponents():
    cyclic: list = []
    cyclic.append(cyclic)
    with pytest.raises(ValueError):
        canonicalize(cyclic)
    value: object = 0
    for _ in range(MAX_DEPTH + 1):
        value = [value]
    with pytest.raises(ValueError):
        canonicalize(value)
    with pytest.raises(ValueError):
        canonicalize([0] * MAX_NODES)
    with pytest.raises(ValueError):
        canonicalize("x" * MAX_BYTES)
    with pytest.raises(ValueError):
        load_json(" " * (MAX_BYTES + 1))
    for number in (Decimal("1e1000000000"), Decimal("1e-1000000000")):
        with pytest.raises(ValueError):
            canonicalize(number)
    shared = [1]
    assert snapshot([shared, shared]) == [[1], [1]]


def test_finite_number_excludes_booleans_and_out_of_float_range_integers():
    assert finite_number(0)
    assert not finite_number(True)
    assert not finite_number(10**400)


@given(st.dictionaries(TEXT, JSON, max_size=5))
def test_dictionary_order_has_no_effect(state):
    def reverse(value):
        if isinstance(value, dict):
            return {key: reverse(value[key]) for key in reversed(list(value))}
        if isinstance(value, list):
            return [reverse(part) for part in value]
        return value

    assert canonicalize(state) == canonicalize(reverse(state))


@given(JSON)
def test_snapshot_is_canonical_idempotent(value):
    cloned = snapshot(value)
    assert canonicalize(value) == canonicalize(cloned)
    assert canonicalize(cloned) == canonicalize(snapshot(cloned))


@given(st.integers(min_value=-(10**80), max_value=10**80))
def test_distinct_values_have_distinct_hashes(number):
    assert state_hash({"amount": number}) != state_hash({"amount": number + 1})
    assert state_hash(number) != state_hash(str(number))


@given(st.decimals(min_value=-100, max_value=100, places=4, allow_nan=False, allow_infinity=False))
def test_decimal_equivalence(number):
    assert state_hash(number) == state_hash(Decimal(str(number)))
    assert canonicalize(number) == canonicalize(snapshot(number))


@given(st.integers(min_value=-720, max_value=840))
def test_equivalent_timestamp_offsets(minutes):
    instant = datetime(2026, 10, 6, 12, 30, tzinfo=timezone.utc)
    other = instant.astimezone(timezone(timedelta(minutes=minutes)))
    assert state_hash(instant) == state_hash(other)
    assert state_hash(instant) == state_hash(other.isoformat())
