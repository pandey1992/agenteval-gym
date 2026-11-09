import asyncio

import pytest

from agenteval.evaluation.scenarios import load_scenarios
from agenteval.execution import FaultPlan, ScenarioRunner, ScriptedAgent, ToolCall


SCENARIOS = load_scenarios()


def _agent_for(scenario, *, retries=0, idempotency_key=None):
    calls = []
    if scenario.scenario_id in {"TC002", "TC005", "TC006"}:
        request = scenario.request
        calls.append(ToolCall("get_availability", {
            "employee_id": request.employee_id,
            "start_date": request.start_date,
            "end_date": request.end_date,
        }))
    if scenario.scenario_id == "TC003":
        calls.append(ToolCall("get_employee", {"employee_id": scenario.request.employee_id}))
    request = scenario.request
    calls.append(ToolCall("assign_resource", request.model_dump(mode="json"), idempotency_key))
    return ScriptedAgent(calls, max_retries=retries)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.scenario_id)
def test_runner_executes_scenarios_through_agent_http_tools(tmp_path, scenario):
    result = asyncio.run(ScenarioRunner().run(
        scenario,
        _agent_for(scenario),
        database_path=tmp_path / f"{scenario.scenario_id}.db",
    ))
    assert result.passed, "\n".join(check.detail for check in result.evaluation.checks if not check.passed)
    assert result.tool_trace


@pytest.mark.parametrize("mode", ["fail_before_call", "lose_successful_response"])
def test_runner_retries_deterministic_fault_without_duplicate_side_effects(tmp_path, mode):
    scenario = next(item for item in SCENARIOS if item.scenario_id == "TC001")
    key = f"retry-{mode}"
    result = asyncio.run(ScenarioRunner().run(
        scenario,
        _agent_for(scenario, retries=1, idempotency_key=key),
        database_path=tmp_path / f"fault-{mode}.db",
        fault_plan=FaultPlan(mode=mode),
    ))
    assert result.passed, "\n".join(check.detail for check in result.evaluation.checks if not check.passed)
    assert [trace.status_code for trace in result.tool_trace] == [503, 201]
    assert result.tool_trace[0].fault_injected
    assert len(result.final_state.allocations) == 1
    assert len(result.final_state.events) == 1
    if mode == "lose_successful_response":
        assert result.tool_trace[1].headers.get("idempotency-replayed") == "true"

