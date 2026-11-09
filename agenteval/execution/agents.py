"""Provider-neutral agent interface and deterministic scripted test agent."""

from dataclasses import dataclass, field
from typing import Protocol, Sequence

from agenteval.execution.tools import ResourceTools, ToolResponse


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict = field(default_factory=dict)
    idempotency_key: str | None = None


@dataclass(frozen=True)
class AgentRunResult:
    final_message: str
    terminal_response: ToolResponse | None


class Agent(Protocol):
    async def run(self, instruction: str, tools: ResourceTools) -> AgentRunResult:
        """Execute the instruction using only the provided agent-facing tools."""
        ...


class ScriptedAgent:
    """Small deterministic agent used to exercise scenarios without model API calls."""

    def __init__(self, calls: Sequence[ToolCall], *, retry_status_codes: tuple[int, ...] = (503,),
        max_retries: int = 0) -> None:
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative.")
        self.calls = tuple(calls)
        self.retry_status_codes = retry_status_codes
        self.max_retries = max_retries

    async def run(self, instruction: str, tools: ResourceTools) -> AgentRunResult:
        terminal: ToolResponse | None = None
        for call in self.calls:
            for attempt in range(self.max_retries + 1):
                terminal = await tools.call(call.name, call.arguments, call.idempotency_key)
                if terminal.status_code not in self.retry_status_codes or attempt == self.max_retries:
                    break
        summary = "No tool call was configured." if terminal is None else f"Final tool response: HTTP {terminal.status_code}."
        return AgentRunResult(summary, terminal)

