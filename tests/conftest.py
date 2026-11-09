from dataclasses import dataclass
from datetime import date
import pytest
from fastapi.testclient import TestClient
from agenteval.api import create_app
from agenteval.database import create_schema, make_engine, make_session_factory
from agenteval.models import Employee, Project

@dataclass
class ProjectEnvironment:
    database_url: str
    engine: object
    session_factory: object

@pytest.fixture
def project_env(tmp_path):
    url = f"sqlite:///{tmp_path / 'benchmark.db'}"
    engine = make_engine(url)
    create_schema(engine)
    env = ProjectEnvironment(url, engine, make_session_factory(engine))
    try:
        yield env
    finally:
        engine.dispose()

@pytest.fixture
def agent_runner(project_env):
    with TestClient(create_app(project_env.database_url)) as client:
        yield client

@pytest.fixture
def seeded_project(project_env):
    with project_env.session_factory() as session:
        session.add_all([
            Employee(employee_id="EMP001", name="Asha Rao", department="Engineering",
                capacity_percentage=100, status="active"),
            Project(project_id="PROJ001", project_name="Alpha",
                start_date=date(2025, 1, 1), end_date=date(2027, 12, 31), status="active"),
            Project(project_id="PROJ002", project_name="Beta",
                start_date=date(2025, 1, 1), end_date=date(2027, 12, 31), status="active"),
        ])
        session.commit()
    return project_env
