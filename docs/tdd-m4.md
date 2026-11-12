# AgentEval Gym — M4 Technical Design

## Goal

Make the M1–M3 evaluator convenient to use from ordinary pytest suites, produce reviewable machine-readable results, and run the same locked test setup in CI and Docker.

## Pytest plugin

The package registers `agenteval.pytest_plugin` through the `pytest11` entry point. After installing the project, pytest exposes:

- `project_env`: a fresh file-backed SQLite database, schema, engine and session factory for a test.
- `agenteval_scenarios`: validated scenario definitions in stable order.
- `agent_runner`: a synchronous wrapper around the async M3 runner. Each run receives a unique database in pytest's temporary directory. Run results are collected for optional report output.

The fixture is synchronous to work with standard pytest tests. Async test frameworks can call `ScenarioRunner.run` directly.

## JSON report

`--agenteval-report PATH` writes a UTF-8 JSON document with a versioned schema, total/pass/fail counts, per-scenario verdicts, named oracle checks, agent final message, tool traces and final-state row counts. `--agenteval-html-report PATH` writes a standalone local dashboard with scenario pass rate, HTTP 2xx tool-call rate, oracle-check rate, diagnostics, traces and allocation state changes. Both create parent directories and can be requested together. They omit raw database credentials and database files. The terminal summary points to generated files.

The report only contains scenario runs made through the `agent_runner` fixture. Direct calls to `ScenarioRunner` are not automatically collected.

## Docker and CI

Docker installs from the committed `uv.lock` using locked mode, keeping its dependency set aligned with local `uv sync --locked --group dev`. GitHub Actions uses the same locked sync and runs pytest on pushes and pull requests. Docker remains optional for local uv/pytest workflows.

## Scope boundary

M4 adds no hosted service, model API dependency, database server or proprietary evaluation format. Scenario execution and correctness remain independent of pytest; pytest provides integration and report collection.
