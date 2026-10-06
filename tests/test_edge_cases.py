import math
import sqlite3
import unittest
from copy import deepcopy
from decimal import Decimal

from tests.helpers import make_trace
from tracefi import TraceFi
from tracefi.analysis import analyze, check_policy, replay
from tracefi.counterfactual import boundary, counterfactual, set_path, why_change
from tracefi.hashing import (
    MAX_BYTES,
    MAX_DEPTH,
    MAX_NODES,
    canonicalize,
    load_json,
    snapshot,
    state_hash,
)
from tracefi.models import load_adapter
from tracefi.models.deterministic import finite_number
from tracefi.security import Redactor, Secret
from tracefi.storage import IntegrityError


class HashingEdges(unittest.TestCase):
    def test_golden_bytes_and_value_types(self):
        self.assertEqual(
            canonicalize({"é": [True, None, -0.0, 1.0, Decimal("0.10")], "a": "x\n"}),
            '{"a":"x\\n","é":[true,null,0,1,0.1]}'.encode(),
        )
        self.assertNotEqual(state_hash(False), state_hash(0))
        self.assertNotEqual(state_hash("é"), state_hash("e\u0301"))
        self.assertNotEqual(state_hash([1, 2]), state_hash([2, 1]))

    def test_precision_is_never_silently_lost(self):
        for value in (Decimal("1.0000000000000000001"), Decimal("1e-400")):
            with self.assertRaises(ValueError):
                snapshot(value)
        with self.assertRaises(ValueError):
            load_json('{"price":1.0000000000000000001}')
        self.assertEqual(snapshot(Decimal("0.10")), 0.1)

    def test_timestamp_precision_and_invalid_dates(self):
        for value in (
            "2026-10-06T10:00:00.1234567Z",
            "2026-10-06T10:00:00.1234568Z",
            "2026-02-30T10:00:00Z",
            "2026-10-06T10:00:00+25:00",
        ):
            with self.assertRaises(ValueError):
                canonicalize(value)
        self.assertEqual(
            canonicalize("2026-10-06T10:00:00.123456000Z"),
            canonicalize("2026-10-06T10:00:00.123456Z"),
        )
        self.assertEqual(snapshot("2026-10-06T10:00:00"), "2026-10-06T10:00:00")

    def test_nonfinite_unsupported_and_surrogate_values(self):
        for value in (float("nan"), float("inf"), Decimal("NaN"), Decimal("Infinity"), "\ud800"):
            with self.assertRaises(ValueError):
                canonicalize(value)
        for value in ({1: "key"}, b"bytes", {1, 2}, object()):
            with self.assertRaises(TypeError):
                canonicalize(value)
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', "1e1000000000"):
            with self.assertRaises(ValueError):
                load_json(raw)

    def test_cycles_depth_size_and_decimal_exponents(self):
        cyclic = []
        cyclic.append(cyclic)
        with self.assertRaises(ValueError):
            canonicalize(cyclic)
        value = 0
        for _ in range(MAX_DEPTH + 1):
            value = [value]
        with self.assertRaises(ValueError):
            canonicalize(value)
        with self.assertRaises(ValueError):
            canonicalize([0] * MAX_NODES)
        with self.assertRaises(ValueError):
            canonicalize("x" * MAX_BYTES)
        with self.assertRaises(ValueError):
            load_json(" " * (MAX_BYTES + 1))
        for number in (Decimal("1e1000000000"), Decimal("1e-1000000000")):
            with self.assertRaises(ValueError):
                canonicalize(number)
        shared = [1]
        self.assertEqual(snapshot([shared, shared]), [[1], [1]])


