"""One-shot, deterministic faults for repeatable agent regression tests."""

from dataclasses import dataclass
from typing import Literal


FaultMode = Literal["fail_before_call", "lose_successful_response"]


@dataclass(frozen=True)
class FaultPlan:
    mode: FaultMode
    tool_name: str = "assign_resource"
    count: int = 1
    status_code: int = 503
    error_code: str = "injected_service_unavailable"
    message: str = "A deterministic test fault was injected."


class FaultInjector:
    """Apply a configured fault a fixed number of times, then pass calls through."""

    def __init__(self, plan: FaultPlan | None = None) -> None:
        if plan is not None and plan.count < 1:
            raise ValueError("FaultPlan.count must be at least one.")
        self.plan = plan
        self.remaining = plan.count if plan else 0

    def _matches(self, tool_name: str) -> bool:
        return self.plan is not None and self.remaining > 0 and self.plan.tool_name == tool_name

    def fail_before_call(self, tool_name: str) -> bool:
        if self._matches(tool_name) and self.plan.mode == "fail_before_call":
            self.remaining -= 1
            return True
        return False

    def lose_response(self, tool_name: str, status_code: int) -> bool:
        if self._matches(tool_name) and self.plan.mode == "lose_successful_response" and status_code < 400:
            self.remaining -= 1
            return True
        return False

    def error_response(self) -> dict:
        if self.plan is None:
            raise RuntimeError("No fault plan is configured.")
        return {"error": {"code": self.plan.error_code, "message": self.plan.message}}

    @property
    def fault_status_code(self) -> int:
        if self.plan is None:
            raise RuntimeError("No fault plan is configured.")
        return self.plan.status_code

