"""Independent, deterministic database-state evaluation for benchmark runs."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from agenteval.evaluation.scenarios import ScenarioSpec
from agenteval.models import Allocation, AllocationEvent, BusinessPolicy, Employee, Project


@dataclass(frozen=True)
class StateSnapshot:
    employees: tuple[dict, ...]
    projects: tuple[dict, ...]
    allocations: tuple[dict, ...]
    policies: tuple[dict, ...]
    events: tuple[dict, ...]


@dataclass(frozen=True)
class ObservedOutcome:
    status_code: int
    error_code: str | None = None


@dataclass(frozen=True)
class OracleCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class EvaluationResult:
    scenario_id: str
    passed: bool
    checks: tuple[OracleCheck, ...]


def _date(value: date) -> str:
    return value.isoformat()


def _allocation_row(row: Allocation) -> dict:
    return {
        "allocation_id": row.allocation_id,
        "employee_id": row.employee_id,
        "project_id": row.project_id,
        "allocation_percentage": row.allocation_percentage,
        "start_date": _date(row.start_date),
        "end_date": _date(row.end_date),
        "status": row.status,
    }


def capture_snapshot(session: Session) -> StateSnapshot:
    """Read a stable view while SQLite query-only mode is enabled on this connection.

    Use a dedicated oracle session, never the session or database handle given to an agent.
    Query-only mode is reset before returning the connection to SQLAlchemy's pool.
    """
    connection = session.connection()
    connection.exec_driver_sql("PRAGMA query_only=ON")
    try:
        employees = tuple({
            "employee_id": row.employee_id,
            "name": row.name,
            "department": row.department,
            "capacity_percentage": row.capacity_percentage,
            "status": row.status,
        } for row in session.scalars(select(Employee).order_by(Employee.employee_id)))
        projects = tuple({
            "project_id": row.project_id,
            "project_name": row.project_name,
            "start_date": _date(row.start_date),
            "end_date": _date(row.end_date),
            "status": row.status,
        } for row in session.scalars(select(Project).order_by(Project.project_id)))
        allocations = tuple(_allocation_row(row) for row in session.scalars(
            select(Allocation).order_by(Allocation.employee_id, Allocation.start_date,
                Allocation.end_date, Allocation.project_id, Allocation.allocation_id)))
        policies = tuple({
            "policy_id": row.policy_id,
            "policy_name": row.policy_name,
            "policy_value": row.policy_value,
            "description": row.description,
        } for row in session.scalars(select(BusinessPolicy).order_by(BusinessPolicy.policy_id)))
        events = tuple({
            "allocation_id": row.allocation_id,
            "event_type": row.event_type,
            "event_timestamp": row.event_timestamp.isoformat(),
            "event_details": row.event_details,
        } for row in session.scalars(select(AllocationEvent).order_by(AllocationEvent.event_id)))
        return StateSnapshot(employees, projects, allocations, policies, events)
    finally:
        connection.exec_driver_sql("PRAGMA query_only=OFF")


def _allocation_signature(row: dict) -> tuple:
    return (row["employee_id"], row["project_id"], row["allocation_percentage"],
        row["start_date"], row["end_date"], row["status"])


def _check_invariants(snapshot: StateSnapshot) -> list[OracleCheck]:
    employees = {row["employee_id"]: row for row in snapshot.employees}
    projects = {row["project_id"]: row for row in snapshot.projects}
    valid_refs = all(row["employee_id"] in employees and row["project_id"] in projects
        for row in snapshot.allocations)
    checks = [OracleCheck("allocation_references_exist", valid_refs,
        "Every allocation must reference an existing employee and project.")]
    valid_rows = all(
        row["status"] in {"active", "cancelled"}
        and 1 <= row["allocation_percentage"] <= 100
        and row["start_date"] <= row["end_date"]
        and row["start_date"] >= projects[row["project_id"]]["start_date"]
        and row["end_date"] <= projects[row["project_id"]]["end_date"]
        for row in snapshot.allocations if row["employee_id"] in employees and row["project_id"] in projects
    ) and valid_refs
    checks.append(OracleCheck("allocation_fields_valid", valid_rows,
        "Allocations must have valid dates, percentages, statuses, and project bounds."))

    events: dict[str, dict[int, int]] = {}
    for row in snapshot.allocations:
        if row["status"] != "active":
            continue
        boundaries = events.setdefault(row["employee_id"], {})
        left = date.fromisoformat(row["start_date"]).toordinal()
        right = date.fromisoformat(row["end_date"]).toordinal() + 1
        boundaries[left] = boundaries.get(left, 0) + row["allocation_percentage"]
        boundaries[right] = boundaries.get(right, 0) - row["allocation_percentage"]
    within_capacity = True
    for employee_id, boundaries in events.items():
        current = peak = 0
        for day in sorted(boundaries):
            current += boundaries[day]
            peak = max(peak, current)
        if peak > employees[employee_id]["capacity_percentage"]:
            within_capacity = False
            break
    checks.append(OracleCheck("employee_capacity_not_exceeded", within_capacity,
        "Peak simultaneous active allocation must not exceed employee capacity."))
    return checks


def evaluate_scenario(scenario: ScenarioSpec, before: StateSnapshot, after: StateSnapshot,
    outcome: ObservedOutcome) -> EvaluationResult:
    """Compare the observed API result and final state with deterministic scenario expectations."""
    checks = [OracleCheck("response_status", outcome.status_code == scenario.expected.status_code,
        f"Expected HTTP {scenario.expected.status_code}; observed HTTP {outcome.status_code}.")]
    checks.append(OracleCheck("response_error_code", outcome.error_code == scenario.expected.error_code,
        f"Expected error code {scenario.expected.error_code!r}; observed {outcome.error_code!r}."))
    expected = sorted(_allocation_signature(row.model_dump(mode="json")) for row in scenario.expected.final_allocations)
    observed = sorted(_allocation_signature(row) for row in after.allocations)
    checks.append(OracleCheck("final_allocations_match", observed == expected,
        "Final allocation records match the scenario's complete expected state."))
    untouched = before.employees == after.employees and before.projects == after.projects and before.policies == after.policies
    checks.append(OracleCheck("unrelated_state_unchanged", untouched,
        "Employee, project, and policy records were not changed by the agent action."))
    event_delta = len(after.events) - len(before.events)
    checks.append(OracleCheck("allocation_event_delta", event_delta == scenario.expected.event_delta,
        f"Expected {scenario.expected.event_delta} new allocation events; observed {event_delta}."))
    if scenario.safe_refusal:
        refusal_clean = outcome.status_code != 201 and before.allocations == after.allocations
        checks.append(OracleCheck("safe_refusal_has_no_side_effects", refusal_clean,
            "Expected refusal left allocation state unchanged."))
    checks.extend(_check_invariants(after))
    return EvaluationResult(scenario.scenario_id, all(check.passed for check in checks), tuple(checks))

