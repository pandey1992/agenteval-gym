"""SQLAlchemy schema for the M1 resource-allocation domain."""
from datetime import datetime, timezone
from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (CheckConstraint("capacity_percentage BETWEEN 1 AND 100", name="ck_employee_capacity"),)
    employee_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str] = mapped_column(String(120), nullable=False)
    capacity_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (CheckConstraint("start_date <= end_date", name="ck_project_dates"),)
    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

class Allocation(Base):
    __tablename__ = "allocations"
    __table_args__ = (
        CheckConstraint("allocation_percentage BETWEEN 1 AND 100", name="ck_allocation_pct"),
        CheckConstraint("start_date <= end_date", name="ck_allocation_dates"),
        UniqueConstraint("employee_id", "project_id", "allocation_percentage", "start_date", "end_date", "status", name="uq_allocation_identical"),
        Index("ix_allocation_employee_dates", "employee_id", "status", "start_date", "end_date"),
    )
    allocation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.employee_id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id", ondelete="RESTRICT"), nullable=False)
    allocation_percentage: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

class BusinessPolicy(Base):
    __tablename__ = "business_policies"
    policy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    policy_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    policy_value: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

class AllocationEvent(Base):
    __tablename__ = "allocation_events"
    __table_args__ = (Index("ix_allocation_events_allocation", "allocation_id", "event_id"),)
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    allocation_id: Mapped[int] = mapped_column(ForeignKey("allocations.allocation_id", ondelete="RESTRICT"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    event_details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    idempotency_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_body: Mapped[dict] = mapped_column(JSON, nullable=False)
