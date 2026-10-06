"""Deterministic evidence-based findings. Findings are not causal proof."""
from enum import Enum
from agenttrace.hashing import state_hash
from agenttrace.models import decision_state, observed_decision
from agenttrace.models.deterministic import finite_number


class FailureType(str, Enum):
    DATA_FAILURE = "DATA_FAILURE"
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"
    REASONING_FAILURE = "REASONING_FAILURE"
    POLICY_FAILURE = "POLICY_FAILURE"
    SIMULATION_FAILURE = "SIMULATION_FAILURE"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    MARKET_OUTCOME = "MARKET_OUTCOME"
    ADVERSARIAL_INPUT = "ADVERSARIAL_INPUT"


def check_policy(proposal, portfolio, config):
    amount = proposal.get("amount")
    balance = portfolio.get(proposal.get("asset", "USDC"), 0)
    limit = config.get("max_exposure", 0.35)
    reasons = []
    valid = (proposal.get("action") in ("HOLD", "SUPPLY", "WITHDRAW")
             and finite_number(amount) and amount >= 0)
    if not valid:
        reasons.append("INVALID_PROPOSAL")
    if not finite_number(balance) or balance < 0 or not finite_number(limit) or not 0 <= limit <= 1:
        reasons.append("INVALID_POLICY_INPUT")
    exposure = amount / balance if valid and finite_number(balance) and balance > 0 else None
    if valid and proposal["action"] == "SUPPLY":
        if exposure is None or finite_number(limit) and exposure > limit:
            reasons.append("MAX_EXPOSURE")
    return {"approved": not reasons, "should_reject": bool(reasons), "reasons": reasons,
            "requested_exposure": exposure, "maximum_exposure": limit}


def analyze(trace):
    context = trace.get("context") or {}
    retrieval = trace.get("retrieval") or {}
    policy = trace.get("policy") or {}
    simulation = trace.get("simulation") or {}
    execution = trace.get("execution") or {}
    outcome = trace.get("outcome") or {}
    proposal = trace.get("proposal") or {}
    findings = []

    def add(kind, evidence, certainty="observed", path=None):
        findings.append({"type": kind.value, "certainty": certainty, "evidence": evidence, "path": path})

    max_age = trace.get("policy_configuration", {}).get("max_oracle_age_seconds", 300)
    age = context.get("oracle_age_seconds")
    if finite_number(age) and finite_number(max_age) and (age < 0 or age > max_age):
        add(FailureType.DATA_FAILURE, f"Oracle age {age}s is outside [0, {max_age}]s.", path="context.oracle_age_seconds")
    if "price" in context and not finite_number(context["price"]):
        add(FailureType.DATA_FAILURE, "Price is missing or non-numeric.", path="context.price")
    if context.get("conflicting_sources") is True:
        add(FailureType.DATA_FAILURE, "The snapshot reports conflicting price sources.", "likely", "context.conflicting_sources")
    available = retrieval.get("available_features", [])
    included = retrieval.get("included_features", [])
    required = retrieval.get("required_features", [])
    if all(isinstance(item, list) and all(isinstance(key, str) for key in item) for item in (available, included, required)):
        missing = sorted(set(required) & set(available) - set(included))
        if missing:
            add(FailureType.RETRIEVAL_FAILURE,
                "Available required features omitted from agent context: " + ", ".join(missing), "likely", "retrieval")
    success = execution.get("success") is True or execution.get("status") == "success"
    reverted = execution.get("status") in ("reverted", "failed") or execution.get("success") is False
    if success and (policy.get("should_reject") is True or policy.get("approved") is False):
        add(FailureType.POLICY_FAILURE, "Execution succeeded despite a recorded rejection requirement.", path="policy")
    if trace.get("policy_configuration") and proposal:
        expected = check_policy(proposal, trace.get("portfolio", {}), trace["policy_configuration"])
        if not expected["approved"] and policy.get("approved") is True:
            add(FailureType.POLICY_FAILURE, "Recorded approval contradicts the configured deterministic policy: " + ", ".join(expected["reasons"]), path="policy")
    if proposal and (not finite_number(proposal.get("amount")) or proposal.get("amount", 0) < 0):
        add(FailureType.REASONING_FAILURE, "Proposal contains an invalid amount; no internal reasoning is inferred.", path="proposal.amount")
    if reverted:
        add(FailureType.EXECUTION_FAILURE, "Execution failed" + (" after a successful simulation." if simulation.get("success") is True else "."), path="execution")
    predicted = simulation.get("predicted_effect")
    actual = execution.get("actual_effect")
    tolerance = simulation.get("effect_tolerance", 0)
    if all(finite_number(item) for item in (predicted, actual, tolerance)) and tolerance >= 0 and abs(predicted - actual) > tolerance:
        add(FailureType.SIMULATION_FAILURE, f"Predicted effect {predicted} differs from actual {actual} beyond tolerance {tolerance}.", path="simulation.predicted_effect")
    untrusted = retrieval.get("untrusted_data", [])
    for item in untrusted if isinstance(untrusted, list) else []:
        if isinstance(item, dict) and item.get("suspicious") is True:
            add(FailureType.ADVERSARIAL_INPUT, "Suspicious untrusted input recorded from " + str(item.get("source", "unknown")) + "; influence on the decision is unproven.", "likely", "retrieval.untrusted_data")
    pnl = outcome.get("pnl")
    if finite_number(pnl) and pnl < 0 and not findings and success and policy.get("approved") is True and simulation.get("success") is True:
        add(FailureType.MARKET_OUTCOME, "Negative recorded PnL with no failure detected by available rules; unobserved failures remain possible.", "likely", "outcome.pnl")
    # Priority expresses diagnostic interest, never proof of a primary cause.
    order = {kind.value: i for i, kind in enumerate((FailureType.POLICY_FAILURE, FailureType.DATA_FAILURE,
             FailureType.RETRIEVAL_FAILURE, FailureType.REASONING_FAILURE, FailureType.SIMULATION_FAILURE,
             FailureType.EXECUTION_FAILURE, FailureType.ADVERSARIAL_INPUT, FailureType.MARKET_OUTCOME))}
    findings.sort(key=lambda finding: order[finding["type"]])
    return {"trace_id": trace["trace_id"], "decision": proposal, "outcome": outcome,
            "likely_failure_class": findings[0]["type"] if findings else None, "findings": findings,
            "coverage": {key: "recorded" if trace.get(key) else "not recorded" for key in
                         ("context", "retrieval", "proposal", "policy", "simulation", "execution", "outcome")},
            "limitations": "Rule matches identify evidence and inconsistencies, not financial correctness or causal proof."}


