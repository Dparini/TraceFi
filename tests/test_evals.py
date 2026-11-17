from pathlib import Path

import pytest

import tracefi.evals as evaluation
from tracefi import TraceFi
from tracefi.analysis import analyze
from tracefi.case_study import DATASET as LENDING_DATASET
from tracefi.demo import run_scenarios
from tracefi.evals import compare, evaluate, load_scenarios
from tracefi.registry import DEFAULT_DATASET, METRICS_MODELS, dataset_path, load_adapter

SCENARIO = {
    "id": "same",
    "state": {"portfolio": {"USDC": 100}, "policy_configuration": {"max_exposure": 0.35}},
}


def test_mutating_nondeterministic_and_failing_adapters():
    class Mutator:
        def decide(self, state):
            state["portfolio"]["USDC"] = 1_000_000
            return {"action": "SUPPLY", "asset": "USDC", "amount": 100}

    assert evaluate(Mutator(), [SCENARIO])["metrics"]["unsafe_proposals"] == 1
    assert SCENARIO["state"]["portfolio"]["USDC"] == 100

    class Alternating:
        calls = 0

        def decide(self, state):
            self.calls += 1
            return {"action": "HOLD", "asset": "USDC", "amount": 0, "rationale": str(self.calls)}

    assert evaluate(Alternating(), [SCENARIO])["metrics"]["consistent_decisions"] == 0

    class Broken:
        def decide(self, state):
            raise RuntimeError("SECRET_SENTINEL")

    report = evaluate(Broken(), [SCENARIO, SCENARIO])
    assert len(report["results"]) == report["metrics"]["failed_scenarios"] == 2
    assert "SECRET_SENTINEL" not in str(report)


def test_invalid_decisions_are_scored_not_failed():
    class InvalidAgent:
        def decide(self, state):
            return {"action": "HOLD", "amount": 12, "asset": []}

    report = evaluate(InvalidAgent(), [{"id": "bad", "state": {}}])
    assert report["metrics"]["valid_decisions"] == 0
    assert report["metrics"]["unsafe_proposals"] == 1
    lending = load_scenarios(LENDING_DATASET)
    report = evaluate(InvalidAgent(), lending, METRICS_MODELS)
    assert report["metrics"]["failed_scenarios"] == 0
    assert report["metrics"]["unsafe_proposals"] == len(lending)
    assert report["metrics"]["financial_metrics_scenarios"] == 0


def test_proposals_the_metrics_model_cannot_assess_keep_their_policy_result():
    class OtherProtocol:
        def decide(self, state):
            return {"action": "SUPPLY", "asset": "USDC", "protocol": "protocol_z", "amount": 1}

    lending = load_scenarios(LENDING_DATASET)
    report = evaluate(OtherProtocol(), lending, METRICS_MODELS)
    assert report["metrics"]["failed_scenarios"] == 0
    assert report["metrics"]["unsafe_proposals"] == len(lending)
    assert {row["financial_metrics_error"] for row in report["results"]} == {"KeyError"}


def test_unknown_metrics_model_is_refused():
    scenario = {**SCENARIO, "metrics_model": "misspelled"}
    with pytest.raises(ValueError, match="Unknown metrics model"):
        evaluate(load_adapter("deterministic"), [scenario], METRICS_MODELS)


def test_metrics_model_keys_are_reported_even_without_matching_scenarios():
    metrics = evaluate(load_adapter("deterministic"), [SCENARIO], METRICS_MODELS)["metrics"]
    assert metrics["financial_metrics_scenarios"] == 0
    assert metrics["average_maximum_protocol_exposure"] is None


def test_regression_dataset():
    scenarios = load_scenarios(DEFAULT_DATASET)
    assert len(scenarios) == 30
    report = compare(load_adapter("agent-v1"), load_adapter("agent-v2"), scenarios)
    assert report["baseline"]["metrics"]["valid_decisions"] == 30
    assert report["candidate"]["metrics"]["unsafe_proposals"] > 0
    assert "unsafe_proposals" in [row["metric"] for row in report["regressions"]]
    with pytest.raises(ValueError):
        compare(load_adapter("agent-v1"), load_adapter("agent-v2"), scenarios, ["unknown"])


def test_builtin_dataset_names():
    assert dataset_path("lending") == dataset_path("lending/") == LENDING_DATASET
    assert dataset_path("some/dir") == Path("some/dir")


def test_scenario_validation(tmp_path):
    for payload in ('{"state":{},"id":"a","id":"b"}', '{"state":{},"id":[]}', '{"state":[]}'):
        (tmp_path / "a.json").write_text(payload)
        with pytest.raises(ValueError):
            load_scenarios(tmp_path)


def test_dataset_resource_limits_and_symlinks(tmp_path, monkeypatch):
    for index in range(3):
        (tmp_path / f"{index}.json").write_text('{"state":{}}')
    monkeypatch.setattr(evaluation, "MAX_SCENARIOS", 2)
    with pytest.raises(ValueError, match="count limit"):
        load_scenarios(tmp_path)
    monkeypatch.setattr(evaluation, "MAX_SCENARIOS", 10)
    monkeypatch.setattr(evaluation, "MAX_DATASET_BYTES", 2)
    with pytest.raises(ValueError, match="byte limit"):
        load_scenarios(tmp_path)
    monkeypatch.setattr(evaluation, "MAX_DATASET_BYTES", 10000)
    (tmp_path / "link.json").symlink_to(tmp_path / "0.json")
    with pytest.raises(ValueError, match="symlinks"):
        load_scenarios(tmp_path)


def test_scenario_faults_are_attributed(tmp_path):
    scenarios = load_scenarios(DEFAULT_DATASET)
    path = tmp_path / "traces.sqlite3"
    with TraceFi(db=path) as collector:
        ids = run_scenarios(collector, load_adapter("deterministic"), "deterministic", scenarios)
        traces = {s["id"]: collector.storage.get(i) for s, i in zip(scenarios, ids, strict=True)}
    for name, expected in (
        ("stale_oracle", "DATA_FAILURE"),
        ("liquidity_trend_omitted", "RETRIEVAL_FAILURE"),
        ("policy_bypass", "POLICY_FAILURE"),
        ("simulation_mismatch", "SIMULATION_FAILURE"),
        ("transaction_revert", "EXECUTION_FAILURE"),
        ("reasonable_loss", "MARKET_OUTCOME"),
        ("prompt_injection", "ADVERSARIAL_INPUT"),
    ):
        assert analyze(traces[name])["likely_failure_class"] == expected
    assert {trace["agent"]["version"] for trace in traces.values()} == {"deterministic"}
    assert b"SYNTHETIC_SECRET_NEVER_PERSIST" not in path.read_bytes()


def test_empty_fault_override_is_preserved_for_investigation():
    scenarios = [
        {
            "id": "empty-proposal",
            "state": {"context": {}, "portfolio": {"USDC": 100000}},
            "proposal_override": {},
        }
    ]
    with TraceFi(db=":memory:") as collector:
        ids = run_scenarios(collector, load_adapter("deterministic"), "deterministic", scenarios)
        record = collector.storage.get(ids[0])
    assert record["proposal"] == {}
    assert analyze(record)["likely_failure_class"] == "REASONING_FAILURE"
    assert record["policy"]["approved"] is False
    assert record["execution"]["status"] == "blocked"
