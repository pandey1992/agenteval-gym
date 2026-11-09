"""Validated, versioned scenario definitions used by the M2 oracle."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class EmployeeSeed(BaseModel):
    employee_id: str
    name: str
    department: str
    capacity_percentage: int = Field(ge=1, le=100)
    status: str = "active"


class ProjectSeed(BaseModel):
    project_id: str
    project_name: str
    start_date: str
    end_date: str
    status: str = "active"


class AllocationSeed(BaseModel):
    employee_id: str
    project_id: str
    allocation_percentage: int = Field(ge=1, le=100)
    start_date: str
    end_date: str
    status: str = "active"


class AllocationRequest(BaseModel):
    employee_id: str
    project_id: str
    allocation_percentage: int = Field(ge=1, le=100)
    start_date: str
    end_date: str


class InitialState(BaseModel):
    employees: list[EmployeeSeed] = Field(default_factory=list)
    projects: list[ProjectSeed] = Field(default_factory=list)
    allocations: list[AllocationSeed] = Field(default_factory=list)


class ExpectedOutcome(BaseModel):
    status_code: int
    error_code: str | None = None
    final_allocations: list[AllocationSeed] = Field(default_factory=list)
    event_delta: int = Field(ge=0)


class ScenarioSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    title: str
    user_instruction: str
    request: AllocationRequest
    initial_state: InitialState
    state_changes_before_action: list[AllocationSeed] = Field(default_factory=list)
    expected: ExpectedOutcome
    safe_refusal: bool = False


def load_scenarios(directory: str | Path | None = None) -> list[ScenarioSpec]:
    """Load and validate every TC*.json scenario in stable filename order."""
    root = Path(directory) if directory else Path(__file__).resolve().parents[2] / "benchmarks" / "resource_allocation"
    scenarios = [ScenarioSpec.model_validate_json(path.read_text(encoding="utf-8")) for path in sorted(root.glob("TC*.json"))]
    if not scenarios:
        raise ValueError(f"No benchmark scenarios found in {root}")
    ids = [scenario.scenario_id for scenario in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Scenario IDs must be unique in {root}")
    return scenarios

