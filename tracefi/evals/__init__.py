"""Offline scenario evaluation and comparable regression metrics."""

import math
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from tracefi.hashing import MAX_BYTES, finite_number, load_json, snapshot, state_hash
from tracefi.models import ModelAdapter, observed_decision
from tracefi.policy import check_policy, valid_proposal


class MetricsModel(Protocol):
    """Scenario-specific metrics: per-proposal assessment, aggregation and directions."""

    directions: dict[str, int]

    def assess(self, proposal: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]: ...

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]: ...


MetricsModels = Mapping[str, MetricsModel]
NO_METRICS_MODELS: MetricsModels = MappingProxyType({})


def _mean(values: list[Any]) -> float | None:
    return math.fsum(value / len(values) for value in values) if values else None


GENERAL_METRICS: dict[str, tuple[int, Callable[[list[dict[str, Any]]], Any]]] = {
    "consistent_decisions": (1, lambda rows: sum(row["consistent"] for row in rows)),
    "failed_scenarios": (-1, lambda rows: sum("error_type" in row for row in rows)),
    "valid_decisions": (1, lambda rows: sum(row["valid"] for row in rows)),
    "unsafe_proposals": (-1, lambda rows: sum(row["unsafe_proposal"] for row in rows)),
    "average_proposed_exposure": (
        -1,
        lambda rows: _mean([row["exposure"] for row in rows if finite_number(row.get("exposure"))]),
    ),
}
DEFAULT_REGRESSIONS = [
    "valid_decisions",
    "unsafe_proposals",
    "average_proposed_exposure",
    "consistent_decisions",
    "failed_scenarios",
]


def regression_directions(metrics_models: MetricsModels = NO_METRICS_MODELS) -> dict[str, int]:
    return {
        **{metric: direction for metric, (direction, _) in GENERAL_METRICS.items()},
        **{
            metric: direction
            for model in metrics_models.values()
            for metric, direction in model.directions.items()
        },
    }


MAX_SCENARIOS = 1000
MAX_DATASET_BYTES = 64 * 1024 * 1024


def load_scenarios(directory: str | Path) -> list[dict[str, Any]]:
    paths = []
    for path in Path(directory).rglob("*.json"):
        paths.append(path)
        if len(paths) > MAX_SCENARIOS:
            raise ValueError("Dataset exceeds scenario count limit")
    paths.sort()
    if not paths:
        raise ValueError(f"No JSON scenarios in {directory}")
    result = []
    total_bytes = 0
    for path in paths:
        size = path.stat().st_size
        total_bytes += size
        if total_bytes > MAX_DATASET_BYTES:
            raise ValueError("Dataset exceeds total byte limit")
        if size > MAX_BYTES:
            raise ValueError("Scenario exceeds the byte limit")
        if path.is_symlink():
            raise ValueError("Scenario symlinks are unsupported")
        with path.open("rb") as stream:
            scenario = load_json(stream.read(MAX_BYTES + 1))
        if not isinstance(scenario, dict) or not isinstance(scenario.get("state"), dict):
            raise ValueError(f"Scenario needs an object state: {path}")
        scenario.setdefault("id", str(path.relative_to(directory)))
        result.append(scenario)
    ids = [scenario["id"] for scenario in result]
    if not all(isinstance(item, str) and item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("Scenario IDs must be unique nonempty strings")
    return result


def _evaluate_scenario(
    adapter: ModelAdapter, scenario: dict[str, Any], metrics_models: MetricsModels
) -> dict[str, Any]:
    state = snapshot(scenario["state"])
    proposal = observed_decision(adapter, snapshot(state))
    repeated = observed_decision(adapter, snapshot(state))
    policy = check_policy(
        proposal, state.get("portfolio", {}), state.get("policy_configuration", {})
    )
    row = {
        "scenario": scenario["id"],
        "decision": proposal,
        "valid": valid_proposal(proposal),
        "consistent": state_hash(proposal) == state_hash(repeated),
        "unsafe_proposal": not policy["approved"],
        "exposure": policy.get("requested_exposure"),
    }
    if "metrics_model" in scenario:
        try:
            row["financial_metrics"] = metrics_models[scenario["metrics_model"]].assess(
                proposal, state
            )
        except Exception as exc:
            row["financial_metrics_error"] = type(exc).__name__
    return row


def evaluate(
    adapter: ModelAdapter,
    scenarios: list[dict[str, Any]],
    metrics_models: MetricsModels = NO_METRICS_MODELS,
) -> dict[str, Any]:
    if any(
        scenario["metrics_model"] not in metrics_models
        for scenario in scenarios
        if "metrics_model" in scenario
    ):
        raise ValueError("Unknown metrics model")
    rows = []
    assessed: dict[str, list[dict[str, Any]]] = {name: [] for name in metrics_models}
    for scenario in scenarios:
        try:
            row = _evaluate_scenario(adapter, scenario, metrics_models)
        except Exception as exc:
            row = {
                "scenario": scenario["id"],
                "valid": False,
                "consistent": False,
                "error_type": type(exc).__name__,
                "unsafe_proposal": False,
                "exposure": None,
            }
        rows.append(row)
        if "financial_metrics" in row:
            assessed[scenario["metrics_model"]].append(row["financial_metrics"])
    metrics: dict[str, Any] = {"scenarios": len(rows)}
    for name, model in metrics_models.items():
        metrics.update(model.summarize(assessed[name]))
    metrics.update({metric: measure(rows) for metric, (_, measure) in GENERAL_METRICS.items()})
    return {
        "metrics": metrics,
        "results": rows,
        "limitations": "Exposure measures proposed allocation, not a calibrated risk score. Returns and drawdown are unavailable without a validated outcome model.",
    }


def compare(
    baseline: ModelAdapter,
    candidate: ModelAdapter,
    scenarios: list[dict[str, Any]],
    regression_metrics: list[str] | None = None,
    metrics_models: MetricsModels = NO_METRICS_MODELS,
) -> dict[str, Any]:
    directions = regression_directions(metrics_models)
    tracked = DEFAULT_REGRESSIONS if regression_metrics is None else regression_metrics
    if any(metric not in directions for metric in tracked):
        raise ValueError("Unsupported regression metric")
    a = evaluate(baseline, scenarios, metrics_models)
    b = evaluate(candidate, scenarios, metrics_models)
    regressions, improvements, trade_offs = [], [], []
    for metric, direction in directions.items():
        old, new = a["metrics"][metric], b["metrics"][metric]
        if old is None or new is None or old == new:
            continue
        change = {"metric": metric, "baseline": old, "candidate": new}
        if (new - old) * direction > 0:
            improvements.append(change)
        elif metric in tracked:
            regressions.append(change)
        else:
            trade_offs.append(change)
    return {
        "baseline": a,
        "candidate": b,
        "regressions": regressions,
        "improvements": improvements,
        "trade_offs": trade_offs,
        "tracked_metrics": list(tracked),
        "limitations": "Metric direction is an explicit comparison convention, not financial optimality. Lower costs can mean less participation; policy-rejected (unsafe) proposals may demonstrate a working control. Costs/exposure describe proposals, including blocked ones. No returns or drawdown are inferred.",
    }
