# AgentEval Gym — M1 Technical Design

## Goal
Establish the SQLite-backed resource-allocation environment for later benchmarks. Agents use HTTP endpoints; they receive no database session or oracle access.

## Scope
M1 includes employee, project, allocation, business-policy, allocation-event and idempotency tables; SQLAlchemy services; a FastAPI mock API; isolated pytest fixtures; and Docker Compose support.

## Frozen rules
- Capacity for a requested range is based on the peak simultaneous active allocation on any day in that range, not the sum of every allocation that intersects any part of it.
- Capacity-changing writes acquire `BEGIN IMMEDIATE` before checking availability. SQLite still has one writer; WAL is not treated as multi-writer support.
- File databases use WAL, foreign keys, and a 5000 ms busy timeout. Busy/locked errors map to HTTP 503 with `Retry-After: 1`.
- Over-capacity attempts return 409 `capacity_conflict` with no state change.
- Identical active allocations return 409 `duplicate_allocation`; they are never merged.
- The same `Idempotency-Key` and payload replays the original response snapshot, even if the allocation later changes. A changed payload with that key returns 409 `idempotency_key_reused`.
- Allocation dates must fit the project dates. Missing entities return 404; inactive entities and business conflicts return 409.
- Creation and cancellation append allocation events. DELETE performs a soft cancellation.
- A safe refusal is a passing benchmark outcome when a request violates a business rule.

## Test isolation
The `project_env` fixture creates a fresh file database in pytest's `tmp_path`, builds a new schema, and disposes the engine. Each API request gets a new SQLAlchemy session. The concurrency test uses a file-backed database.

## API
- `GET /health`, `GET /employees/{id}`, `GET /projects/{id}`
- `GET /employees/{id}/availability?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`
- `GET /allocations`, `POST /allocations` (optional idempotency header)
- `DELETE /allocations/{id}` (soft cancellation)

## Later milestones
Scenario loading, agent adapters, oracle/scoring, fault injection, traces and reports are deferred.
