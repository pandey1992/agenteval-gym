# AgentEval Gym

A local-first pytest toolkit for evaluating AI agents against stateful business workflows, database invariants, and side-effect safety.

M1 provides a SQLite resource-allocation environment, transaction-safe business services, a FastAPI mock API, and isolated pytest fixtures.

M2 adds a deterministic evaluation oracle and seven versioned resource-allocation benchmark scenarios. The oracle inspects database state independently of the agent-facing API; expected safe refusals count as successful outcomes.

## Requirements
Python 3.11+ and uv, or Docker with Compose. SQLite is embedded; no database server or paid service is needed.

## Run locally
```bash
uv sync --group dev
uv run pytest
```
The first sync resolves dependencies and creates `uv.lock`; commit that lockfile for reproducible development installs.

## Run with Docker
```bash
docker compose run --build --rm app
```
Docker runs the same test suite and is optional for local use.

## Start the mock API
```bash
uv run uvicorn agenteval.api:app --reload
```
The standalone API uses `./agenteval.db` by default. Set `AGENTEEVAL_DATABASE_URL` to choose another SQLite file.

See [docs/tdd-m1.md](docs/tdd-m1.md) for the M1 contracts and API surface.
See [docs/tdd-m2.md](docs/tdd-m2.md) for the oracle contract and scenario format.

