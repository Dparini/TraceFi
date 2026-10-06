"""Property tests cover invariants, not examples of the implementation."""

import os
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.helpers import make_trace
from tracefi import TraceFi
from tracefi.analysis import analyze, check_policy, replay
from tracefi.counterfactual import counterfactual
from tracefi.hashing import canonicalize, snapshot, state_hash
from tracefi.models import decision_state, load_adapter
from tracefi.security import REDACTED, Redactor, Secret

settings.register_profile("ci", max_examples=200, deadline=None, derandomize=True, database=None)
settings.register_profile(
    "stress", max_examples=2000, deadline=None, derandomize=True, database=None
)
settings.register_profile(
    "mutation", max_examples=40, deadline=None, derandomize=True, database=None
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
TEXT = st.text(st.characters(exclude_categories=("Cs",)), max_size=30)
SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**100), max_value=10**100),
    st.floats(allow_nan=False, allow_infinity=False),
    TEXT,
)
JSON = st.recursive(
    SCALARS,
    lambda child: st.one_of(st.lists(child, max_size=5), st.dictionaries(TEXT, child, max_size=5)),
    max_leaves=20,
)
OBJECTS = st.dictionaries(TEXT, JSON, max_size=5)


class Properties(unittest.TestCase):
    @given(OBJECTS)
    def test_dictionary_order_has_no_effect(self, state):
        def reverse(value):
            if isinstance(value, dict):
                return {key: reverse(value[key]) for key in reversed(list(value))}
            if isinstance(value, list):
                return [reverse(part) for part in value]
            return value

        self.assertEqual(canonicalize(state), canonicalize(reverse(state)))

    @given(JSON)
    def test_snapshot_is_canonical_idempotent(self, value):
        cloned = snapshot(value)
        self.assertEqual(canonicalize(value), canonicalize(cloned))
        self.assertEqual(canonicalize(cloned), canonicalize(snapshot(cloned)))

    @given(st.integers(min_value=-(10**80), max_value=10**80))
    def test_distinct_values_have_distinct_hashes(self, number):
        self.assertNotEqual(state_hash({"amount": number}), state_hash({"amount": number + 1}))
        self.assertNotEqual(state_hash(number), state_hash(str(number)))

    @given(
        st.decimals(min_value=-100, max_value=100, places=4, allow_nan=False, allow_infinity=False)
    )
    def test_decimal_equivalence(self, number):
        self.assertEqual(state_hash(number), state_hash(Decimal(str(number))))
        self.assertEqual(canonicalize(number), canonicalize(snapshot(number)))

    @given(st.integers(min_value=-720, max_value=840))
    def test_equivalent_timestamp_offsets(self, minutes):
        instant = datetime(2026, 10, 6, 12, 30, tzinfo=timezone.utc)
        other = instant.astimezone(timezone(timedelta(minutes=minutes)))
        self.assertEqual(state_hash(instant), state_hash(other))
        self.assertEqual(state_hash(instant), state_hash(other.isoformat()))

    @given(JSON)
    def test_redaction_is_recursive_idempotent_and_nonmutating(self, value):
        payload = {
            "safe": deepcopy(value),
            "nested": [{"PRIVATE-KEY": "KEY_SENTINEL"}],
            "Authorization": "AUTH_SENTINEL",
            "wrapped": Secret("WRAPPED_SENTINEL"),
        }
        redactor = Redactor()
        cleaned = redactor(payload)
        self.assertEqual(cleaned, redactor(cleaned))
        self.assertEqual(payload["safe"], value)
        self.assertEqual(payload["nested"][0]["PRIVATE-KEY"], "KEY_SENTINEL")
        self.assertNotIn(b"KEY_SENTINEL", canonicalize(cleaned))
        self.assertNotIn(b"AUTH_SENTINEL", canonicalize(cleaned))
        self.assertNotIn(b"WRAPPED_SENTINEL", canonicalize(cleaned))

    @given(
        st.sampled_from(["api_key", "API-KEY", "Private_Key", "AUTHORIZATION", "refresh-token"]),
        JSON,
    )
    def test_secret_key_values_never_enter_storage_or_export(self, key, value):
        with TraceFi(db=":memory:") as collector:
            with collector.decision("property-agent") as trace:
                trace.capture_context(
                    {"level": [{key: {"sentinel": "PERSIST_SENTINEL", "data": value}}]}
                )
            stored = collector.storage.get(trace.trace_id)
            self.assertEqual(stored["context"]["level"][0][key], REDACTED)
            for table in ("traces", "spans", "artifacts"):
                for (raw,) in collector.storage.connection.execute(f"SELECT payload FROM {table}"):
                    self.assertNotIn("PERSIST_SENTINEL", raw)

    @given(
        st.floats(min_value=0, max_value=0.2, allow_nan=False),
        st.integers(min_value=0, max_value=100_000_000),
    )
    def test_replay_and_irrelevant_counterfactual_preserve_state(self, apy, liquidity):
        trace = make_trace({"apy": apy, "liquidity": liquidity})
        before = canonicalize(trace)
        adapter = load_adapter("deterministic")
        self.assertTrue(replay(trace, adapter)["equal"])
        self.assertFalse(counterfactual(trace, adapter, "context.unused", 42)["decision_changed"])
        self.assertEqual(before, canonicalize(trace))
        self.assertEqual(trace["context"], decision_state(trace)["context"])

    @given(JSON, JSON, JSON)
    def test_policy_never_throws_or_emits_nonfinite_numbers(self, proposal, portfolio, config):
        result = check_policy(proposal, portfolio, config)
        snapshot(result)
        if not isinstance(proposal, dict):
            self.assertFalse(result["approved"])

    @given(
        st.sampled_from(
            [
                "context",
                "portfolio",
                "retrieval",
                "proposal",
                "policy",
                "simulation",
                "execution",
                "outcome",
            ]
        ),
        JSON,
    )
    def test_attribution_handles_arbitrary_json_sections_without_mutation(self, field, value):
        trace = make_trace()
        trace[field] = value
        before = canonicalize(trace)
        report = analyze(trace)
        snapshot(report)
        self.assertEqual(before, canonicalize(trace))
        if value is not None and not isinstance(value, dict):
            self.assertTrue(report["input_errors"])
            self.assertNotEqual(report["likely_failure_class"], "MARKET_OUTCOME")
