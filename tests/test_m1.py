from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
import pytest
from fastapi.testclient import TestClient
from agenteval.api import create_app
from agenteval.models import Allocation, AllocationEvent
from agenteval.services import BusinessError, create_allocation, get_availability

START, END = date(2026, 1, 1), date(2026, 3, 31)

def add_allocation(env, project="PROJ001", percentage=60):
    with env.session_factory() as session:
        session.add(Allocation(employee_id="EMP001", project_id=project,
            allocation_percentage=percentage, start_date=START, end_date=END, status="active"))
        session.commit()

def test_over_capacity_rolls_back_without_side_effects(seeded_project):
    add_allocation(seeded_project)
    with seeded_project.session_factory() as session:
        with pytest.raises(BusinessError) as error:
            create_allocation(session, employee_id="EMP001", project_id="PROJ002",
                allocation_percentage=50, start_date=START, end_date=END)
    assert error.value.code == "capacity_conflict"
    with seeded_project.session_factory() as session:
        assert session.query(Allocation).count() == 1
        assert session.query(AllocationEvent).count() == 0

def test_non_overlapping_dates_have_independent_capacity(seeded_project):
    add_allocation(seeded_project)
    with seeded_project.session_factory() as session:
        value, replayed = create_allocation(session, employee_id="EMP001", project_id="PROJ002",
            allocation_percentage=100, start_date=date(2026, 4, 1), end_date=date(2026, 6, 30))
    assert value.status == "active" and not replayed

def test_capacity_uses_peak_concurrent_usage_for_split_ranges(seeded_project):
    with seeded_project.session_factory() as session:
        session.add_all([
            Allocation(employee_id="EMP001", project_id="PROJ001", allocation_percentage=60,
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 15), status="active"),
            Allocation(employee_id="EMP001", project_id="PROJ002", allocation_percentage=60,
                start_date=date(2026, 1, 16), end_date=date(2026, 1, 31), status="active"),
        ])
        session.commit()
    with seeded_project.session_factory() as session:
        availability = get_availability(session, "EMP001", START, END)
    assert availability["allocated_percentage"] == 60
    assert availability["available_percentage"] == 40
    with seeded_project.session_factory() as session:
        allocation, replayed = create_allocation(session, employee_id="EMP001",
            project_id="PROJ001", allocation_percentage=40, start_date=START, end_date=END)
    assert allocation.status == "active" and not replayed


def test_duplicate_and_idempotency_contracts(seeded_project):
    args = dict(employee_id="EMP001", project_id="PROJ001", allocation_percentage=30,
        start_date=START, end_date=END, idempotency_key="m1-request")
    with seeded_project.session_factory() as session:
        first, replay1 = create_allocation(session, **args)
    with seeded_project.session_factory() as session:
        replay, replay2 = create_allocation(session, **args)
    assert first.allocation_id == replay.allocation_id and not replay1 and replay2
    with seeded_project.session_factory() as session:
        with pytest.raises(BusinessError) as error:
            create_allocation(session, **{**args, "allocation_percentage": 40})
    assert error.value.code == "idempotency_key_reused"
    with seeded_project.session_factory() as session:
        assert session.query(AllocationEvent).count() == 1

def test_api_returns_safe_conflict(seeded_project, agent_runner):
    add_allocation(seeded_project, percentage=80)
    response = agent_runner.post("/allocations", json={
        "employee_id": "EMP001", "project_id": "PROJ002", "allocation_percentage": 30,
        "start_date": "2026-01-01", "end_date": "2026-03-31"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "capacity_conflict"

def test_idempotent_retry_replays_original_response_after_cancellation(seeded_project, agent_runner):
    payload = {"employee_id": "EMP001", "project_id": "PROJ001", "allocation_percentage": 30,
        "start_date": "2026-01-01", "end_date": "2026-03-31"}
    headers = {"Idempotency-Key": "stable-after-cancel"}
    original = agent_runner.post("/allocations", json=payload, headers=headers)
    assert original.status_code == 201
    allocation_id = original.json()["allocation_id"]
    cancelled = agent_runner.delete(f"/allocations/{allocation_id}")
    assert cancelled.status_code == 204
    replay = agent_runner.post("/allocations", json=payload, headers=headers)
    assert replay.status_code == 201
    assert replay.json() == original.json()


def test_concurrent_requests_cannot_over_allocate(seeded_project):
    add_allocation(seeded_project)
    app, barrier = create_app(seeded_project.database_url), Barrier(2)
    payload = {"employee_id": "EMP001", "project_id": "PROJ002", "allocation_percentage": 30,
        "start_date": "2026-01-01", "end_date": "2026-03-31"}
    with TestClient(app) as client:
        def request(_):
            barrier.wait()
            return client.post("/allocations", json=payload).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(request, range(2)))
    assert sorted(statuses) == [201, 409]
    with seeded_project.session_factory() as session:
        total = sum(x.allocation_percentage for x in session.query(Allocation).filter_by(employee_id="EMP001", status="active"))
    assert total == 90
