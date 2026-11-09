"""Stable JSON serialization for AgentEval Gym scenario results."""

import json
from dataclasses import asdict
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
    }


def build_report(results: list[ScenarioRunResult]) -> dict:
    passed = sum(result.passed for result in results)
    return {
        "schema_version": 1,
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
        "scenarios": [result_to_dict(result) for result in results],
    }


def write_json_report(results: list[ScenarioRunResult], path: str | Path) -> Path:
    """Write a UTF-8 JSON report, creating parent directories as needed."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_report(results), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
