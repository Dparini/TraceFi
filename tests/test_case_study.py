from copy import deepcopy

import pytest

from tracefi import TraceFi
from tracefi.analysis import analyze, check_policy, replay
from tracefi.case_study import DATASET, LendingAgent, run_case_study, simulate
from tracefi.cli import main
from tracefi.evals import compare, evaluate, load_scenarios
from tracefi.hashing import state_hash
from tracefi.models import decision_state


def test_lending_investigation_end_to_end_and_replay():
    with TraceFi(db=":memory:") as collector:
        result = run_case_study(collector)
        record = collector.storage.get(result["trace_id"])
        assert record["proposal"]["protocol"] == "protocol_b"
        assert record["policy"]["approved"] is True
        assert record["policy"]["requested_exposure"] == 0.3
        assert record["simulation"]["success"] is True
        assert record["execution"]["status"] == "success"
        assert (
            record["outcome"]["pnl"] == sum(record["outcome"]["components_usdc"].values()) == -1821
        )
        report = analyze(record)
        assert [(finding["type"], finding["certainty"]) for finding in report["findings"]] == [
            ("RETRIEVAL_FAILURE", "likely")
        ]
        assert replay(record, LendingAgent("1"))["equal"]
        experiment = result["counterfactual"]
        assert experiment["decision_changed"]
        assert experiment["counterfactual"]["protocol"] == "protocol_a"
        assert experiment["counterfactual"]["amount"] == 20000
        state = decision_state(record)
        before = state_hash(state)
        assert check_policy(
            experiment["counterfactual"], state["portfolio"], state["policy_configuration"]
        )["approved"]
        assert state_hash(state) == before
        assert "liquidity_trend_24h" not in record["context"]["markets"]["protocol_b"]
        record["outcome"] = None
        assert analyze(record)["likely_failure_class"] == "RETRIEVAL_FAILURE"


def test_regression_metrics_use_same_inputs_and_separate_cost_tradeoffs():
    scenarios = load_scenarios(DATASET)
    before = deepcopy(scenarios)
    report = compare(LendingAgent("1"), LendingAgent("2"), scenarios)
    a, b = report["baseline"]["metrics"], report["candidate"]["metrics"]
    assert (
        a["valid_decisions"]
        == b["valid_decisions"]
        == a["consistent_decisions"]
        == b["consistent_decisions"]
        == 8
    )
    assert a["unsafe_proposals"] == 0 and b["unsafe_proposals"] == b["policy_rejections"] == 8
    assert a["proposed_transaction_cost_usdc"] == 596 and b["proposed_transaction_cost_usdc"] == 114
    assert a["average_maximum_protocol_exposure"] < b["average_maximum_protocol_exposure"]
    assert "proposed_transaction_cost_usdc" in [row["metric"] for row in report["improvements"]]
    assert "unsafe_proposals" in [row["metric"] for row in report["regressions"]]
    assert scenarios == before
    assert (
        main(
            [
                "eval",
                "--baseline",
                "lending-v1",
                "--candidate",
                "lending-v2",
                "--dataset",
                "lending",
                "--fail-on-regression",
            ]
        )
        == 1
    )
    assert (
        main(
            [
                "eval",
                "--baseline",
                "lending-v1",
                "--candidate",
                "lending-v2",
                "--dataset",
                "lending",
                "--regression-metric",
                "valid_decisions",
                "--fail-on-regression",
            ]
        )
        == 0
    )


def test_eval_mutating_and_nondeterministic_adapters():
    scenario = {
        "id": "same",
        "state": {"portfolio": {"USDC": 100}, "policy_configuration": {"max_exposure": 0.35}},
    }

    class Mutator:
        def decide(self, state):
            state["portfolio"]["USDC"] = 1_000_000
            return {"action": "SUPPLY", "asset": "USDC", "amount": 100}

    assert evaluate(Mutator(), [scenario])["metrics"]["unsafe_proposals"] == 1
    assert scenario["state"]["portfolio"]["USDC"] == 100

    class Alternating:
        calls = 0

        def decide(self, state):
            self.calls += 1
            return {"action": "HOLD", "asset": "USDC", "amount": 0, "rationale": str(self.calls)}

    assert evaluate(Alternating(), [scenario])["metrics"]["consistent_decisions"] == 0

    class Broken:
        def decide(self, state):
            raise RuntimeError("SECRET_SENTINEL")

    report = evaluate(Broken(), [scenario, scenario])
    assert len(report["results"]) == report["metrics"]["failed_scenarios"] == 2
    assert "SECRET_SENTINEL" not in str(report)


@pytest.mark.parametrize(
    "positions,nav,amount,approved",
    [
        ({"A": 10000}, 100000, 25000, True),
        ({"A": 10001}, 100000, 25000, False),
        ({"A": True}, 100000, 1, False),
        ({"A": 0}, 0, 0, False),
        ({"A": -1}, 100000, 1, False),
        ([], 100000, 1, False),
        ({"A": 90000}, 100000, 1, False),
    ],
)
def test_existing_exposure_policy(positions, nav, amount, approved):
    proposal = {"action": "SUPPLY", "asset": "USDC", "protocol": "A", "amount": amount}
    result = check_policy(
        proposal,
        {"USDC": 80000, "positions": positions, "total_value_usdc": nav},
        {"exposure_basis": "total_portfolio", "max_exposure": 0.35},
    )
    assert result["approved"] is approved


def test_simulation_refuses_unfunded_transaction_costs():
    scenario = load_scenarios(DATASET)[0]
    state = deepcopy(scenario["state"])
    proposal = {"action": "SUPPLY", "asset": "USDC", "protocol": "protocol_a", "amount": 80000}
    assert simulate(proposal, state)["success"] is False


def test_lending_metrics_and_simulator_reject_unmodeled_asset_units():
    from tracefi.case_study import assess

    state = load_scenarios(DATASET)[0]["state"]
    for action in ("assess", "simulate"):
        function = assess if action == "assess" else simulate
        with pytest.raises(ValueError):
            function(
                {"action": "SUPPLY", "asset": "ETH", "protocol": "protocol_a", "amount": 1}, state
            )


@pytest.mark.parametrize("amount,approved", [(5000, True), (5001, False)])
def test_lending_withdrawal_position_bounds(amount, approved):
    assert (
        check_policy(
            {"action": "WITHDRAW", "asset": "USDC", "protocol": "A", "amount": amount},
            {"USDC": 95000, "total_value_usdc": 100000, "positions": {"A": 5000}},
            {"exposure_basis": "total_portfolio", "max_exposure": 0.35},
        )["approved"]
        is approved
    )


def test_empty_fault_override_is_preserved_for_investigation():
    from tracefi.evals import run_scenarios
    from tracefi.models import load_adapter

    scenarios = [
        {
            "id": "empty-proposal",
            "state": {"context": {}, "portfolio": {"USDC": 100000}},
            "proposal_override": {},
        }
    ]
    with TraceFi(db=":memory:") as collector:
        ids = run_scenarios(collector, load_adapter("deterministic"), scenarios)
        record = collector.storage.get(ids[0])
        assert record["proposal"] == {}
        assert analyze(record)["likely_failure_class"] == "REASONING_FAILURE"
        assert record["policy"]["approved"] is False
        assert record["execution"]["status"] == "blocked"
