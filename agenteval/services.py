"""Transaction-safe resource-allocation business rules."""
import hashlib
import json
import sqlite3
from datetime import date
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from agenteval.models import Allocation, AllocationEvent, Employee, IdempotencyRecord, Project

class BusinessError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code

def _begin_write(session: Session) -> None:
    # Reserve SQLite's sole writer slot before reading availability.
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")

def _raise_busy(exc: OperationalError) -> None:
    if isinstance(exc.orig, sqlite3.OperationalError) and any(x in str(exc.orig).lower() for x in ("locked", "busy")):
        raise BusinessError("database_busy", "The database is busy; retry the request.", 503) from exc
    raise exc

def get_employee(session: Session, employee_id: str) -> Employee:
    value = session.get(Employee, employee_id)
    if value is None:
        raise BusinessError("employee_not_found", "Employee not found.", 404)
    return value

def get_project(session: Session, project_id: str) -> Project:
    value = session.get(Project, project_id)
    if value is None:
        raise BusinessError("project_not_found", "Project not found.", 404)
    return value

def _peak_allocated_percentage(session: Session, employee_id: str, start_date: date, end_date: date) -> int:
    """Return the greatest simultaneous active allocation on any day in the interval."""
    rows = session.scalars(select(Allocation).where(
        Allocation.employee_id == employee_id,
        Allocation.status == "active",
        Allocation.start_date <= end_date,
        Allocation.end_date >= start_date,
    )).all()
    # Sweep integer day boundaries. The end boundary is exclusive, so adjacent
    # allocations ending/starting on consecutive days do not overlap.
    events: dict[int, int] = {}
    interval_end = end_date.toordinal() + 1
    for row in rows:
        left = max(start_date, row.start_date).toordinal()
        right = min(end_date, row.end_date).toordinal() + 1
        events[left] = events.get(left, 0) + row.allocation_percentage
        events[right] = events.get(right, 0) - row.allocation_percentage
    current = peak = 0
    for boundary in sorted(events):
        current += events[boundary]
        if boundary < interval_end:
            peak = max(peak, current)
    return peak


def _allocation_payload(allocation: Allocation) -> dict:
    """Capture the original successful response for stable idempotent replay."""
    return {
        "allocation_id": allocation.allocation_id,
        "employee_id": allocation.employee_id,
        "project_id": allocation.project_id,
        "allocation_percentage": allocation.allocation_percentage,
        "start_date": allocation.start_date.isoformat(),
        "end_date": allocation.end_date.isoformat(),
        "status": allocation.status,
    }


def get_availability(session: Session, employee_id: str, start_date: date, end_date: date) -> dict:
    if start_date > end_date:
        raise BusinessError("invalid_date_range", "start_date must be on or before end_date.", 400)
    employee = get_employee(session, employee_id)
    if employee.status != "active":
        raise BusinessError("employee_inactive", "Employee is not active.", 409)
    allocated = _peak_allocated_percentage(session, employee_id, start_date, end_date)
    return {"employee_id": employee_id, "capacity_percentage": employee.capacity_percentage,
        "allocated_percentage": allocated, "available_percentage": max(employee.capacity_percentage - allocated, 0),
        "start_date": start_date, "end_date": end_date}

def create_allocation(session: Session, *, employee_id: str, project_id: str,
    allocation_percentage: int, start_date: date, end_date: date,
    idempotency_key: str | None = None) -> tuple[Allocation, bool]:
    if not 1 <= allocation_percentage <= 100:
        raise BusinessError("invalid_allocation_percentage", "allocation_percentage must be between 1 and 100.", 400)
    if start_date > end_date:
        raise BusinessError("invalid_date_range", "start_date must be on or before end_date.", 400)
    payload = {"employee_id": employee_id, "project_id": project_id, "allocation_percentage": allocation_percentage,
        "start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    try:
        with session.begin():
            _begin_write(session)
            if idempotency_key:
                prior = session.get(IdempotencyRecord, idempotency_key)
                if prior:
                    if prior.request_hash != digest:
                        raise BusinessError("idempotency_key_reused", "This idempotency key was used for another request.", 409)
                    snapshot = dict(prior.response_body)
                    snapshot["start_date"] = date.fromisoformat(snapshot["start_date"])
                    snapshot["end_date"] = date.fromisoformat(snapshot["end_date"])
                    return Allocation(**snapshot), True
            employee, project = get_employee(session, employee_id), get_project(session, project_id)
            if employee.status != "active":
                raise BusinessError("employee_inactive", "Employee is not active.", 409)
            if project.status != "active":
                raise BusinessError("project_inactive", "Project is not active.", 409)
            if start_date < project.start_date or end_date > project.end_date:
                raise BusinessError("allocation_outside_project_dates", "Allocation dates must fit within the project dates.", 409)
            duplicate = session.scalar(select(Allocation).where(
                Allocation.employee_id == employee_id, Allocation.project_id == project_id,
                Allocation.allocation_percentage == allocation_percentage, Allocation.start_date == start_date,
                Allocation.end_date == end_date, Allocation.status == "active"))
            if duplicate:
                raise BusinessError("duplicate_allocation", "This allocation already exists.", 409)
            availability = get_availability(session, employee_id, start_date, end_date)
            if allocation_percentage > availability["available_percentage"]:
                raise BusinessError("capacity_conflict", "The allocation would exceed available capacity.", 409)
            allocation = Allocation(employee_id=employee_id, project_id=project_id,
                allocation_percentage=allocation_percentage, start_date=start_date, end_date=end_date, status="active")
            session.add(allocation)
            session.flush()
            session.add(AllocationEvent(allocation_id=allocation.allocation_id, event_type="created",
                event_details={"allocation_percentage": allocation_percentage}))
            if idempotency_key:
                session.add(IdempotencyRecord(idempotency_key=idempotency_key, request_hash=digest,
                    response_body=_allocation_payload(allocation)))
            return allocation, False
    except OperationalError as exc:
        _raise_busy(exc)

def cancel_allocation(session: Session, allocation_id: int) -> Allocation:
    try:
        with session.begin():
            _begin_write(session)
            allocation = session.get(Allocation, allocation_id)
            if allocation is None:
                raise BusinessError("allocation_not_found", "Allocation not found.", 404)
            if allocation.status != "cancelled":
                allocation.status = "cancelled"
                session.add(AllocationEvent(allocation_id=allocation_id, event_type="cancelled", event_details={}))
            return allocation
    except OperationalError as exc:
        _raise_busy(exc)