class RedactionReplayEdges(unittest.TestCase):
    def test_custom_reserved_invalid_and_cyclic_redaction(self):
        self.assertEqual(
            Redactor(["credential"])([{"CrEdEnTiAl": Secret("x")}]), [{"CrEdEnTiAl": "[REDACTED]"}]
        )
        for keys in ("api_key", [None], [""], [123]):
            with self.assertRaises(TypeError):
                Redactor(keys)
        for key in ("context", "context_hash", "Trace-ID", "redaction_keys", "parent_id"):
            with self.assertRaises(ValueError):
                Redactor([key])
        value = {}
        value["self"] = value
        with self.assertRaises(ValueError):
            Redactor()(value)
        self.assertEqual(repr(Secret("SENTINEL")), "[REDACTED]")
        self.assertEqual(Secret("SENTINEL").reveal(), "SENTINEL")

    def test_replay_markers_and_report_aliases(self):
        trace = make_trace({"note": "The label [REDACTED] is text", "[REDACTED]": "key"})
        report = replay(trace, load_adapter("deterministic"))
        self.assertTrue(report["equal"])
        report["original"]["amount"] = 99
        report["agent"]["name"] = "changed"
        self.assertEqual(trace["proposal"]["amount"], 25000)
        self.assertEqual(trace["agent"]["name"], "rule-agent")
        trace["context"]["note"] = "[REDACTED]"
        with self.assertRaises(ValueError):
            replay(trace, load_adapter("deterministic"))

    def test_replay_missing_state_and_malformed_outputs(self):
        for field in ("context", "portfolio", "agent_configuration", "policy_configuration"):
            trace = make_trace()
            del trace[field]
            with self.assertRaises(ValueError):
                replay(trace, load_adapter("deterministic"))
        for output in (None, [], "HOLD", {"amount": float("inf")}):

            class BadAdapter:
                def decide(self, state, chosen=output):
                    return chosen

            with self.assertRaises((TypeError, ValueError)):
                replay(make_trace(), BadAdapter())
        trace = make_trace()
        trace["proposal"] = None
        with self.assertRaises(ValueError):
            replay(trace, load_adapter("deterministic"))


class CounterfactualEdges(unittest.TestCase):
    def test_invalid_paths_limits_and_nonfinite_values(self):
        trace, adapter = make_trace(), load_adapter("deterministic")
        for path in (
            "",
            "context",
            "context..apy",
            ".apy",
            "metadata.apy",
            "context.missing.value",
            "context.apy.value",
        ):
            with self.assertRaises(ValueError):
                counterfactual(trace, adapter, path, 1)
        for low, high in (
            (1, 1),
            (2, 1),
            (float("nan"), 2),
            (0, float("inf")),
            (True, 2),
            (0, 10**400),
        ):
            with self.assertRaises(ValueError):
                boundary(trace, adapter, "context.apy", low, high)
        for count in (0, 61, 1.5, True, "2"):
            with self.assertRaises(ValueError):
                boundary(trace, adapter, "context.apy", 0, 1, count)
        for value in (float("nan"), float("inf"), Secret("SENSITIVE")):
            with self.assertRaises((ValueError, TypeError)):
                counterfactual(trace, adapter, "context.apy", value)
        with self.assertRaises(ValueError):
            counterfactual(trace, adapter, "context.private_key", "SENSITIVE")

    def test_nondeterministic_baselines_and_candidate_outputs_are_refused(self):
        original = make_trace()

        class Alternating:
            calls = 0

            def decide(self, state):
                self.calls += 1
                return (
                    original["proposal"]
                    if self.calls % 2
                    else {"action": "HOLD", "asset": "USDC", "amount": 0}
                )

        with self.assertRaises(ValueError):
            counterfactual(original, Alternating(), "context.liquidity", 1)

        class UnstableIntervention:
            calls = 0

            def decide(self, state):
                if state["context"]["liquidity"] == 21000000:
                    return original["proposal"]
                self.calls += 1
                return {"action": "HOLD", "asset": "USDC", "amount": self.calls}

        with self.assertRaises(ValueError):
            counterfactual(original, UnstableIntervention(), "context.liquidity", 1)

    def test_boolean_amount_does_not_equal_numeric_amount(self):
        class TypeAdapter:
            def decide(self, state):
                return {"action": "HOLD", "asset": "USDC", "amount": state["context"]["value"]}

        trace = make_trace({"value": False}, TypeAdapter())
        self.assertTrue(
            counterfactual(trace, TypeAdapter(), "context.value", 0)["decision_changed"]
        )

    def test_mutating_adapter_and_input_cannot_mutate_original(self):
        class Mutating:
            def decide(self, state):
                state["context"].pop("unused", None)
                return {"action": "HOLD", "asset": "USDC", "amount": 0}

        trace = make_trace(adapter=Mutating())
        before = deepcopy(trace)
        value = {"items": [1]}
        counterfactual(trace, Mutating(), "context.unused", value)
        self.assertEqual(value, {"items": [1]})
        self.assertEqual(trace, before)
        set_path(trace, "context.extra", value)
        trace["context"]["extra"]["items"].append(2)
        self.assertEqual(value, {"items": [1]})

    def test_boundary_equal_endpoints_third_outcome_and_float_resolution(self):
        class ThreeOutcomes:
            def decide(self, state):
                x = state["context"]["x"]
                return {
                    "action": "HOLD" if x < 0 else "SUPPLY" if x < 1 else "WITHDRAW",
                    "asset": "USDC",
                    "amount": 0,
                }

        trace = make_trace({"x": -1}, ThreeOutcomes())
        with self.assertRaises(ValueError):
            boundary(trace, ThreeOutcomes(), "context.x", -1, 2)

        class Threshold:
            def decide(self, state):
                return {
                    "action": "HOLD" if state["context"]["x"] < 10**308 else "SUPPLY",
                    "asset": "USDC",
                    "amount": 0,
                }

        trace = make_trace({"x": 0}, Threshold())
        result = boundary(trace, Threshold(), "context.x", 9e307, 1.1e308)
        self.assertLessEqual(result["interval"][0], 1e308)
        self.assertGreaterEqual(result["interval"][1], 1e308)
        self.assertTrue(all(math.isfinite(n) for n in result["interval"]))
        result = boundary(trace, Threshold(), "context.x", 1e308 - 1e292, 1e308, 60)
        self.assertTrue(result["boundary_found"])
        equal = boundary(make_trace(), load_adapter("deterministic"), "context.liquidity", 1, 2)
        self.assertFalse(equal["boundary_found"])
        self.assertIn("do not exclude", equal["limitations"])

    def test_why_change_identical_interactions_and_multiple_drivers(self):
        class Logic:
            def __init__(self, operation):
                self.operation = operation

            def decide(self, state):
                x, y = state["context"].get("x", 0), state["context"].get("y", 0)
                active = x and y if self.operation == "and" else x or y
                return {
                    "action": "SUPPLY" if active else "HOLD",
                    "asset": "USDC",
                    "amount": 1 if active else 0,
                }

        for mode, sufficient in (("and", []), ("or", ["context.x", "context.y"])):
            adapter = Logic(mode)
            a, b = make_trace({"x": 0, "y": 0}, adapter), make_trace({"x": 1, "y": 1}, adapter)
            report = why_change(a, b, adapter)
            self.assertIsNone(report["primary_decision_driver"])
            self.assertEqual(report["sufficient_single_changes"], sufficient)
            self.assertEqual(why_change(a, a, adapter)["experiments"], [])
        a = make_trace({"a.b": 1})
        b = make_trace({"a.b": 2})
        with self.assertRaises(ValueError):
            why_change(a, b, load_adapter("deterministic"))
        a, b = make_trace({"unused": [1]}), make_trace({"unused": [2]})
        self.assertFalse(
            why_change(a, b, load_adapter("deterministic"))["experiments"][0]["decision_changed"]
        )
        a = make_trace({"unused": None})
        b = make_trace()
        self.assertFalse(
            why_change(a, b, load_adapter("deterministic"))["experiments"][0]["after_present"]
        )


