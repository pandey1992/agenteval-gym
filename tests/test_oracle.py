from datetime import date
from pathlib import Path

import pytest

from agenteval.evaluation.oracle import ObservedOutcome, capture_snapshot, evaluate_scenario
from agenteval.evaluation.scenarios import load_scenarios
from agenteval.models import Allocation, AllocationEvent, Employee, Project
from agenteval.services import BusinessError, create_allocation, get_availability


SCENARIOS = load_scenarios()


def _seed(session, scenario):
    for row in scenario.initial_state.employees:
        session.add(Employee(**row.model_dump()))
    session.flush()
    for row in scenario.initial_state.projects:
        data = row.model_dump()
        data["start_date"] = date.fromisoformat(data["start_date"])
        data["end_date"] = date.fromisoformat(data["end_date"])
        session.add(Project(**data))
    session.flush()
    for row in scenario.initial_state.allocations:
        data = row.model_dump()
        data["start_date"] = date.fromisoformat(data["start_date"])
        data["end_date"] = date.fromisoformat(data["end_date"])
        session.add(Allocation(**data))
    session.commit()


def test_five_frozen_scenario_definitions_are_valid():
    assert {scenario.scenario_id for scenario in SCENARIOS} == {"TC001", "TC002", "TC003", "TC004", "TC005"}
    assert all(scenario.safe_refusal == (scenario.scenario_id != "TC001") for scenario in SCENARIOS)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.scenario_id)
def test_scenario_oracle_evaluates_expected_business_outcomes(project_env, scenario):
    with project_env.session_factory() as session:
        _seed(session, scenario)

    # TC005 captures an earlier availability result, then changes the world
    # before the allocation attempt to model stale agent observations.
    if scenario.state_changes_before_action:
        request = scenario.request
        with project_env.session_factory() as session:
            old_availability = get_availability(session, request.employee_id,
                date.fromisoformat(request.start_date), date.fromisoformat(request.end_date))
        assert old_availability["available_percentage"] >= request.allocation_percentage
        with project_env.session_factory() as session:
            for row in scenario.state_changes_before_action:
                data = row.model_dump()
                data["start_date"] = date.fromisoformat(data["start_date"])
                data["end_date"] = date.fromisoformat(data["end_date"])
                allocation = Allocation(**data)
                session.add(allocation)
                session.flush()
                session.add(AllocationEvent(allocation_id=allocation.allocation_id,
                    event_type="external_change", event_details={}))
            session.commit()

    with project_env.session_factory() as session:
        before = capture_snapshot(session)

    request = scenario.request
    try:
        with project_env.session_factory() as session:
            create_allocation(session, employee_id=request.employee_id, project_id=request.project_id,
                allocation_percentage=request.allocation_percentage, start_date=date.fromisoformat(request.start_date),
                end_date=date.fromisoformat(request.end_date))
        outcome = ObservedOutcome(status_code=201)
    except BusinessError as error:
        outcome = ObservedOutcome(status_code=error.status_code, error_code=error.code)

    with project_env.session_factory() as session:
        after = capture_snapshot(session)
    result = evaluate_scenario(scenario, before, after, outcome)
    assert result.passed, "\n".join(f"{check.name}: {check.detail}" for check in result.checks if not check.passed)


def test_oracle_detects_unexpected_side_effect(project_env):
    scenario = next(item for item in SCENARIOS if item.scenario_id == "TC002")
    with project_env.session_factory() as session:
        _seed(session, scenario)
    with project_env.session_factory() as session:
        before = capture_snapshot(session)
    request = scenario.request
    with project_env.session_factory() as session:
        session.add(Allocation(employee_id="EMP001", project_id="PROJ002", allocation_percentage=10,
            start_date=date.fromisoformat(request.start_date), end_date=date.fromisoformat(request.end_date), status="active"))
        session.commit()
    with project_env.session_factory() as session:
        after = capture_snapshot(session)
    result = evaluate_scenario(scenario, before, after, ObservedOutcome(status_code=409, error_code="capacity_conflict"))
    assert not result.passed
    assert not next(check for check in result.checks if check.name == "final_allocations_match").passed


def test_loader_rejects_duplicate_scenario_ids(tmp_path):
    scenario = Path(__file__).resolve().parents[1] / "benchmarks" / "resource_allocation" / "TC001_valid_assignment.json"
    (tmp_path / "TC001_a.json").write_text(scenario.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "TC001_b.json").write_text(scenario.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_scenarios(tmp_path)

