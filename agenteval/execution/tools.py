"""Agent-facing HTTP tools and request trace capture."""

from dataclasses import dataclass, field
from typing import Awaitable, Callable

import httpx

from agenteval.execution.faults import FaultInjector


@dataclass(frozen=True)
class ToolResponse:
    status_code: int
    body: dict | list | None
    headers: dict[str, str] = field(default_factory=dict)
    fault_injected: bool = False


@dataclass(frozen=True)
class ToolTrace:
    tool_name: str
    arguments: dict
    status_code: int
    body: dict | list | None
    headers: dict[str, str]
    fault_injected: bool


BeforeToolCall = Callable[[str], Awaitable[None]]


class ResourceTools:
    """HTTP-only resource API available to agents; no database or oracle handle is exposed."""

    def __init__(self, client: httpx.AsyncClient, *, fault_injector: FaultInjector | None = None,
        before_tool_call: BeforeToolCall | None = None) -> None:
        self._client = client
        self._faults = fault_injector or FaultInjector()
        self._before_tool_call = before_tool_call
        self.trace: list[ToolTrace] = []

    async def call(self, tool_name: str, arguments: dict,
        idempotency_key: str | None = None) -> ToolResponse:
        args = dict(arguments)
        if self._before_tool_call is not None:
            await self._before_tool_call(tool_name)

        if self._faults.fail_before_call(tool_name):
            return self._record(tool_name, args, ToolResponse(
                self._faults.fault_status_code, self._faults.error_response(), fault_injected=True))

        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        if tool_name == "get_employee":
            response = await self._client.get(f"/employees/{args['employee_id']}")
        elif tool_name == "get_project":
            response = await self._client.get(f"/projects/{args['project_id']}")
        elif tool_name == "get_availability":
            response = await self._client.get(
                f"/employees/{args['employee_id']}/availability",
                params={"start_date": args["start_date"], "end_date": args["end_date"]},
            )
        elif tool_name == "list_allocations":
            response = await self._client.get("/allocations")
        elif tool_name == "assign_resource":
            response = await self._client.post("/allocations", json=args, headers=headers)
        elif tool_name == "cancel_resource":
            response = await self._client.delete(f"/allocations/{args['allocation_id']}")
        else:
            raise ValueError(f"Unknown resource tool: {tool_name}")

        body = response.json() if response.content else None
        safe_headers = {name: response.headers[name] for name in ("idempotency-replayed", "retry-after")
            if name in response.headers}
        observed = ToolResponse(response.status_code, body, safe_headers)
        if self._faults.lose_response(tool_name, observed.status_code):
            observed = ToolResponse(self._faults.fault_status_code, self._faults.error_response(),
                fault_injected=True)
        return self._record(tool_name, args, observed)

    def _record(self, tool_name: str, arguments: dict, response: ToolResponse) -> ToolResponse:
        self.trace.append(ToolTrace(tool_name, arguments, response.status_code,
            response.body, response.headers, response.fault_injected))
        return response

