from __future__ import annotations

from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ValidationError

from relay.domain.models import ApprovalState, ToolErrorCategory, ToolResult, ToolRisk
from relay.network.simulator import NetworkError, NetworkSimulator


class ToolError(ValueError):
    pass


class ApprovalRequiredError(PermissionError):
    pass


class Tool[InputT: BaseModel](ABC):
    name: str
    input_model: type[InputT]
    risk = ToolRisk.READ_ONLY
    retryable = False

    def __init__(self, simulator: NetworkSimulator) -> None:
        self.simulator = simulator

    @abstractmethod
    def run(self, inputs: InputT) -> dict[str, Any]: ...


class ToolRegistry:
    def __init__(self, tools: list[Tool[Any]], max_retries: int = 1) -> None:
        if not tools:
            raise ValueError("at least one tool is required")
        self._tools = {tool.name: tool for tool in tools}
        self.simulator = tools[0].simulator
        self.max_retries = max_retries

    def is_state_changing(self, name: str) -> bool:
        return self.risk(name) is not ToolRisk.READ_ONLY

    def risk(self, name: str) -> ToolRisk:
        return self._get(name).risk

    def schemas(self) -> dict[str, dict[str, Any]]:
        return {name: tool.input_model.model_json_schema() for name, tool in self._tools.items()}

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        approved: bool | ApprovalState = False,
    ) -> ToolResult:
        started = perf_counter()
        tool = self._get(name)
        is_approved = approved is True or approved is ApprovalState.APPROVED
        if tool.risk is not ToolRisk.READ_ONLY and not is_approved:
            raise ApprovalRequiredError(
                f"tool '{name}' requires explicit approval tied to the exact action"
            )
        try:
            inputs = tool.input_model.model_validate(arguments)
        except ValidationError as exc:
            return self._failure(started, ToolErrorCategory.INVALID_ARGUMENT, str(exc))
        retries = 0
        while True:
            try:
                if tool.simulator.consume_failure(name):
                    raise TimeoutError(f"injected timeout for {name}")
                output = tool.run(inputs)
                return ToolResult(
                    success=True,
                    output=output,
                    retry_count=retries,
                    duration_ms=(perf_counter() - started) * 1000,
                )
            except TimeoutError as exc:
                if tool.retryable and retries < self.max_retries:
                    retries += 1
                    continue
                return self._failure(started, ToolErrorCategory.TOOL_TIMEOUT, str(exc), retries)
            except NetworkError as exc:
                category = (
                    ToolErrorCategory.DEVICE_NOT_FOUND
                    if "unknown device" in str(exc)
                    else ToolErrorCategory.INVALID_ARGUMENT
                )
                return self._failure(started, category, str(exc), retries)
            except PermissionError as exc:
                return self._failure(
                    started, ToolErrorCategory.PERMISSION_DENIED, str(exc), retries
                )

    @staticmethod
    def _failure(
        started: float, category: ToolErrorCategory, error: str, retries: int = 0
    ) -> ToolResult:
        return ToolResult(
            success=False,
            error_category=category,
            error=error,
            retry_count=retries,
            duration_ms=(perf_counter() - started) * 1000,
        )

    def _get(self, name: str) -> Tool[Any]:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"unknown tool: {name}") from exc
