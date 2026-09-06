from pathlib import Path

from fastapi.testclient import TestClient

from relay.agent.planner import DeterministicPlanner
from relay.agent.runtime import AgentRuntime
from relay.domain.models import AgentRunStatus
from relay.network.simulator import NetworkSimulator
from relay.repositories.incidents import SQLiteIncidentRepository
from relay.services.incidents import IncidentService
from relay.tools.network_tools import build_registry


def service_at(path: Path) -> IncidentService:
    registry = build_registry(NetworkSimulator())
    planner = DeterministicPlanner()
    return IncidentService(
        SQLiteIncidentRepository(str(path)),
        registry,
        planner,
        AgentRuntime(registry, planner),
    )


def test_run_lifecycle_events_are_ordered_and_cancel_is_durable(tmp_path: Path) -> None:
    service = service_at(tmp_path / "runs.db")
    incident = service.create("case", "outage", "branch-03", "payments-api")
    run = service.queue_agent_run(incident.id)
    assert run.status is AgentRunStatus.QUEUED
    cancelled = service.cancel_run(incident.id, run.id)
    assert cancelled.status is AgentRunStatus.CANCELLED
    restored = service.get(incident.id)
    events = [event for event in restored.events if event.run_id == run.id]
    assert [event.type for event in events] == ["RUN_QUEUED", "RUN_CANCELLED"]
    assert [event.sequence for event in events] == sorted(event.sequence for event in events)


def test_incident_simulators_are_isolated_and_reconstruct_approved_state(tmp_path: Path) -> None:
    database = tmp_path / "isolation.db"
    service = service_at(database)
    first = service.create("first", "outage", "branch-03", "payments-api")
    second = service.create("second", "outage", "branch-03", "payments-api")
    diagnosed = service.agent_run(first.id)
    assert diagnosed.proposed_remediation
    service.approve_remediation(first.id, diagnosed.proposed_remediation.id, "operator")

    second_core = next(
        d for d in service.topology_for_incident(second.id).devices if d.id == "core-router-02"
    )
    assert next(i for i in second_core.interfaces if i.name == "eth1").admin_up is False

    restarted = service_at(database)
    first_core = next(
        d for d in restarted.topology_for_incident(first.id).devices if d.id == "core-router-02"
    )
    assert next(i for i in first_core.interfaces if i.name == "eth1").admin_up is True


def test_sse_replays_from_sequence(client: TestClient) -> None:
    created = client.post(
        "/incidents",
        json={
            "title": "live",
            "description": "outage",
            "source_device": "branch-03",
            "destination_device": "payments-api",
        },
    ).json()
    run = client.post(
        f"/incidents/{created['id']}/agent/start", json={"planner": "deterministic"}
    ).json()
    response = client.get(f"/incidents/{created['id']}/runs/{run['id']}/events?after=1")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "RUN_STARTED" in response.text
    assert "id: 1\n" not in response.text
