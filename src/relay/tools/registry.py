from __future__ import annotations

from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ValidationError

from relay.adapters.base import NetworkAdapter
from relay.domain.models import (
    AdapterObservation,
    ApprovalState,
    ObservationStatus,
    ToolErrorCategory,
    ToolResult,
    ToolRisk,
)
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

    def __init__(self, adapter: NetworkAdapter) -> None:
        self.adapter = adapter

    @property
    def simulator(self) -> NetworkSimulator:
        candidate = getattr(self.adapter, "simulator", None)
        if not isinstance(candidate, NetworkSimulator):
            raise ToolError("this tool is not backed by the LAB simulator")
        return candidate

    @abstractmethod
    def run(self, inputs: InputT) -> dict[str, Any] | AdapterObservation: ...


class ToolRegistry:
    def __init__(
        self, tools: list[Tool[Any]], max_retries: int = 1, read_only: bool | None = None
    ) -> None:
        if not tools:
            raise ValueError("at least one tool is required")
        self._tools = {tool.name: tool for tool in tools}
        self.adapter = tools[0].adapter
        self.read_only = self.adapter.read_only if read_only is None else read_only
        self.max_retries = max_retries

    def is_state_changing(self, name: str) -> bool:
        return self.risk(name) is not ToolRisk.READ_ONLY

    def risk(self, name: str) -> ToolRisk:
        return self._get(name).risk

    def schemas(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                **tool.input_model.model_json_schema(),
                "x-relay-risk": tool.risk.value,
                "x-relay-read-only-source": self.read_only,
            }
            for name, tool in self._tools.items()
        }

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        approved: bool | ApprovalState = False,
    ) -> ToolResult:
        started = perf_counter()
        tool = self._get(name)
        if self.read_only and tool.risk is not ToolRisk.READ_ONLY:
            return self._failure(
                started,
                ToolErrorCategory.PERMISSION_DENIED,
                "write tools are structurally disabled for OBSERVE mode",
            )
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
                simulator = getattr(tool.adapter, "simulator", None)
                if simulator is not None and simulator.consume_failure(name):
                    raise TimeoutError(f"injected timeout for {name}")
                output = tool.run(inputs)
                if isinstance(output, AdapterObservation):
                    success = output.status in {
                        ObservationStatus.SUCCESS,
                        ObservationStatus.STALE,
                        ObservationStatus.UNSUPPORTED,
                        ObservationStatus.UNAVAILABLE,
                    }
                    return ToolResult(
                        success=success,
                        output=output.data,
                        status=output.status,
                        provenance=output.provenance,
                        error=output.message,
                        error_category=ToolErrorCategory.UNSUPPORTED_OPERATION
                        if output.status is ObservationStatus.UNSUPPORTED
                        else (
                            ToolErrorCategory.TOOL_TIMEOUT
                            if output.status is ObservationStatus.UNAVAILABLE
                            else None
                        ),
                        retry_count=retries,
                        duration_ms=(perf_counter() - started) * 1000,
                    )
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

    @property
    def simulator(self) -> NetworkSimulator:
        candidate = getattr(self.adapter, "simulator", None)
        if not isinstance(candidate, NetworkSimulator):
            raise ToolError("registry is not backed by a simulator")
        return candidate
