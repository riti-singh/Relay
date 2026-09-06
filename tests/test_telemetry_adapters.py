from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from relay.adapters.base import CompositeNetworkAdapter, DiagnosticOperation
from relay.adapters.http_telemetry import HTTPTelemetryAdapter
from relay.adapters.simulator import SimulatorNetworkAdapter
from relay.agent.planner import DeterministicPlanner
from relay.domain.models import AdapterCapability, Freshness, ObservationStatus, OperatingMode
from relay.network.simulator import NetworkSimulator
from relay.repositories.incidents import SQLiteIncidentRepository
from relay.services.incidents import IncidentService
from relay.tools.network_tools import build_registry
from relay.tools.registry import ToolError

CAPABILITIES = frozenset(
    {
        AdapterCapability.TOPOLOGY,
        AdapterCapability.INVENTORY,
        AdapterCapability.REACHABILITY,
        AdapterCapability.INTERFACE_STATE,
        AdapterCapability.ROUTES,
        AdapterCapability.LINK_METRICS,
        AdapterCapability.PACKET_LOSS,
    }
)


@pytest.fixture(scope="module")
def fixture_url() -> Iterator[str]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "relay.fixture_service:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            from urllib.request import urlopen

            with urlopen(f"{url}/health", timeout=0.1):
                break
        except OSError:
            time.sleep(0.02)
    else:
        process.terminate()
        raise RuntimeError("fixture telemetry service did not start")
    yield url
    process.terminate()
    process.wait(timeout=5)


def adapter(url: str, dataset: str = "degraded-link", freshness: int = 60) -> HTTPTelemetryAdapter:
    return HTTPTelemetryAdapter(
        "fixture-http", "Fixture HTTP", url, dataset, CAPABILITIES, 0.2, freshness
    )


def test_simulator_implements_adapter_contract() -> None:
    source = SimulatorNetworkAdapter(NetworkSimulator())
    result = source.collect(
        DiagnosticOperation.PING, {"source": "branch-03", "destination": "payments-api"}
    )
    assert result.status is ObservationStatus.SUCCESS
    assert result.provenance.adapter == "lab-simulator"
    assert source.inventory().devices


def test_external_normalization_inventory_stale_and_unsupported(fixture_url: str) -> None:
    source = adapter(fixture_url)
    result = source.collect(
        DiagnosticOperation.LINK_METRICS, {"device_a": "edge-01", "device_b": "core-01"}
    )
    assert result.status is ObservationStatus.SUCCESS
    assert result.data["packet_loss_percent"] == 28
    assert result.provenance.observed_at and result.provenance.freshness is Freshness.FRESH
    assert source.inventory().devices[0].telemetry_source == "fixture-http"
    unsupported = source.collect(DiagnosticOperation.ACL_RULES, {"device_id": "core-01"})
    assert unsupported.status is ObservationStatus.UNSUPPORTED
    stale = adapter(fixture_url, "stale-link").collect(
        DiagnosticOperation.PACKET_LOSS, {"source": "edge-01", "destination": "orders-api"}
    )
    assert stale.status is ObservationStatus.STALE
    assert stale.provenance.freshness is Freshness.STALE


def test_external_unavailable_timeout_and_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    unavailable = adapter("http://127.0.0.1:1").collect(
        DiagnosticOperation.PING, {"source": "a", "destination": "b"}
    )
    assert unavailable.status is ObservationStatus.UNAVAILABLE

    def timeout(*args: object, **kwargs: object) -> None:
        raise TimeoutError("deadline exceeded")

    monkeypatch.setattr("relay.adapters.http_telemetry.request.urlopen", timeout)
    timed_out = adapter("http://telemetry.invalid").collect(
        DiagnosticOperation.PING, {"source": "a", "destination": "b"}
    )
    assert timed_out.status is ObservationStatus.UNAVAILABLE

    class MalformedResponse:
        def __enter__(self) -> MalformedResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"not-json"

    monkeypatch.setattr(
        "relay.adapters.http_telemetry.request.urlopen",
        lambda *_args, **_kwargs: MalformedResponse(),
    )
    malformed = adapter("http://telemetry.invalid").collect(
        DiagnosticOperation.PING, {"source": "a", "destination": "b"}
    )
    assert malformed.status is ObservationStatus.FAILED


def test_multi_source_inventory_correlation() -> None:
    first = SimulatorNetworkAdapter(NetworkSimulator("interface-disabled"))
    second = SimulatorNetworkAdapter(NetworkSimulator("degraded-link"))
    second.adapter_id = "secondary-inventory"
    composite = CompositeNetworkAdapter("correlated", [first, second])
    inventory = composite.inventory()
    assert len(inventory.devices) == 8
    assert {item.telemetry_source for item in inventory.devices} == {
        "lab-simulator",
        "secondary-inventory",
    }


@pytest.mark.parametrize(
    "dataset, expected",
    [
        ("interface-failure", "down"),
        ("route-anomaly", "anomalous route"),
        ("degraded-link", "degraded"),
    ],
)
def test_observe_runtime_root_cause_provenance_and_safety(
    tmp_path: Path, fixture_url: str, dataset: str, expected: str
) -> None:
    factory = lambda incident: adapter(fixture_url, incident.scenario)  # noqa: E731
    service = IncidentService(
        SQLiteIncidentRepository(str(tmp_path / "relay.db")),
        build_registry(NetworkSimulator()),
        DeterministicPlanner(),
        adapter_factories={"fixture-http": factory},
    )
    incident = service.create(
        "External incident",
        "Observed symptoms",
        "edge-01",
        "orders-api",
        dataset,
        OperatingMode.OBSERVE,
        ["fixture-http"],
    )
    result = service.agent_run(incident.id)
    assert expected in result.hypotheses[0].statement
    assert result.proposed_remediation is None
    assert all(not call.state_changing for call in result.tool_calls)
    assert all(item.run_id == result.investigation_runs[-1].id for item in result.evidence)
    assert result.events[-1].payload["mode"] == "OBSERVE"
    registry, _ = service._runtime_for(result)
    with pytest.raises(ToolError):
        registry.risk("set_interface_admin_state")


def test_observe_approval_attempt_is_audited(tmp_path: Path, fixture_url: str) -> None:
    factory = lambda incident: adapter(fixture_url, incident.scenario)  # noqa: E731
    service = IncidentService(
        SQLiteIncidentRepository(str(tmp_path / "relay.db")),
        build_registry(NetworkSimulator()),
        DeterministicPlanner(),
        adapter_factories={"fixture-http": factory},
    )
    incident = service.create(
        "External",
        "Observed",
        "edge-01",
        "orders-api",
        "healthy",
        OperatingMode.OBSERVE,
        ["fixture-http"],
    )
    from uuid import uuid4

    with pytest.raises(ValueError, match="read-only"):
        service.approve_remediation(incident.id, uuid4(), "operator")
    assert service.get(incident.id).events[-1].type == "OBSERVE_WRITE_REJECTED"
