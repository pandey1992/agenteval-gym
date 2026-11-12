"""Reusable pytest fixtures and report option for AgentEval Gym projects."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest

from agenteval.database import create_schema, make_engine, make_session_factory
from agenteval.evaluation.scenarios import ScenarioSpec, load_scenarios
from agenteval.execution.agents import Agent
from agenteval.execution.faults import FaultPlan
from agenteval.execution.runner import ScenarioRunResult, ScenarioRunner
from agenteval.reporting import write_html_report, write_json_report


_RESULTS_KEY: pytest.StashKey[list[ScenarioRunResult]] = pytest.StashKey()


@dataclass(frozen=True)
class ProjectEnvironment:
    database_url: str
    engine: object
    session_factory: object


class AgentRunnerFixture:
    """Synchronous pytest wrapper around the async isolated scenario runner."""

    def __init__(self, tmp_path: Path, results: list[ScenarioRunResult]) -> None:
        self._tmp_path = tmp_path
        self._results = results
        self._runner = ScenarioRunner()

    @property
    def results(self) -> tuple[ScenarioRunResult, ...]:
        return tuple(self._results)

    def run(self, scenario: ScenarioSpec, agent: Agent, *,
            database_path: str | Path | None = None,
            fault_plan: FaultPlan | None = None) -> ScenarioRunResult:
        path = Path(database_path) if database_path else self._tmp_path / f"{scenario.scenario_id}-{uuid4().hex}.db"
        result = asyncio.run(self._runner.run(scenario, agent, database_path=path, fault_plan=fault_plan))
        self._results.append(result)
        return result


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("agenteval-gym")
    group.addoption("--agenteval-report", metavar="PATH", default=None,
                    help="write scenario results as JSON to PATH")
    group.addoption("--agenteval-html-report", metavar="PATH", default=None,
                    help="write a standalone HTML evaluation report to PATH")


def pytest_configure(config: pytest.Config) -> None:
    config.stash[_RESULTS_KEY] = []


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    path = session.config.getoption("--agenteval-report")
    html_path = session.config.getoption("--agenteval-html-report")
    results = session.config.stash[_RESULTS_KEY]
    if not path and not html_path:
        return
    outputs = []
    if path:
        outputs.append(write_json_report(results, path))
    if html_path:
        outputs.append(write_html_report(results, html_path))
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter:
        reporter.write_sep("=", f"AgentEval Gym: {sum(item.passed for item in results)}/{len(results)} scenarios passed; reports: {', '.join(map(str, outputs))}")


@pytest.fixture
def project_env(tmp_path: Path):
    """Provide a fresh SQLite database, schema and session factory per test."""
    database_url = f"sqlite:///{(tmp_path / 'project.db').as_posix()}"
    engine = make_engine(database_url)
    create_schema(engine)
    environment = ProjectEnvironment(database_url, engine, make_session_factory(engine))
    try:
        yield environment
    finally:
        engine.dispose()


@pytest.fixture
def agenteval_scenarios() -> list[ScenarioSpec]:
    """Load and validate the packaged benchmark scenarios."""
    return load_scenarios()


@pytest.fixture
def agent_runner(tmp_path: Path, request: pytest.FixtureRequest) -> AgentRunnerFixture:
    """Run scenarios in isolated databases and collect results for JSON reporting."""
    return AgentRunnerFixture(tmp_path, request.config.stash[_RESULTS_KEY])
