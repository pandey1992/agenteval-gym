import json

from agenteval.reporting import build_report, write_json_report


def test_report_serializes_checks_trace_and_summary(agent_runner, agenteval_scenarios, tmp_path):
    from agenteval.execution import ScriptedAgent, ToolCall

    scenario = next(item for item in agenteval_scenarios if item.scenario_id == "TC001")
    result = agent_runner.run(scenario, ScriptedAgent([
        ToolCall("assign_resource", scenario.request.model_dump(mode="json"), "report-test")
    ]))
    report = build_report([result])
    assert report["summary"] == {"total": 1, "passed": 1, "failed": 0}
    assert report["scenarios"][0]["checks"]
    assert report["scenarios"][0]["tool_trace"][0]["tool_name"] == "assign_resource"

    output = write_json_report([result], tmp_path / "nested" / "report.json")
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded == report
