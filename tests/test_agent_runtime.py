from pathlib import Path
from uuid import uuid4

import pytest

from relay.agent.planner import AgentModelError, DeterministicPlanner, ScriptedAgentModel
from relay.agent.runtime import AgentRuntime, action_fingerprint
from relay.domain.models import (
    ActionKind,
    AgentDecision,
    ApprovalRecord,
    IncidentStatus,
)
from relay.network.simulator import SCENARIOS, NetworkSimulator
from relay.repositories.incidents import SQLiteIncidentRepository
from relay.services.incidents import IncidentService
from relay.tools.network_tools import build_registry
from relay.tools.registry import ApprovalRequiredError


def build_service(
    tmp_path: Path, scenario: str = "interface-disabled"
) -> tuple[IncidentService, NetworkSimulator]:
    simulator = NetworkSimulator(scenario)
    registry = build_registry(simulator)
    planner = DeterministicPlanner()
    return IncidentService(
        SQLiteIncidentRepository(str(tmp_path / f"{scenario}.db")),
        registry,
        planner,
        AgentRuntime(registry, planner),
    ), simulator


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_every_scenario_diagnoses_and_recovers(tmp_path: Path, scenario: str) -> None:
    service, _ = build_service(tmp_path, scenario)
    definition = SCENARIOS[scenario]
    created = service.create(
        definition.description,
        definition.description,
        definition.source,
        definition.destination,
        scenario,
    )
    investigated = service.agent_run(created.id)
    assert investigated.status is IncidentStatus.AWAITING_APPROVAL
    assert investigated.proposed_remediation is not None
    assert investigated.proposed_remediation.tool_name == definition.expected_remediation_tool
    assert any(definition.expected_root_cause in item.statement for item in investigated.hypotheses)
    assert all(not call.state_changing for call in investigated.tool_calls)
    resolved = service.approve_remediation(
        created.id, investigated.proposed_remediation.id, "test-operator"
    )
    assert resolved.status is IncidentStatus.RESOLVED
    assert resolved.verification_result and resolved.verification_result.successful
    assert all(e.is_verification for e in resolved.evidence[-2:])


def test_tool_retry_is_bounded_and_observable(tmp_path: Path) -> None:
    service, simulator = build_service(tmp_path)
    simulator.inject_failure("ping")
    incident = service.create("x", "x", "branch-03", "payments-api")
    investigated = service.agent_run(incident.id)
    ping = next(call for call in investigated.tool_calls if call.tool_name == "ping")
    assert ping.success and ping.retry_count == 1 and ping.duration_ms is not None


def test_provider_failure_blocks_without_looping(tmp_path: Path) -> None:
    simulator = NetworkSimulator()
    registry = build_registry(simulator)
    runtime = AgentRuntime(
        registry, ScriptedAgentModel([AgentModelError("provider timeout")]), max_steps=5
    )
    service = IncidentService(
        SQLiteIncidentRepository(str(tmp_path / "blocked.db")),
        registry,
        DeterministicPlanner(),
        runtime,
    )
    incident = service.create("x", "x", "branch-03", "payments-api")
    result = service.agent_run(incident.id)
    assert result.status is IncidentStatus.BLOCKED
    assert result.investigation_runs[-1].steps_used == 1
    assert "provider timeout" in (result.investigation_runs[-1].outcome or "")


def test_repeated_calls_are_rejected_then_step_limit_blocks(tmp_path: Path) -> None:
    decision = AgentDecision(
        kind=ActionKind.RUN_TOOL,
        tool_name="ping",
        arguments={"source": "branch-03", "destination": "payments-api"},
        summary="repeat",
    )
    simulator = NetworkSimulator()
    registry = build_registry(simulator)
    runtime = AgentRuntime(
        registry,
        ScriptedAgentModel([decision, decision, decision]),
        max_steps=3,
        max_repeated_calls=1,
    )
    service = IncidentService(
        SQLiteIncidentRepository(str(tmp_path / "repeat.db")),
        registry,
        DeterministicPlanner(),
        runtime,
    )
    result = service.agent_run(service.create("x", "x", "branch-03", "payments-api").id)
    assert result.status is IncidentStatus.BLOCKED
    assert len(result.tool_calls) == 1
    assert sum(not action.successful for action in result.actions) == 2


def test_exact_approval_cannot_cross_incidents_or_changed_arguments(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    first = service.agent_run(service.create("a", "a", "branch-03", "payments-api").id)
    second = service.create("b", "b", "branch-03", "payments-api")
    assert first.proposed_remediation is not None
    with pytest.raises(ValueError, match="matching remediation"):
        service.approve_remediation(second.id, first.proposed_remediation.id, "operator")
    proposal = first.proposed_remediation
    record = ApprovalRecord(
        remediation_id=proposal.id,
        incident_id=first.id,
        approved_by="operator",
        tool_name=proposal.tool_name,
        arguments=proposal.arguments,
        action_fingerprint=action_fingerprint(first.id, proposal),
    )
    proposal.arguments["admin_up"] = False
    with pytest.raises(ValueError, match="exact proposed action"):
        service._execute_remediation(first, record)


def test_unapproved_write_and_failed_verification(tmp_path: Path) -> None:
    service, simulator = build_service(tmp_path)
    with pytest.raises(ApprovalRequiredError):
        service.registry.execute(
            "set_interface_admin_state",
            {"device_id": "core-router-02", "interface_name": "eth1", "admin_up": True},
        )
    investigated = service.agent_run(service.create("x", "x", "branch-03", "payments-api").id)
    assert investigated.proposed_remediation is not None
    simulator.inject_failure("ping", 2)
    result = service.approve_remediation(
        investigated.id, investigated.proposed_remediation.id, "operator"
    )
    assert result.status is IncidentStatus.INVESTIGATING
    assert result.verification_result and not result.verification_result.successful


def test_malformed_script_response_is_normalized(tmp_path: Path) -> None:
    simulator = NetworkSimulator()
    registry = build_registry(simulator)
    runtime = AgentRuntime(
        registry, ScriptedAgentModel([{"kind": "RUN_TOOL", "summary": 123}]), max_steps=2
    )
    service = IncidentService(
        SQLiteIncidentRepository(str(tmp_path / "malformed.db")),
        registry,
        DeterministicPlanner(),
        runtime,
    )
    result = service.agent_run(service.create("x", "x", "branch-03", "payments-api").id)
    assert result.status is IncidentStatus.BLOCKED
    assert result.events[-1].event_type == "planner_failed"


def test_wrong_remediation_id_is_rejected(tmp_path: Path) -> None:
    service, _ = build_service(tmp_path)
    incident = service.agent_run(service.create("x", "x", "branch-03", "payments-api").id)
    with pytest.raises(ValueError, match="matching remediation"):
        service.approve_remediation(incident.id, uuid4(), "operator")
