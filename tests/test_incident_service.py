from pathlib import Path

import pytest

from relay.agent.planner import DeterministicPlanner
from relay.domain.models import ApprovalState, Incident, IncidentStatus
from relay.network.simulator import NetworkSimulator
from relay.repositories.incidents import SQLiteIncidentRepository
from relay.services.incidents import IncidentService
from relay.tools.network_tools import build_registry


def create_seeded(service: IncidentService) -> Incident:
    return service.create(
        "Branch cannot reach payments",
        "Users at branch-03 cannot reach the payments API.",
        "branch-03",
        "payments-api",
    )


def test_state_transitions_reject_invalid_jump() -> None:
    incident = Incident(title="x", description="x", source_device="a", destination_device="b")
    with pytest.raises(ValueError, match="invalid incident transition"):
        incident.transition_to(IncidentStatus.RESOLVED)


def test_diagnosis_stops_for_approval(
    service: IncidentService, simulator: NetworkSimulator
) -> None:
    incident = service.investigate(create_seeded(service).id)
    assert incident.status is IncidentStatus.AWAITING_APPROVAL
    assert incident.approval_state is ApprovalState.PENDING
    assert incident.hypotheses[0].confidence == 0.99
    assert "administratively disabled" in incident.hypotheses[0].statement
    assert incident.proposed_remediation is not None
    assert all(not call.state_changing for call in incident.tool_calls)
    assert simulator.interface("core-router-02", "eth1").admin_up is False


def test_approval_remediation_and_verification(
    service: IncidentService, simulator: NetworkSimulator
) -> None:
    investigated = service.investigate(create_seeded(service).id)
    resolved = service.approve_and_remediate(investigated.id)
    assert resolved.status is IncidentStatus.RESOLVED
    assert resolved.approval_state is ApprovalState.APPROVED
    assert resolved.verification_result is not None
    assert resolved.verification_result.successful
    mutation = next(call for call in resolved.tool_calls if call.state_changing)
    assert mutation.success
    assert simulator.path("branch-03", "payments-api") is not None


def test_persists_complete_history_across_repository_reopen(tmp_path: Path) -> None:
    database = str(tmp_path / "persistent.db")
    simulator = NetworkSimulator()
    service = IncidentService(
        SQLiteIncidentRepository(database), build_registry(simulator), DeterministicPlanner()
    )
    investigated = service.investigate(create_seeded(service).id)
    reopened = IncidentService(
        SQLiteIncidentRepository(database), build_registry(simulator), DeterministicPlanner()
    )
    loaded = reopened.get(investigated.id)
    assert loaded.status is IncidentStatus.AWAITING_APPROVAL
    assert loaded.tool_calls
    assert loaded.evidence
    assert loaded.hypotheses
    assert loaded.proposed_remediation is not None
    assert loaded.approval_state is ApprovalState.PENDING


def test_cannot_approve_open_incident(service: IncidentService) -> None:
    with pytest.raises(ValueError, match="no remediation awaiting approval"):
        service.approve_and_remediate(create_seeded(service).id)
