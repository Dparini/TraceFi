import html
import json
from tracefi.analysis import analyze


def postmortem(trace):
    report = analyze(trace)
    lines = ["TRACEFI POST-MORTEM", "", "Trace: " + trace["trace_id"],
             "Agent: " + trace["agent"]["name"] + "@" + trace["agent"]["version"],
             "Decision: " + json.dumps(report["decision"], ensure_ascii=False),
             "Outcome: " + json.dumps(report["outcome"], ensure_ascii=False), ""]
    for stage, coverage in report["coverage"].items():
        value = trace.get(stage)
        if stage in ("policy", "simulation", "execution") and value:
            lines.append(stage.upper() + ": " + json.dumps(value, ensure_ascii=False))
        else:
            lines.append(stage.upper() + ": " + coverage)
    lines.extend(["", "LIKELY FAILURE CLASS: " + (report["likely_failure_class"] or "UNDETERMINED")])
    for finding in report["findings"]:
        lines.append(f"[{finding['certainty']}] {finding['type']}: {finding['evidence']}")
    lines.extend(["", report["limitations"]])
    return "\n".join(lines)


def export_html(trace):
    rows = "".join("<tr>" + "".join("<td>" + html.escape(str(span.get(key, ""))) + "</td>"
                                 for key in ("start", "name", "type", "status", "duration_ns")) + "</tr>"
                   for span in trace["spans"])
    payload = html.escape(json.dumps(trace, indent=2, ensure_ascii=False))
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>TraceFi post-mortem</title><style>
body{font:16px system-ui;background:#0b1020;color:#e2e8f0;max-width:1100px;margin:40px auto;padding:24px}
h1{color:#67e8f9}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#141e33;padding:24px;border-radius:12px}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:12px;border-bottom:1px solid #334155}
</style><h1>TraceFi</h1><p>Financial decision provenance · synthetic results are not financial validation.</p>
<pre>''' + html.escape(postmortem(trace)) + '''</pre><h2>Timeline</h2><table><thead><tr><th>Start UTC</th><th>Span</th><th>Type</th><th>Status</th><th>Duration ns</th></tr></thead><tbody>''' + rows + '''</tbody></table><details><summary>Recorded snapshot</summary><pre>''' + payload + '''</pre></details></html>'''


def decision_text(proposal):
    if not proposal:
        return "No proposal"
    amount = proposal.get("amount")
    amount_text = f"{amount:,.2f}".rstrip("0").rstrip(".") if isinstance(amount, (int, float)) else str(amount)
    return " ".join(str(item) for item in (proposal.get("action", "UNKNOWN"), amount_text,
                                           proposal.get("asset", ""), "→ " + str(proposal["protocol"]) if proposal.get("protocol") else "") if item)


def replay_report(report):
    return "\n".join(("TRACEFI REPLAY", "Trace: " + report["trace_id"],
                      "Agent: " + report["agent"]["name"] + "@" + report["agent"]["version"], "",
                      "Original: " + decision_text(report["original"]), "Replayed: " + decision_text(report["replayed"]), "",
                      "✓ MATCHING DECISION" if report["equal"] else "⚠ DECISION DIVERGENCE",
                      report["limitations"]))


def diff_report(report):
    lines = ["TRACEFI DECISION DIFF", "A: " + report["trace_a"], "B: " + report["trace_b"], ""]
    for label, field in (("Changed inputs", "changed_inputs"), ("Decision changes", "decision_changes"), ("Policy changes", "policy_changes")):
        lines.append(label.upper())
        for change in report[field]:
            before = json.dumps(change["before"], ensure_ascii=False) if change["before_present"] else "<absent>"
            after = json.dumps(change["after"], ensure_ascii=False) if change["after_present"] else "<absent>"
            lines.append(f"  {change['path']}: {before} → {after}")
        if not report[field]:
            lines.append("  No changes")
        lines.append("")
    return "\n".join(lines)


def why_change_report(report):
    lines = ["TRACEFI WHY CHANGE", "A: " + report["trace_a"], "B: " + report["trace_b"], "", "COUNTERFACTUAL TESTS"]
    for experiment in report["experiments"]:
        lines.append(f"  {experiment['path']}: {experiment['before']} → {experiment['after']}")
        lines.append("    " + decision_text(experiment["decision"]) + (" · reproduces target" if experiment["matches_target"] else ""))
    lines.extend(["", "PRIMARY DECISION DRIVER: " + (report["primary_decision_driver"] or "UNDETERMINED"), report["limitations"]])
    return "\n".join(lines)


def regression_report(report):
    lines = ["AGENT REGRESSION REPORT", "", f"{'Metric':32} {'Baseline':>12} {'Candidate':>12}"]
    for key, value in report["baseline"]["metrics"].items():
        other = report["candidate"]["metrics"][key]
        def fmt(number):
            return "unavailable" if number is None else f"{number:.3f}" if isinstance(number, float) else str(number)
        lines.append(f"{key.replace('_', ' '):32} {fmt(value):>12} {fmt(other):>12}")
    lines.extend(["", "REGRESSIONS"])
    for regression in report["regressions"]:
        lines.append(f"  ⚠ {regression['metric']}: {regression['baseline']} → {regression['candidate']}")
    if not report["regressions"]:
        lines.append("  No tracked regressions")
    lines.extend(["", report["baseline"]["limitations"], report["limitations"]])
    return "\n".join(lines)


def counterfactual_report(report):
    if "boundary_found" in report:
        return "\n".join(("DECISION BOUNDARY " + ("BRACKET FOUND" if report["boundary_found"] else "NOT FOUND AT ENDPOINTS"),
                          "Feature: " + report["feature"], "Interval: " + str(report["interval"]), report["limitations"]))
    return "\n".join(("TRACEFI COUNTERFACTUAL", "Feature: " + report["feature"],
                      "Value: " + json.dumps(report["value"], ensure_ascii=False),
                      "Original: " + decision_text(report["original"]),
                      "Modified: " + decision_text(report["counterfactual"]),
                      "Decision changed: " + str(report["decision_changed"])))
