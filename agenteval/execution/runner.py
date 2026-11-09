"""Isolated scenario execution from agent tools through the deterministic oracle."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
from sqlalchemy.orm import sessionmaker

from agenteval.database import create_schema, make_engine, make_session_factory
from agenteval.evaluation.oracle import EvaluationResult, ObservedOutcome, StateSnapshot, capture_snapshot, evaluate_scenario
from agenteval.evaluation.scenarios import ScenarioSpec
from agenteval.execution.agents import Agent, AgentRunResult
from agenteval.execution.faults import FaultInjector, FaultPlan
from agenteval.execution.tools import ResourceTools, ToolTrace
from agenteval.models import Allocation, AllocationEvent, Employee, Project


@dataclass(frozen=True)
class ScenarioRunResult:
    scenario_id: str
    evaluation: EvaluationResult
    agent_result: AgentRunResult
    tool_trace: tuple[ToolTrace, ...]
    final_state: StateSnapshot

    @property
    def passed(self) -> bool:
        return self.evaluation.passed


class ScenarioRunner:
    """Run one scenario with an isolated file-backed SQLite database and ASGI API."""

    async def run(self, scenario: ScenarioSpec, agent: Agent, *, database_path: str | Path,
        fault_plan: FaultPlan | None = None) -> ScenarioRunResult:
        path = Path(database_path).resolve()
        if path.exists():
            raise FileExistsError(f"Scenario database already exists; use a unique path: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{path.as_posix()}"

        oracle_engine = make_engine(database_url)
        sessions = make_session_factory(oracle_engine)
        try:
            create_schema(oracle_engine)
            self._seed(sessions, scenario)
            from agenteval.api import create_app

            app = create_app(database_url)

            def snapshot() -> StateSnapshot:
                with sessions() as session:
                    return capture_snapshot(session)

            before_action = snapshot()
            state_changes_applied = False

            async def before_tool_call(tool_name: str) -> None:
                nonlocal before_action, state_changes_applied
                if tool_name != "assign_resource" or state_changes_applied:
                    return
                self._apply_state_changes(sessions, scenario)
                before_action = snapshot()
                state_changes_applied = True

            injector = FaultInjector(fault_plan)
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://agenteval.local") as client:
                    tools = ResourceTools(client, fault_injector=injector, before_tool_call=before_tool_call)
                    agent_result = await agent.run(scenario.user_instruction, tools)
                    trace = tuple(tools.trace)
                    after = snapshot()
            response = agent_result.terminal_response
            if response is None:
                outcome = ObservedOutcome(status_code=0, error_code="no_tool_response")
            else:
                error = response.body.get("error") if isinstance(response.body, dict) else None
                outcome = ObservedOutcome(response.status_code, error.get("code") if isinstance(error, dict) else None)
            verdict = evaluate_scenario(scenario, before_action, after, outcome)
            return ScenarioRunResult(scenario.scenario_id, verdict, agent_result, trace, after)
        finally:
            oracle_engine.dispose()

    @staticmethod
    def _seed(sessions: sessionmaker, scenario: ScenarioSpec) -> None:
        with sessions() as session:
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

    @staticmethod
    def _apply_state_changes(sessions: sessionmaker, scenario: ScenarioSpec) -> None:
        if not scenario.state_changes_before_action:
            return
        with sessions() as session:
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

