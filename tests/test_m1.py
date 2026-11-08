from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
import pytest
from fastapi.testclient import TestClient
from agenteval.api import create_app
from agenteval.models import Allocation, AllocationEvent
from agenteval.services import BusinessError, create_allocation

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

def test_concurrent_requests_cannot_over_allocate(seeded_project):
    add_allocation(seeded_project)
    app, barrier = create_app(seeded_project.database_url), Barrier(2)
    payload = {"employee_id": "EMP001", "project_id": "PROJ002", "allocation_percentage": 30,
        "start_date": "2026-01-01", "end_date": "2026-03-31"}
    def request(_):
        with TestClient(app) as client:
            barrier.wait()
            return client.post("/allocations", json=payload).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(request, range(2)))
    assert sorted(statuses) == [201, 409]
    with seeded_project.session_factory() as session:
        total = sum(x.allocation_percentage for x in session.query(Allocation).filter_by(employee_id="EMP001", status="active"))
    assert total == 90
