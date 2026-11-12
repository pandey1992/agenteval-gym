# AgentEval Gym

A local-first pytest toolkit for evaluating AI agents against stateful business workflows, database invariants, and side-effect safety.

M1 provides a SQLite resource-allocation environment, transaction-safe business services, a FastAPI mock API, and isolated pytest fixtures.

M2 adds a deterministic evaluation oracle and seven versioned resource-allocation benchmark scenarios. The oracle inspects database state independently of the agent-facing API; expected safe refusals count as successful outcomes.

M3 adds a framework-neutral scenario runner, HTTP tool wrappers, tool-call traces, and deterministic fault injection for retries.

M4 packages reusable pytest fixtures and JSON evaluation reports, with a GitHub Actions test workflow.

## Requirements
Python 3.11+ and uv, or Docker with Compose. SQLite is embedded; no database server or paid service is needed.

## Run locally
```bash
uv sync --group dev
uv run pytest
```
The committed `uv.lock` keeps development installs reproducible.

## Run with Docker
```bash
docker compose run --build --rm app
```
Docker runs the same test suite and is optional for local use.

## Use the pytest fixtures
Install the project and its development dependencies with `uv sync --group dev`. The installed pytest plugin provides `project_env` (a fresh SQLite schema), `agenteval_scenarios` (validated benchmark definitions), and `agent_runner` (a synchronous fixture for running an async agent against one isolated scenario).

```python
def test_agent_handles_capacity_conflict(agent_runner, agenteval_scenarios):
    scenario = next(item for item in agenteval_scenarios if item.scenario_id == "TC002")
    result = agent_runner.run(scenario, my_agent)
    assert result.passed
```

Write a compact machine-readable summary of all scenario runs made by the plugin fixtures with:

```bash
uv run pytest --agenteval-report artifacts/agenteval-report.json
```

For a visual report you can open in a browser, add `--agenteval-html-report artifacts/agenteval-report.html`. The HTML report shows scenario and oracle pass rates, HTTP 2xx tool-call rate, diagnostics, tool traces, and allocation state changes. It is a standalone local file and does not include database credentials or database files.

## Start the mock API
```bash
uv run uvicorn agenteval.api:app --reload
```
The standalone API uses `./agenteval.db` by default. Set `AGENTEEVAL_DATABASE_URL` to choose another SQLite file.

See [docs/tdd-m1.md](docs/tdd-m1.md) for the M1 contracts and API surface.
See [docs/tdd-m2.md](docs/tdd-m2.md) for the oracle contract and scenario format.
See [docs/tdd-m3.md](docs/tdd-m3.md) for the execution and fault-injection contract.
See [docs/tdd-m4.md](docs/tdd-m4.md) for pytest fixtures, reporting, and CI behavior.
