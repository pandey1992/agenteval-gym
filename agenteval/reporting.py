"""Stable JSON serialization for AgentEval Gym scenario results."""

import json
from dataclasses import asdict
from html import escape
from pathlib import Path

from agenteval.execution.runner import ScenarioRunResult


def result_to_dict(result: ScenarioRunResult) -> dict:
    """Return a JSON-safe, intentionally scoped summary of one scenario run."""
    return {
        "scenario_id": result.scenario_id,
        "passed": result.passed,
        "checks": [asdict(check) for check in result.evaluation.checks],
        "agent_message": result.agent_result.final_message,
        "tool_trace": [asdict(trace) for trace in result.tool_trace],
        "final_state_counts": {
            "employees": len(result.final_state.employees),
            "projects": len(result.final_state.projects),
            "allocations": len(result.final_state.allocations),
            "policies": len(result.final_state.policies),
            "events": len(result.final_state.events),
        },
        "state_diff": _state_diff(result),
    }


def build_report(results: list[ScenarioRunResult]) -> dict:
    passed = sum(result.passed for result in results)
    tool_calls = [trace for result in results for trace in result.tool_trace]
    successful_calls = sum(200 <= trace.status_code < 300 for trace in tool_calls)
    checks = [check for result in results for check in result.evaluation.checks]
    passed_checks = sum(check.passed for check in checks)
    return {
        "schema_version": 1,
        "summary": {
            "total": len(results), "passed": passed, "failed": len(results) - passed,
            "pass_rate": _percentage(passed, len(results)),
            "tool_calls": len(tool_calls), "successful_tool_calls": successful_calls,
            "tool_success_rate": _percentage(successful_calls, len(tool_calls)),
            "checks": len(checks), "passed_checks": passed_checks,
            "check_pass_rate": _percentage(passed_checks, len(checks)),
        },
        "scenarios": [result_to_dict(result) for result in results],
    }


def _percentage(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 1) if denominator else 0.0


