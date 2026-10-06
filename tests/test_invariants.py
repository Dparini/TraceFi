import json
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from agenttrace import AgentTrace, FailureType
from agenttrace.analysis import analyze, replay, check_policy, diff
from agenttrace.counterfactual import counterfactual, boundary, why_change
from agenttrace.demo import run_demo
from agenttrace.evals import compare, load_scenarios
from agenttrace.hashing import canonicalize, state_hash
from agenttrace.models import decision_state, load_adapter
from agenttrace.storage import IntegrityError
from agenttrace.cli.render import export_html


class HashingTests(unittest.TestCase):
    def test_order_and_numbers(self):
        self.assertEqual(state_hash({"b": 1., "a": [Decimal("1.00"), -0.]}),
                         state_hash({"a": [1, 0], "b": 1}))
        self.assertNotEqual(state_hash({"a": 1}), state_hash({"a": 2}))
        self.assertNotEqual(state_hash(True), state_hash(1))

    def test_timestamps(self):
        self.assertEqual(canonicalize("2026-10-06T12:00:00+02:00"), canonicalize("2026-10-06T10:00:00Z"))
        self.assertEqual(canonicalize(datetime(2026, 10, 6, 10, tzinfo=timezone.utc)), canonicalize("2026-10-06T10:00:00Z"))
        with self.assertRaises(ValueError):
            canonicalize(datetime(2026, 10, 6))

    def test_timestamp_object_keys_are_not_normalized(self):
        state = {"2026-10-06T12:00:00+02:00": 1, "2026-10-06T10:00:00Z": 2}
        self.assertEqual(json.loads(canonicalize(state)), state)

    def test_reject_non_json(self):
        for value in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                canonicalize(value)
        with self.assertRaises(TypeError):
            canonicalize({1: "bad"})


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "traces.sqlite3"
        self.collector = AgentTrace(db=self.path)

    def tearDown(self):
        self.collector.close()
        self.temp.cleanup()

    def capture(self, **kwargs):
        with self.collector.decision("rule-agent", "1", portfolio={"USDC": 100000},
                                     agent_config={"version": "1"}, policy_config={"max_exposure": .35}) as t:
            context = {"apy": .067, "liquidity": 21000000, "price": 1, "oracle_age_seconds": 20}
            context.update(kwargs)
            t.capture_context(context)
            proposal = load_adapter("deterministic").decide(decision_state(t.record))
            t.capture_decision(proposal)
            t.capture_policy(check_policy(proposal, t.record["portfolio"], t.record["policy_configuration"]))
            t.capture_simulation({"success": True})
            t.capture_execution({"status": "success"})
        return self.collector.storage.get(t.trace_id)

    def test_replay_and_snapshot(self):
        trace = self.capture()
        self.assertTrue(replay(trace, load_adapter("deterministic"))["equal"])
        with self.collector.decision("snapshot") as t:
            context = {"list": [1]}
            t.capture_context(context)
            context["list"].append(2)
        self.assertEqual(self.collector.storage.get(t.trace_id)["context"], {"list": [1]})

    def test_secrets_never_persisted(self):
        with self.collector.decision("secrets") as t:
            t.capture_context({"nested": {"Private-Key": "PRIVATE_SENTINEL"},
                               "items": [self.collector.secret("WRAPPED_SENTINEL")],
                               "api_key": "API_SENTINEL"})
            with t.span("tool") as span:
                span.log({"Authorization": "AUTH_SENTINEL"})
        raw = self.path.read_bytes()
        for sentinel in (b"PRIVATE_SENTINEL", b"WRAPPED_SENTINEL", b"API_SENTINEL", b"AUTH_SENTINEL"):
            self.assertNotIn(sentinel, raw)
        trace = self.collector.storage.get(t.trace_id)
        self.assertIn("[REDACTED]", json.dumps(trace))
        with self.assertRaises(ValueError):
            replay(trace, load_adapter("deterministic"))

    def test_exception_type_only_and_nested_spans(self):
        with self.assertRaises(RuntimeError):
            with self.collector.decision("failure") as t:
                with t.span("outer"):
                    with t.span("inner"):
                        raise RuntimeError("PRIVATE_EXCEPTION_SENTINEL")
        trace = self.collector.storage.get(t.trace_id)
        self.assertEqual(trace["status"], "error")
        self.assertEqual(trace["spans"][1]["parent_id"], trace["spans"][0]["id"])
        self.assertNotIn(b"PRIVATE_EXCEPTION_SENTINEL", self.path.read_bytes())

    def test_integrity_tampering(self):
        trace = self.capture()
        corrupt = json.loads(json.dumps(trace))
        corrupt["context"]["liquidity"] = 1
        self.collector.storage.connection.execute("UPDATE traces SET payload=? WHERE id=?", (json.dumps(corrupt), trace["trace_id"]))
        with self.assertRaises(IntegrityError):
            self.collector.storage.get(trace["trace_id"])

    def test_artifact_tampering(self):
        trace = self.capture()
        self.collector.storage.connection.execute("UPDATE artifacts SET payload='{}' WHERE trace_id=?", (trace["trace_id"],))
        with self.assertRaises(IntegrityError):
            self.collector.storage.get(trace["trace_id"])

    def test_span_tampering(self):
        trace = self.capture()
        self.collector.storage.connection.execute("DELETE FROM spans WHERE trace_id=?", (trace["trace_id"],))
        with self.assertRaises(IntegrityError):
            self.collector.storage.get(trace["trace_id"])

    def test_counterfactual_irrelevant_and_boundary(self):
        trace = self.capture()
        adapter = load_adapter("deterministic")
        self.assertFalse(counterfactual(trace, adapter, "context.unused", 42)["decision_changed"])
        found = boundary(trace, adapter, "context.liquidity", 1000000, 21000000)
        self.assertTrue(found["boundary_found"])
        self.assertLessEqual(found["interval"][0], 12400000)
        self.assertGreaterEqual(found["interval"][1], 12400000)
        self.assertLess(found["interval"][1] - found["interval"][0], 2)

    def test_why_change(self):
        ids = run_demo(self.collector)
        a, b = [self.collector.storage.get(item) for item in ids]
        self.assertEqual(why_change(a, b, load_adapter("deterministic"))["primary_decision_driver"], "context.liquidity")
        self.assertEqual(diff(a, b)["changed_inputs"][0]["path"], "context.liquidity")
        self.assertEqual(b["status"], "rejected")

    def test_no_false_market_failure(self):
        trace = self.capture()
        self.assertEqual(analyze(trace)["findings"], [])
        trace["outcome"] = {"pnl": -2341}
        report = analyze(trace)
        self.assertEqual(report["likely_failure_class"], FailureType.MARKET_OUTCOME.value)
        self.assertEqual(report["findings"][0]["certainty"], "likely")
        trace["simulation"] = None
        self.assertIsNone(analyze(trace)["likely_failure_class"])

    def test_policy_failure_and_retrieval(self):
        trace = self.capture()
        trace["proposal"]["amount"] = 80000
        trace["policy"] = {"approved": True, "should_reject": True}
        trace["retrieval"] = {"available_features": ["trend"], "included_features": [], "required_features": ["trend"]}
        types = {finding["type"] for finding in analyze(trace)["findings"]}
        self.assertIn("POLICY_FAILURE", types)
        self.assertIn("RETRIEVAL_FAILURE", types)

    def test_export_escapes_untrusted_html(self):
        trace = self.capture(protocol_name="<script>alert(1)</script>")
        exported = export_html(trace)
        self.assertNotIn("<script>alert(1)</script>", exported)
        self.assertIn("&lt;script&gt;", exported)

    def test_metadata_tampering_rejected_by_list(self):
        trace = self.capture()
        self.collector.storage.connection.execute("UPDATE traces SET status='failed' WHERE id=?", (trace["trace_id"],))
        with self.assertRaises(IntegrityError):
            self.collector.storage.list()

    def test_span_metadata_tampering(self):
        trace = self.capture()
        self.collector.storage.connection.execute("UPDATE spans SET type='forged' WHERE trace_id=?", (trace["trace_id"],))
        with self.assertRaises(IntegrityError):
            self.collector.storage.get(trace["trace_id"])

    def test_context_frozen_and_none_proposal_rejected(self):
        with self.collector.decision("frozen") as t:
            with self.assertRaises(TypeError):
                t.capture_decision(None)
            t.capture_context({"price": 1})
            t.capture_decision({"action": "HOLD", "amount": 0})
            with self.assertRaises(RuntimeError):
                t.capture_context({"price": 2})
            with self.assertRaises(RuntimeError):
                t.capture_decision({"action": "SUPPLY", "amount": 1})

    def test_scenario_fault_attribution(self):
        from agenttrace.evals import run_scenarios
        scenarios = load_scenarios(Path(__file__).parents[1] / "scenarios")
        ids = run_scenarios(self.collector, load_adapter("deterministic"), scenarios)
        reports = {scenario["id"]: analyze(self.collector.storage.get(trace_id))
                   for scenario, trace_id in zip(scenarios, ids)}
        for name, expected in (("stale_oracle", "DATA_FAILURE"),
                               ("liquidity_trend_omitted", "RETRIEVAL_FAILURE"),
                               ("policy_bypass", "POLICY_FAILURE"),
                               ("simulation_mismatch", "SIMULATION_FAILURE"),
                               ("transaction_revert", "EXECUTION_FAILURE"),
                               ("reasonable_loss", "MARKET_OUTCOME"),
                               ("prompt_injection", "ADVERSARIAL_INPUT")):
            self.assertEqual(reports[name]["likely_failure_class"], expected)
        self.assertNotIn(b"SYNTHETIC_SECRET_NEVER_PERSIST", self.path.read_bytes())

    def test_adapter_output_secrets_are_redacted(self):
        trace = self.capture()
        class LeakyAdapter:
            def decide(self, state):
                return {"action": "HOLD", "amount": 0, "private_key": "OUTPUT_SENTINEL"}
        report = replay(trace, LeakyAdapter())
        self.assertNotIn("OUTPUT_SENTINEL", json.dumps(report))
        self.assertEqual(report["replayed"]["private_key"], "[REDACTED]")

    def test_packaged_scenarios_match_repository(self):
        source = Path(__file__).parents[1] / "scenarios"
        packaged = Path(__file__).parents[1] / "agenttrace" / "datasets"
        self.assertEqual({str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*.json")},
                         {str(p.relative_to(packaged)): p.read_bytes() for p in packaged.rglob("*.json")})

    def test_regression_dataset(self):
        scenarios = load_scenarios(Path(__file__).parents[1] / "scenarios")
        self.assertEqual(len(scenarios), 30)
        report = compare(load_adapter("agent-v1"), load_adapter("agent-v2"), scenarios)
        self.assertEqual(report["baseline"]["metrics"]["valid_decisions"], 30)
        self.assertGreater(report["candidate"]["metrics"]["unsafe_proposals"], 0)
        self.assertIn("unsafe_proposals", [row["metric"] for row in report["regressions"]])


if __name__ == "__main__":
    unittest.main()
