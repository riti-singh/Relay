from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError

from relay.domain.models import ApprovalState, ToolResult
from relay.network.simulator import NetworkError, NetworkSimulator


class ToolError(ValueError):
    pass


class ApprovalRequiredError(PermissionError):
    pass


class Tool[InputT: BaseModel](ABC):
    name: str
    input_model: type[InputT]
    state_changing = False

    def __init__(self, simulator: NetworkSimulator) -> None:
        self.simulator = simulator

    @abstractmethod
    def run(self, inputs: InputT) -> dict[str, Any]: ...


class ToolRegistry:
    def __init__(self, tools: list[Tool[Any]]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def is_state_changing(self, name: str) -> bool:
        return self._get(name).state_changing

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        approval: ApprovalState = ApprovalState.NOT_REQUIRED,
    ) -> ToolResult:
        tool = self._get(name)
        if tool.state_changing and approval is not ApprovalState.APPROVED:
            raise ApprovalRequiredError(f"tool '{name}' requires explicit approval")
        try:
            inputs = tool.input_model.model_validate(arguments)
            return ToolResult(success=True, output=tool.run(inputs))
        except (ValidationError, NetworkError) as exc:
            return ToolResult(success=False, error=str(exc))

    def _get(self, name: str) -> Tool[Any]:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"unknown tool: {name}") from exc