def write_json_report(results: list[ScenarioRunResult], path: str | Path) -> Path:
    """Write a UTF-8 JSON report, creating parent directories as needed."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_report(results), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def _state_diff(result: ScenarioRunResult) -> dict:
    before = {row["allocation_id"]: row for row in result.initial_state.allocations}
    after = {row["allocation_id"]: row for row in result.final_state.allocations}
    return {
        "allocations_added": [after[key] for key in sorted(after.keys() - before.keys())],
        "allocations_removed": [before[key] for key in sorted(before.keys() - after.keys())],
        "allocations_changed": [
            {"before": before[key], "after": after[key]}
            for key in sorted(before.keys() & after.keys()) if before[key] != after[key]
        ],
        "events_added": list(result.final_state.events[len(result.initial_state.events):]),
    }


def render_html_report(results: list[ScenarioRunResult]) -> str:
    """Render a self-contained, escaped HTML report for local viewing."""
    report = build_report(results)
    summary = report["summary"]
    cards = [
        ("Scenario pass rate", f"{summary['pass_rate']}%", f"{summary['passed']} of {summary['total']} passed"),
        ("Tool call success", f"{summary['tool_success_rate']}%", f"{summary['successful_tool_calls']} of {summary['tool_calls']} returned HTTP 2xx"),
        ("Oracle checks", f"{summary['check_pass_rate']}%", f"{summary['passed_checks']} of {summary['checks']} passed"),
    ]
    metrics = "".join(
        f'<article class="metric"><p>{escape(label)}</p><strong>{value}</strong><span>{escape(note)}</span></article>'
        for label, value, note in cards
    )
    panels = []
    for scenario, result in zip(report["scenarios"], results):
        status = "Passed" if scenario["passed"] else "Failed"
        checks = "".join(
            f'<tr><td>{escape(check["name"])}</td><td class="{"good" if check["passed"] else "bad"}>{"PASS" if check["passed"] else "FAIL"}</td><td>{escape(check["detail"])}</td></tr>'
            for check in scenario["checks"]
        )
        traces = "".join(
            f'<tr><td>{escape(trace.tool_name)}</td><td>{trace.status_code}</td><td><code>{escape(json.dumps(trace.arguments, sort_keys=True))}</code></td><td><code>{escape(json.dumps(trace.body, sort_keys=True))}</code></td></tr>'
            for trace in result.tool_trace
        ) or '<tr><td colspan="4">No tool calls recorded.</td></tr>'
        diff = escape(json.dumps(_state_diff(result), indent=2, sort_keys=True))
        panels.append(
            f'<details class="scenario"><summary><span class="pill {"pass" if scenario["passed"] else "fail"}">{status}</span>'
            f'<strong>{escape(scenario["scenario_id"])}</strong><span>{len(scenario["checks"])} checks · {len(result.tool_trace)} tool calls</span></summary>'
            f'<p class="agent">{escape(scenario["agent_message"])}</p><h3>Oracle checks</h3>'
            f'<div class="table-wrap"><table><tr><th>Check</th><th>Result</th><th>Details</th></tr>{checks}</table></div>'
            f'<h3>Tool trace</h3><div class="table-wrap"><table><tr><th>Tool</th><th>HTTP</th><th>Arguments</th><th>Response</th></tr>{traces}</table></div>'
            f'<h3>Database state changes</h3><pre>{diff}</pre></details>'
        )
    heading = "All scenarios passed" if summary["failed"] == 0 and summary["total"] else "Evaluation results"
    if not summary["total"]:
        heading = "No scenario runs were collected"
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AgentEval Gym Report</title>
<style>
:root{{--bg:#f4f6fa;--ink:#182230;--muted:#617087;--line:#dfe5ee;--green:#147d53;--red:#b42318}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1120px;margin:auto;padding:36px 24px 64px}}header{{margin-bottom:24px}}h1{{font-size:30px;margin:0}}header p{{color:var(--muted);margin:8px 0}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:28px}}
.metric,.scenario{{background:white;border:1px solid var(--line);border-radius:12px;box-shadow:0 2px 8px #18223008}}.metric{{padding:20px}}.metric p,.metric span{{color:var(--muted)}}.metric p{{margin:0}}.metric strong{{display:block;font-size:34px;margin:4px 0}}.metric span{{font-size:13px}}
h2{{font-size:20px}}.scenario{{margin:12px 0;padding:0 18px}}summary{{list-style:none;cursor:pointer;display:flex;align-items:center;gap:12px;min-height:64px}}summary::-webkit-details-marker{{display:none}}summary span:last-child{{margin-left:auto;color:var(--muted);font-size:13px}}
.pill{{font-size:12px;font-weight:700;border-radius:99px;padding:4px 9px}}.pass,.good{{color:var(--green)}}.pass{{background:#e7f6ef}}.fail,.bad{{color:var(--red)}}.fail{{background:#fcebea}}.agent{{color:var(--muted)}}h3{{font-size:15px;margin:18px 0 8px}}.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:var(--muted)}}td code{{white-space:pre-wrap;overflow-wrap:anywhere}}pre{{background:#f7f8fb;border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto;font-size:12px}}footer{{color:var(--muted);font-size:12px;margin-top:28px}}
@media(max-width:700px){{main{{padding:24px 14px}}.metrics{{grid-template-columns:1fr}}summary{{flex-wrap:wrap;padding:12px 0}}summary span:last-child{{margin-left:0;width:100%}}}}
</style></head><body><main><header><h1>AgentEval Gym</h1><p>{escape(heading)} · {summary['passed']}/{summary['total']} scenario runs passed</p></header>
<section class="metrics" aria-label="Evaluation metrics">{metrics}</section><h2>Scenario details</h2>{''.join(panels)}
<footer>Tool call success counts HTTP 2xx responses. Scenario verdicts come from deterministic database and invariant checks.</footer>
</main></body></html>'''


def write_html_report(results: list[ScenarioRunResult], path: str | Path) -> Path:
    """Write a standalone HTML evaluation report."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html_report(results), encoding="utf-8")
    return output