def replay(trace, adapter):
    original = trace.get("proposal")
    if original is None:
        raise ValueError("Trace has no recorded decision")
    if "[REDACTED]" in str(decision_state(trace)):
        raise ValueError("Replay state contains redacted values; exact reproduction is unavailable")
    result = observed_decision(adapter, decision_state(trace), trace.get("redaction_keys", ()))
    return {"trace_id": trace["trace_id"], "agent": trace["agent"], "original": original,
            "replayed": result, "equal": state_hash(original) == state_hash(result),
            "interpretation": "One replay matched" if state_hash(original) == state_hash(result) else "Decision divergence",
            "limitations": "A matching replay is not proof of determinism; code, dependencies and model must also match."}


def changed_paths(a, b, prefix=""):
    if isinstance(a, dict) and isinstance(b, dict):
        changes = []
        for key in sorted(a.keys() | b.keys()):
            path = f"{prefix}.{key}" if prefix else key
            if key not in a or key not in b:
                changes.append({"path": path, "before": a.get(key), "after": b.get(key),
                                "before_present": key in a, "after_present": key in b})
            else:
                changes.extend(changed_paths(a[key], b[key], path))
        return changes
    if state_hash(a) != state_hash(b):
        return [{"path": prefix, "before": a, "after": b, "before_present": True, "after_present": True}]
    return []


def diff(a, b):
    fields = ("agent", "context", "portfolio", "agent_configuration", "policy_configuration")
    return {"trace_a": a["trace_id"], "trace_b": b["trace_id"],
            "changed_inputs": changed_paths({key: a[key] for key in fields}, {key: b[key] for key in fields}),
            "decision_changes": changed_paths(a.get("proposal"), b.get("proposal"), "proposal"),
            "policy_changes": changed_paths(a.get("policy"), b.get("policy"), "policy")}