class AttributionEdges(unittest.TestCase):
    def test_negative_outcome_requires_valid_complete_observations(self):
        for field, invalid in (
            ("context", {}),
            ("portfolio", {}),
            ("retrieval", []),
            ("policy", {"approved": "true"}),
            ("proposal", {}),
            ("execution", {"status": "success", "success": False}),
            ("simulation", {"success": "true"}),
        ):
            trace = make_trace()
            trace["outcome"] = {"pnl": -1}
            trace[field] = invalid
            self.assertNotEqual(analyze(trace)["likely_failure_class"], "MARKET_OUTCOME")

    def test_policy_boundaries_invalid_assets_and_extreme_ratios(self):
        self.assertFalse(finite_number(10**400))
        self.assertFalse(finite_number(True))
        self.assertTrue(finite_number(0))
        for asset in ([], {}, 123, None):
            self.assertFalse(
                check_policy({"action": "SUPPLY", "amount": 1, "asset": asset}, {"USDC": 100}, {})[
                    "approved"
                ]
            )
        self.assertTrue(
            check_policy(
                {"action": "SUPPLY", "amount": 35, "asset": "USDC"},
                {"USDC": 100},
                {"max_exposure": 0.35},
            )["approved"]
        )
        self.assertFalse(
            check_policy(
                {"action": "SUPPLY", "amount": 36, "asset": "USDC"},
                {"USDC": 100},
                {"max_exposure": 0.35},
            )["approved"]
        )
        huge = check_policy(
            {"action": "SUPPLY", "amount": 1e308, "asset": "USDC"}, {"USDC": 1e-308}, {}
        )
        self.assertFalse(huge["approved"])
        self.assertIsNone(huge["requested_exposure"])
        self.assertFalse(
            check_policy({"action": "HOLD", "amount": 1, "asset": "USDC"}, {"USDC": 100}, {})[
                "approved"
            ]
        )

    def test_multiple_findings_priority_and_malformed_retrieval(self):
        trace = make_trace({"oracle_age_seconds": 301})
        trace["proposal"]["amount"] = 80000
        trace["policy"] = {"approved": True, "should_reject": True}
        trace["simulation"] = {"success": True, "predicted_effect": 1}
        trace["execution"] = {"status": "success", "actual_effect": 2}
        report = analyze(trace)
        self.assertEqual(report["likely_failure_class"], "POLICY_FAILURE")
        self.assertTrue(
            {"DATA_FAILURE", "POLICY_FAILURE", "SIMULATION_FAILURE"}
            <= {f["type"] for f in report["findings"]}
        )
        trace["retrieval"] = {"available_features": [{}], "untrusted_data": "not-a-list"}
        self.assertTrue(analyze(trace)["input_errors"])

    def test_attribution_stress_grid(self):
        base = make_trace()
        # 2,000 independently corrupted observations, deterministic and offline.
        values = [
            None,
            [],
            "bad",
            False,
            0,
            {},
            {"success": "true"},
            {"available_features": [None]},
            {"amount": -1},
            {"status": "blocked", "success": True},
        ]
        stages = [
            "context",
            "portfolio",
            "retrieval",
            "proposal",
            "policy",
            "simulation",
            "execution",
            "outcome",
        ]
        for iteration in range(2000):
            trace = deepcopy(base)
            trace[stages[iteration % len(stages)]] = values[
                (iteration // len(stages)) % len(values)
            ]
            report = analyze(trace)
            snapshot(report)


class StorageLifecycleEdges(unittest.TestCase):
    def test_reusing_or_leaving_spans_open_is_rejected(self):
        with TraceFi(db=":memory:") as collector:
            with collector.decision("span-test") as trace:
                span = trace.span("once")
                with span:
                    span.log({"records": 1})
                with self.assertRaises(RuntimeError):
                    span.__enter__()
                with self.assertRaises(RuntimeError):
                    span.log({})
            with self.assertRaises(RuntimeError):
                trace.__enter__()
            with self.assertRaises(RuntimeError):
                trace.__exit__(None, None, None)
            bad = collector.decision("unfinished")
            with self.assertRaises(RuntimeError):
                with bad:
                    bad.span("open").__enter__()
            self.assertFalse(bad.active)
            self.assertTrue(bad.finished)
            self.assertEqual(len(collector.storage.list()), 1)

    def test_save_failure_deactivates_trace_and_atomic_rollback(self):
        with TraceFi(db=":memory:") as collector:
            trace = make_trace()
            trace["spans"].append(deepcopy(trace["spans"][0]))
            with self.assertRaises(sqlite3.IntegrityError):
                collector.storage.save(trace)
            self.assertEqual(collector.storage.list(), [])
            t = collector.decision("corrupt")
            with self.assertRaises(ValueError):
                with t:
                    t.record["cycle"] = t.record
            self.assertFalse(t.active)
            self.assertTrue(t.finished)

    def test_bool_numeric_substitution_in_auxiliary_rows_is_detected(self):
        with TraceFi(db=":memory:") as collector:
            with collector.decision("integrity") as trace:
                trace.capture_context({"flag": 1})
            db = collector.storage.connection
            artifact_id = trace.trace_id + ":context"
            db.execute(
                "UPDATE artifacts SET payload=?,hash=? WHERE id=?",
                ('{"flag":true}', state_hash({"flag": True}), artifact_id),
            )
            with self.assertRaises(IntegrityError):
                collector.storage.get(trace.trace_id)
        with TraceFi(db=":memory:") as collector:
            with collector.decision("integrity") as trace:
                trace.capture_context({"flag": 1})
            span = deepcopy(trace.record["spans"][0])
            span["events"][0]["payload"]["flag"] = True
            collector.storage.connection.execute(
                "UPDATE spans SET payload=? WHERE id=?", (canonicalize(span).decode(), span["id"])
            )
            with self.assertRaises(IntegrityError):
                collector.storage.get(trace.trace_id)

    def test_malformed_rows_and_invalid_limits(self):
        with TraceFi(db=":memory:") as collector:
            with collector.decision("row") as trace:
                trace.capture_context({})
            for raw in ("null", "[]", "{", '{"x":1,"x":2}'):
                collector.storage.connection.execute(
                    "UPDATE traces SET payload=? WHERE id=?", (raw, trace.trace_id)
                )
                with self.assertRaises(IntegrityError):
                    collector.storage.get()
            for limit in (0, -1, 1001, True, 1.5):
                with self.assertRaises(ValueError):
                    collector.storage.list(limit)
        for field in ("portfolio", "agent_config", "policy_config"):
            with TraceFi(db=":memory:") as collector:
                with self.assertRaises(TypeError):
                    collector.decision("invalid", **{field: []})
