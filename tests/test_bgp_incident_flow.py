from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import request

import pytest
from test_ripestat_adapter import FakeResponse, bgp_updates, prefix_overview, routing_status
from test_telemetry_adapters import adapter as fixture_adapter
from test_telemetry_adapters import fixture_url  # noqa: F401

from relay.adapters import RIPEstatAdapter
from relay.adapters.base import CompositeNetworkAdapter, DiagnosticOperation
from relay.adapters.simulator import SimulatorNetworkAdapter
from relay.agent.planner import DeterministicPlanner
from relay.domain.models import Incident, ObservationStatus, OperatingMode
from relay.network.simulator import NetworkSimulator
from relay.repositories.incidents import SQLiteIncidentRepository
from relay.services.incidents import IncidentService
from relay.tools.network_tools import build_registry

SOURCE_IP = "198.51.100.10"
DESTINATION_IP = "193.0.0.1"


def install_ripestat(monkeypatch: pytest.MonkeyPatch, announced: bool = True) -> list[str]:
    """Serve mocked RIPEstat data calls; pass every other URL through to the real urlopen."""
    calls: list[str] = []
    real_urlopen = request.urlopen
    responses: dict[str, dict[str, Any]] = {
        "routing-status": routing_status(announced=announced),
        "prefix-overview": prefix_overview(),
        "bgp-updates": bgp_updates(),
    }

    def fake_urlopen(url: str, timeout: float) -> Any:
        if "stat.ripe.net" not in url:
            return real_urlopen(url, timeout=timeout)
        calls.append(url)
        data_call = url.split("/data/")[1].split("/")[0]
        return FakeResponse(json.dumps(responses[data_call]).encode())

    monkeypatch.setattr("relay.adapters.ripestat.request.urlopen", fake_urlopen)
    return calls


def ripestat_factory(_incident: Incident) -> RIPEstatAdapter:
    return RIPEstatAdapter()


def service(tmp_path: Path, factories: dict[str, Any]) -> IncidentService:
    return IncidentService(
        SQLiteIncidentRepository(str(tmp_path / "relay.db")),
        build_registry(NetworkSimulator()),
        DeterministicPlanner(),
        adapter_factories=factories,
    )


def test_ripestat_only_incident_queries_destination_and_reports_healthy_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = install_ripestat(monkeypatch)
    svc = service(tmp_path, {"ripestat": ripestat_factory})
    incident = svc.create(
        "Unreachable prefix",
        "Customers cannot reach 193.0.0.1",
        SOURCE_IP,
        DESTINATION_IP,
        "healthy",
        OperatingMode.OBSERVE,
        ["ripestat"],
    )
    result = svc.agent_run(incident.id)
    assert len([url for url in calls if f"resource={DESTINATION_IP}&" in url]) == 3
    assert all(f"resource={DESTINATION_IP}" in url or SOURCE_IP in url for url in calls)
    statement = result.hypotheses[0].statement
    assert "globally announced by AS3333" in statement
    assert "not an origin withdrawal" in statement
    assert result.proposed_remediation is None
    visibility_call = next(c for c in result.tool_calls if c.tool_name == "get_prefix_visibility")
    assert visibility_call.arguments == {"resource": DESTINATION_IP}
    evidence = next(e for e in result.evidence if e.tool_call_id == visibility_call.id)
    assert evidence.provenance.source_type == "ripestat"
    assert evidence.provenance.resource_id == DESTINATION_IP
    assert DESTINATION_IP in evidence.provenance.source_metadata["routing_status_url"]


def test_ripestat_only_incident_reports_withdrawn_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_ripestat(monkeypatch, announced=False)
    svc = service(tmp_path, {"ripestat": ripestat_factory})
    incident = svc.create(
        "Withdrawn prefix",
        "Route disappeared",
        SOURCE_IP,
        DESTINATION_IP,
        "healthy",
        OperatingMode.OBSERVE,
        ["ripestat"],
    )
    result = svc.agent_run(incident.id)
    statement = result.hypotheses[0].statement
    assert "not globally visible in BGP" in statement
    assert "withdrawn" in statement
    assert "1 withdrawal(s)" in statement
    assert result.proposed_remediation is None


def test_non_ip_endpoints_still_require_topology(tmp_path: Path) -> None:
    svc = service(tmp_path, {"ripestat": ripestat_factory})
    with pytest.raises(ValueError, match="unknown incident device"):
        svc.create(
            "Bad endpoints",
            "",
            "edge-01",
            "orders-api",
            "healthy",
            OperatingMode.OBSERVE,
            ["ripestat"],
        )


@pytest.mark.parametrize(
    "dataset, announced, expected",
    [
        ("healthy", True, "No active network fault"),
        ("route-anomaly", True, "anomalous route"),
        ("healthy", False, "not globally visible in BGP"),
    ],
)
def test_composite_fixture_and_ripestat_incident(
    tmp_path: Path,
    fixture_url: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    dataset: str,
    announced: bool,
    expected: str,
) -> None:
    calls = install_ripestat(monkeypatch, announced=announced)
    svc = service(
        tmp_path,
        {
            "fixture-http": lambda incident: fixture_adapter(fixture_url, incident.scenario),
            "ripestat": ripestat_factory,
        },
    )
    incident = svc.create(
        "Composite incident",
        "",
        "edge-01",
        "orders-api",
        dataset,
        OperatingMode.OBSERVE,
        ["fixture-http", "ripestat"],
    )
    registry, _ = svc._runtime_for(incident)
    assert isinstance(registry.adapter, CompositeNetworkAdapter)
    result = svc.agent_run(incident.id)
    assert expected in result.hypotheses[0].statement
    assert result.proposed_remediation is None
    assert all(not call.state_changing for call in result.tool_calls)
    by_tool = {c.tool_name: c for c in result.tool_calls}
    sources = {
        name: next(e.provenance.source_type for e in result.evidence if e.tool_call_id == call.id)
        for name, call in by_tool.items()
        if name in {"get_route_table", "get_prefix_visibility"}
    }
    assert sources == {"get_route_table": "http-telemetry", "get_prefix_visibility": "ripestat"}
    assert calls and all("resource=orders-api&" in url for url in calls)


def test_simulator_reports_prefix_visibility_unsupported() -> None:
    observation = SimulatorNetworkAdapter(NetworkSimulator()).collect(
        DiagnosticOperation.PREFIX_VISIBILITY, {"resource": DESTINATION_IP}
    )
    assert observation.status is ObservationStatus.UNSUPPORTED
    assert not SimulatorNetworkAdapter(NetworkSimulator()).supports(
        DiagnosticOperation.PREFIX_VISIBILITY
    )
