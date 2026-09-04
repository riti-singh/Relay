from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from relay.domain.models import Incident


@dataclass(frozen=True)
class PlannedToolCall:
    tool_name: str
    arguments: dict[str, object]
    evidence_summary: str


class InvestigationPlanner(Protocol):
    def plan(self, incident: Incident) -> list[PlannedToolCall]: ...


class DeterministicPlanner:
    """An explicit planner for the seeded scenario, replaceable by an LLM planner."""

    def plan(self, incident: Incident) -> list[PlannedToolCall]:
        connectivity: dict[str, object] = {
            "source": incident.source_device,
            "destination": incident.destination_device,
        }
        return [
            PlannedToolCall("get_network_topology", {}, "Captured current network topology"),
            PlannedToolCall("ping", connectivity, "Tested end-to-end reachability"),
            PlannedToolCall(
                "traceroute", connectivity, "Located the connectivity failure boundary"
            ),
            PlannedToolCall(
                "get_route_table",
                {"device_id": incident.source_device},
                "Inspected source routing state",
            ),
        ]
