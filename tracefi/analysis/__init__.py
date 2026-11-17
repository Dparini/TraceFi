"""Deterministic evidence-based findings. Findings are not causal proof."""

from enum import Enum
from typing import Any

from tracefi.hashing import finite_number
from tracefi.policy import check_policy, valid_proposal
from tracefi.schema import (
    EXECUTION_STATUSES,
    OBSERVATIONS,
    STATE_FIELDS,
    changed_paths,
    clean,
    execution_failed,
)


class FailureType(str, Enum):
    """Failure classes, declared in inspection priority order."""

    POLICY_FAILURE = "POLICY_FAILURE"
    DATA_FAILURE = "DATA_FAILURE"
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"
    REASONING_FAILURE = "REASONING_FAILURE"
    SIMULATION_FAILURE = "SIMULATION_FAILURE"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    ADVERSARIAL_INPUT = "ADVERSARIAL_INPUT"
    MARKET_OUTCOME = "MARKET_OUTCOME"


_PRIORITY = {kind.value: index for index, kind in enumerate(FailureType)}


def analyze(trace: dict[str, Any]) -> dict[str, Any]:
    trace = clean(trace, trace)
    input_errors: list[str] = []

    def section(key: str) -> dict[str, Any]:
        value = trace.get(key)
        if value is None:
            return {}
        if not isinstance(value, dict):
            input_errors.append(key + ": expected a JSON object")
            return {}
        return value

    context, retrieval, policy = section("context"), section("retrieval"), section("policy")
    simulation, execution, outcome = section("simulation"), section("execution"), section("outcome")
    proposal, portfolio, config = (
        section("proposal"),
        section("portfolio"),
        section("policy_configuration"),
    )
    findings: list[dict[str, Any]] = []

    def add(
        kind: FailureType, evidence: str, certainty: str = "observed", path: str | None = None
    ) -> None:
        findings.append(
            {"type": kind.value, "certainty": certainty, "evidence": evidence, "path": path}
        )

    for label, obj, keys in (
        ("policy", policy, ("approved", "should_reject")),
        ("simulation", simulation, ("success",)),
        ("execution", execution, ("success",)),
    ):
        for key in keys:
            if key in obj and not isinstance(obj[key], bool):
                input_errors.append(label + "." + key + ": expected a boolean")
    max_age = config.get("max_oracle_age_seconds", 300)
    age = context.get("oracle_age_seconds")
    if not finite_number(max_age) or max_age < 0:
        input_errors.append("policy_configuration.max_oracle_age_seconds: invalid limit")
    if "oracle_age_seconds" in context and not finite_number(age):
        add(
            FailureType.DATA_FAILURE,
            "Oracle age is not a finite number.",
            path="context.oracle_age_seconds",
        )
    elif (
        finite_number(age)
        and finite_number(max_age)
        and max_age >= 0
        and (age < 0 or age > max_age)
    ):
        add(
            FailureType.DATA_FAILURE,
            f"Oracle age {age}s is outside [0, {max_age}]s.",
            path="context.oracle_age_seconds",
        )
    if "price" in context and not finite_number(context["price"]):
        add(FailureType.DATA_FAILURE, "Price is missing or non-numeric.", path="context.price")
    if "conflicting_sources" in context and not isinstance(context["conflicting_sources"], bool):
        input_errors.append("context.conflicting_sources: expected a boolean")
    if context.get("conflicting_sources") is True:
        add(
            FailureType.DATA_FAILURE,
            "The snapshot reports conflicting price sources.",
            "likely",
            "context.conflicting_sources",
        )
    features = [
        retrieval.get(key, [])
        for key in ("available_features", "included_features", "required_features")
    ]
    if all(
        isinstance(item, list) and all(isinstance(key, str) for key in item) for item in features
    ):
        available, included, required = features
        missing = sorted((set(required) & set(available)) - set(included))
        if missing:
            add(
                FailureType.RETRIEVAL_FAILURE,
                "Available required features omitted from agent context: " + ", ".join(missing),
                "likely",
                "retrieval",
            )
    else:
        input_errors.append("retrieval: feature lists must contain strings")
    status = execution.get("status")
    if status is not None and status not in EXECUTION_STATUSES:
        input_errors.append("execution.status: unsupported value")
    success = execution.get("success") is True or status == "success"
    reverted = execution_failed(execution)
    if success and (reverted or status == "blocked"):
        input_errors.append("execution: conflicting success/status evidence")
        success = False
    if success and (policy.get("should_reject") is True or policy.get("approved") is False):
        add(
            FailureType.POLICY_FAILURE,
            "Execution reports success despite a recorded rejection requirement.",
            path="policy",
        )
    if config and proposal:
        expected = check_policy(proposal, portfolio, config)
        if not expected["approved"] and policy.get("approved") is True:
            add(
                FailureType.POLICY_FAILURE,
                "Recorded approval contradicts the configured deterministic policy: "
                + ", ".join(expected["reasons"]),
                path="policy",
            )
    if trace.get("proposal") is not None and not valid_proposal(proposal):
        add(
            FailureType.REASONING_FAILURE,
            "Proposal fields are invalid or inconsistent; no internal reasoning is inferred.",
            path="proposal",
        )
    if reverted:
        add(
            FailureType.EXECUTION_FAILURE,
            "Execution reports failure"
            + (" after a successful simulation." if simulation.get("success") is True else "."),
            path="execution",
        )
    if simulation.get("success") is False:
        add(
            FailureType.SIMULATION_FAILURE,
            "Simulation explicitly reports failure; execution effects remain separate evidence.",
            path="simulation.success",
        )
    predicted, actual, tolerance = (
        simulation.get("predicted_effect"),
        execution.get("actual_effect"),
        simulation.get("effect_tolerance", 0),
    )
    if (
        finite_number(predicted)
        and finite_number(actual)
        and finite_number(tolerance)
        and tolerance >= 0
    ):
        if abs(predicted - actual) > tolerance:
            add(
                FailureType.SIMULATION_FAILURE,
                f"Predicted effect {predicted} differs from actual {actual} beyond tolerance {tolerance}.",
                path="simulation.predicted_effect",
            )
    elif (
        "predicted_effect" in simulation
        or "actual_effect" in execution
        or "effect_tolerance" in simulation
    ):
        input_errors.append("simulation/execution: invalid or incomplete effect comparison")
    untrusted = retrieval.get("untrusted_data", [])
    if not isinstance(untrusted, list) or not all(isinstance(item, dict) for item in untrusted):
        input_errors.append("retrieval.untrusted_data: expected a list of objects")
    else:
        for item in untrusted:
            if "suspicious" in item and not isinstance(item["suspicious"], bool):
                input_errors.append("retrieval.untrusted_data.suspicious: expected a boolean")
            if item.get("suspicious") is True:
                add(
                    FailureType.ADVERSARIAL_INPUT,
                    "Suspicious untrusted input recorded from "
                    + str(item.get("source", "unknown"))
                    + "; influence on the decision is unproven.",
                    "likely",
                    "retrieval.untrusted_data",
                )
    pnl = outcome.get("pnl")
    if "pnl" in outcome and not finite_number(pnl):
        input_errors.append("outcome.pnl: expected a finite number")
    if (
        finite_number(pnl)
        and pnl < 0
        and not findings
        and not input_errors
        and success
        and policy.get("approved") is True
        and simulation.get("success") is True
        and context
        and portfolio
        and valid_proposal(proposal)
    ):
        add(
            FailureType.MARKET_OUTCOME,
            "Negative recorded PnL with no failure detected by available rules; unobserved failures remain possible.",
            "likely",
            "outcome.pnl",
        )
    findings.sort(key=lambda finding: _PRIORITY[finding["type"]])
    return {
        "trace_id": trace.get("trace_id", "unknown"),
        "decision": proposal,
        "outcome": outcome,
        "likely_failure_class": findings[0]["type"] if findings else None,
        "findings": findings,
        "input_errors": input_errors,
        "coverage": {
            key: "not recorded"
            if trace.get(key) is None
            else "invalid"
            if not isinstance(trace[key], dict)
            else "recorded"
            if trace[key]
            else "empty"
            for key in OBSERVATIONS
        },
        "limitations": "Rule matches identify evidence and inconsistencies, not financial correctness or causal proof.",
    }


def diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    fields = ("agent", *STATE_FIELDS)
    return {
        "trace_a": a["trace_id"],
        "trace_b": b["trace_id"],
        "changed_inputs": changed_paths(
            {key: a[key] for key in fields}, {key: b[key] for key in fields}
        ),
        "decision_changes": changed_paths(a.get("proposal"), b.get("proposal"), "proposal"),
        "policy_changes": changed_paths(a.get("policy"), b.get("policy"), "policy"),
    }
