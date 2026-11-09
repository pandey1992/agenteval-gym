# AgentEval Gym — M2 Technical Design

## Goal

Evaluate agent outcomes using deterministic business-state checks. The oracle reads a separate database snapshot and is never exposed through the mock API or agent-facing tools.

## Oracle inputs and outputs

`evaluate_scenario` receives a validated scenario definition, a snapshot immediately before the agent action, a snapshot afterward, and the observed HTTP status/error code. It returns named checks with pass/fail details. It does not call an LLM or rely on the agent's success message.

The snapshot contains employees, projects, allocations, business policies and allocation events. Snapshot reads temporarily enable SQLite `query_only` on the dedicated oracle session connection and restore it before returning that connection to the pool.

## Checks

- The observed HTTP status and error code match the scenario.
- Final allocation business records match the complete expected allocation state.
- Employee, project and policy records remain unchanged by the agent action.
- The number of new allocation events matches the expected delta.
- Every allocation references an existing employee/project, has valid dates and percentages, and fits within project dates.
- Peak simultaneous active allocation for each employee does not exceed declared capacity.
- Scenarios marked `safe_refusal` pass when the expected business refusal occurs and allocation state remains unchanged.

The capacity invariant is recomputed in the oracle with an independent date-boundary sweep; it does not call the allocation service's availability implementation.

## Initial scenarios

| ID | Case | Expected result |
| --- | --- | --- |
| TC001 | Assign an available employee | HTTP 201; one correct allocation and one creation event |
| TC002 | Request exceeds capacity | Safe HTTP 409 `capacity_conflict`; no allocation or event change |
| TC003 | Employee does not exist | Safe HTTP 404 `employee_not_found`; no state change |
| TC004 | Exact active allocation already exists | Safe HTTP 409 `duplicate_allocation`; no state change |
| TC005 | Availability becomes stale before assignment | Safe HTTP 409 `capacity_conflict`; external state retained and no agent allocation added |
| TC006 | Assign across two separate 60% intervals | HTTP 201 at the 60% peak; do not sum non-overlapping assignments |
| TC007 | Requested dates start before the project | Safe HTTP 409 `allocation_outside_project_dates`; no state change |

Scenario JSON stores the user instruction, request, initial state, controlled state changes before the action, and exact expected result. `load_scenarios` validates these files and rejects duplicate IDs.

For TC005, the fixture first records an availability result with 50% capacity free, then inserts a 20% allocation before the attempted 40% assignment. The service must recheck inside its write transaction and refuse safely.

TC006 proves that capacity is based on peak simultaneous usage: existing 60% allocations occupy January 1–15 and January 16–31 respectively. A new 40% allocation across all of January is valid because peak load is exactly 100%. TC007 covers project-date validation independently of employee availability.

## M2 boundary

M2 provides scenario data, validation, snapshotting, invariants and deterministic verdicts. It does not yet schedule arbitrary agents, inject runtime faults, create traces, or generate reports; those belong to M3/M4.

