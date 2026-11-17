from copy import deepcopy

import pytest

from tracefi import TraceFi
from tracefi.analysis import analyze
from tracefi.case_study import DATASET, LendingAgent, LendingMetrics, simulate
from tracefi.cli import main
from tracefi.counterfactual import replay
from tracefi.demo import run_case_study
from tracefi.evals import compare, load_scenarios
from tracefi.hashing import state_hash
from tracefi.policy import check_policy
from tracefi.registry import METRICS_MODELS
from tracefi.schema import decision_state


def test_lending_investigation_end_to_end_and_replay():
    with TraceFi(db=":memory:") as collector:
        result = run_case_study(collector)
        record = collector.storage.get(result["trace_id"])
    assert record["proposal"]["protocol"] == "protocol_b"
    assert record["policy"]["approved"] is True
    assert record["policy"]["requested_exposure"] == 0.3
    assert record["simulation"]["success"] is True
    assert record["execution"]["status"] == "success"
    assert record["outcome"]["pnl"] == sum(record["outcome"]["components_usdc"].values()) == -1821
    assert record["retrieval"]["required_features"] == ["markets.protocol_b.liquidity_trend_24h"]
    assert "liquidity_trend_24h" not in record["context"]["markets"]["protocol_b"]
    report = analyze(record)
    assert [(f["type"], f["certainty"]) for f in report["findings"]] == [
        ("RETRIEVAL_FAILURE", "likely")
    ]
    assert replay(record, LendingAgent("1"))["equal"]
    experiment = result["counterfactual"]
    assert experiment["feature"] == "context.markets.protocol_b.liquidity_trend_24h"
    assert experiment["value"] == -0.41
    assert experiment["decision_changed"]
    assert experiment["counterfactual"]["protocol"] == "protocol_a"
    assert experiment["counterfactual"]["amount"] == 20000
    state = decision_state(record)
    before = state_hash(state)
    assert check_policy(
        experiment["counterfactual"], state["portfolio"], state["policy_configuration"]
    )["approved"]
    assert state_hash(state) == before
    record["outcome"] = None
    assert analyze(record)["likely_failure_class"] == "RETRIEVAL_FAILURE"


def test_lending_agent_declares_every_recorded_market_input():
    state = load_scenarios(DATASET)[0]["state"]
    inputs = LendingAgent("1").inputs(state)
    assert inputs["context.markets.protocol_b.liquidity_trend_24h"] is True
    assert inputs["context.markets.protocol_a.supply_apy"] is False
    assert len(inputs) == 5 * len(state["context"]["markets"])
    assert LendingAgent("1").inputs({"context": {}}) == {}


def test_regression_metrics_use_same_inputs_and_separate_cost_tradeoffs():
    scenarios = load_scenarios(DATASET)
    before = deepcopy(scenarios)
    report = compare(LendingAgent("1"), LendingAgent("2"), scenarios, metrics_models=METRICS_MODELS)
    a, b = report["baseline"]["metrics"], report["candidate"]["metrics"]
    assert a["financial_metrics_scenarios"] == b["financial_metrics_scenarios"] == 8
    assert (
        a["valid_decisions"]
        == b["valid_decisions"]
        == a["consistent_decisions"]
        == b["consistent_decisions"]
        == 8
    )
    assert a["unsafe_proposals"] == 0 and b["unsafe_proposals"] == 8
    assert a["proposed_transaction_cost_usdc"] == 596 and b["proposed_transaction_cost_usdc"] == 114
    assert a["average_maximum_protocol_exposure"] < b["average_maximum_protocol_exposure"]
    assert "proposed_transaction_cost_usdc" in [row["metric"] for row in report["improvements"]]
    assert "unsafe_proposals" in [row["metric"] for row in report["regressions"]]
    assert scenarios == before


@pytest.mark.parametrize("extra,code", [([], 1), (["--regression-metric", "valid_decisions"], 0)])
def test_cli_lending_eval_gates(extra, code):
    arguments = ["eval", "--baseline", "lending-v1", "--candidate", "lending-v2"]
    assert main([*arguments, "--dataset", "lending", *extra, "--fail-on-regression"]) == code


def test_simulation_refuses_unfunded_transaction_costs():
    state = deepcopy(load_scenarios(DATASET)[0]["state"])
    proposal = {"action": "SUPPLY", "asset": "USDC", "protocol": "protocol_a", "amount": 80000}
    assert simulate(proposal, state)["success"] is False


@pytest.mark.parametrize("function", [LendingMetrics().assess, simulate])
def test_lending_metrics_and_simulator_reject_unmodeled_asset_units(function):
    state = load_scenarios(DATASET)[0]["state"]
    with pytest.raises(ValueError):
        function({"action": "SUPPLY", "asset": "ETH", "protocol": "protocol_a", "amount": 1}, state)
