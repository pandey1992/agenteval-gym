# AgentEval Gym — M3 Technical Design

## Goal

Execute a validated scenario through an agent's HTTP tools, capture the tool trace, and evaluate the resulting business state with the M2 oracle.

## Execution boundary

- `Agent` is a provider-neutral async protocol. A future Grok or other model adapter implements this interface without changing the scenario runner.
- `ScriptedAgent` provides deterministic local execution for tests and costs no model/API calls.
- Agents receive only `ResourceTools`, a thin HTTPX client over FastAPI ASGI transport. They receive no SQLAlchemy session, engine, scenario expected state, or oracle result.
- Each scenario run creates a unique file-backed SQLite database, seeds the declared starting state, starts the app lifespan, executes the agent, captures the final snapshot, and invokes the deterministic oracle.
- The returned run record contains the verdict, named checks, final state snapshot, agent message, and tool trace.

## Tool trace

Each trace item records tool name, arguments, HTTP status, returned body, selected response headers, and whether a fault changed the agent-visible response. Secrets and database handles are not included.

## Fault injection

M3 supports one-shot deterministic faults for a selected tool:

- `fail_before_call`: return an injected 503 without sending the request.
- `lose_successful_response`: allow a successful API request to commit, then expose a synthetic 503 to the agent. A retry with the same idempotency key should replay the original response and create no duplicate allocation or event.

Faults are applied only inside the in-process test transport. They do not add network services or execute user-supplied code.

## Scope boundary

M3 provides the execution primitives and scripted adapter. Live model adapters, general pytest plugin packaging, traces persisted to disk, and human-readable reports remain future work. No model API key is required for M3 tests.

