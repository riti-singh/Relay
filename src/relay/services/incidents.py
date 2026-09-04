from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from relay.agent.planner import AgentModel, DeterministicPlanner, InvestigationPlanner
from relay.agent.runtime import AgentRuntime, action_fingerprint
from relay.domain.models import (
    ApprovalRecord,
    ApprovalState,
    Evidence,
    Hypothesis,
    HypothesisStatus,
    Incident,
    IncidentStatus,
    InvestigationRun,
    ProposedRemediation,
    ToolCall,
    VerificationResult,
)
from relay.repositories.incidents import IncidentRepository
from relay.tools.registry import ToolRegistry


class IncidentNotFoundError(LookupError):
    pass


class IncidentService:
    def __init__(
        self,
        repository: IncidentRepository,
        registry: ToolRegistry,
        planner: InvestigationPlanner,
        runtime: AgentRuntime | None = None,
    ) -> None:
        self.repository, self.registry, self.planner = repository, registry, planner
        model = (
            cast(AgentModel, planner)
            if hasattr(planner, "decide_next_action")
            else DeterministicPlanner()
        )
        self.runtime = runtime or AgentRuntime(registry, model)
        self._scenario_runtimes: dict[str, tuple[ToolRegistry, AgentRuntime]] = {
            registry.simulator.scenario: (registry, self.runtime)
        }

    def create(
        self,
        title: str,
        description: str,
        source_device: str,
        destination_device: str,
        scenario: str = "interface-disabled",
    ) -> Incident:
        self._activate_scenario(scenario)
        topology = self.registry.execute("get_network_topology", {})
        device_ids = {device["id"] for device in topology.output["devices"]}
        unknown = {source_device, destination_device} - device_ids
        if unknown:
            raise ValueError(f"unknown incident device(s): {', '.join(sorted(unknown))}")
        incident = Incident(
            title=title,
            description=description,
            source_device=source_device,
            destination_device=destination_device,
            scenario=scenario,
        )
        self.repository.save(incident)
        return incident

    def get(self, incident_id: UUID) -> Incident:
        incident = self.repository.get(incident_id)
        if incident is None:
            raise IncidentNotFoundError(f"incident not found: {incident_id}")
        return incident

    def list(self) -> list[Incident]:
        return self.repository.list()

    def agent_run(self, incident_id: UUID) -> Incident:
        incident = self.get(incident_id)
        self._activate_scenario(incident.scenario)
        incident = self.runtime.run(incident)
        self.repository.save(incident)
        return incident

    def agent_continue(self, incident_id: UUID) -> Incident:
        return self.agent_run(incident_id)

    def investigate(self, incident_id: UUID) -> Incident:
        """Milestone 1 deterministic endpoint retained byte-for-byte in behavior."""
        incident = self.get(incident_id)
        self._activate_scenario(incident.scenario)
        incident.transition_to(IncidentStatus.INVESTIGATING)
        planned = self.planner.plan(incident)
        incident.investigation_plan = [f"{s.tool_name}: {s.evidence_summary}" for s in planned]
        run = InvestigationRun(plan=incident.investigation_plan)
        incident.investigation_runs.append(run)
        for step in planned:
            self._execute_and_record(
                incident, step.tool_name, dict(step.arguments), step.evidence_summary
            )
        topology = incident.evidence[0].observation
        routes = incident.evidence[3].observation["routes"]
        next_hop = routes.get(incident.destination_device)
        suspect = self._linked_interface(topology["links"], incident.source_device, str(next_hop))
        if suspect:
            device, interface = suspect
            self._execute_and_record(
                incident,
                "get_interface_status",
                {"device_id": device, "interface_name": interface},
                "Inspected the suspect ingress interface",
            )
            self._execute_and_record(
                incident, "get_device_logs", {"device_id": device}, "Reviewed suspect device logs"
            )
            self._execute_and_record(
                incident,
                "get_device_config",
                {"device_id": device},
                "Reviewed suspect device configuration",
            )
        status = next(
            (
                e
                for e in reversed(incident.evidence)
                if e.summary == "Inspected the suspect ingress interface"
            ),
            None,
        )
        if status and status.observation.get("admin_up") is False:
            supporting = [
                e.id
                for e in incident.evidence
                if e.summary
                in {
                    "Located the connectivity failure boundary",
                    "Inspected the suspect ingress interface",
                    "Reviewed suspect device logs",
                    "Reviewed suspect device configuration",
                }
            ]
            incident.hypotheses.append(
                Hypothesis(
                    statement=(
                        f"{device} interface {interface} is administratively disabled, "
                        f"isolating {incident.source_device}"
                    ),
                    suspected_component=f"{device}/{interface}",
                    confidence=0.99,
                    supporting_evidence_ids=supporting,
                    status=HypothesisStatus.CONFIRMED,
                )
            )
            proposal = ProposedRemediation(
                description=f"Enable {device} {interface} administrative state",
                tool_name="set_interface_admin_state",
                arguments={"device_id": device, "interface_name": interface, "admin_up": True},
            )
            incident.proposed_remediation = proposal
            incident.remediation_history.append(proposal)
            incident.approval_state = ApprovalState.PENDING
            incident.transition_to(IncidentStatus.AWAITING_APPROVAL)
            run.outcome = "Root cause identified; remediation awaits approval"
        else:
            incident.transition_to(IncidentStatus.FAILED)
            run.outcome = "Deterministic planner could not identify the seeded failure"
        run.completed_at = datetime.now(UTC)
        self.repository.save(incident)
        return incident

    @staticmethod
    def _linked_interface(
        links: object, source_device: str, next_hop: str
    ) -> tuple[str, str] | None:
        if not isinstance(links, list):
            return None
        for link in links:
            if not isinstance(link, dict):
                continue
            if link.get("device_a") == source_device and link.get("device_b") == next_hop:
                return next_hop, str(link["interface_b"])
            if link.get("device_b") == source_device and link.get("device_a") == next_hop:
                return next_hop, str(link["interface_a"])
        return None

    def approve_remediation(
        self, incident_id: UUID, remediation_id: UUID, approved_by: str
    ) -> Incident:
        incident = self.get(incident_id)
        self._activate_scenario(incident.scenario)
        remediation = incident.proposed_remediation
        if (
            incident.status is not IncidentStatus.AWAITING_APPROVAL
            or remediation is None
            or remediation.id != remediation_id
        ):
            raise ValueError("incident has no matching remediation awaiting approval")
        record = ApprovalRecord(
            remediation_id=remediation.id,
            incident_id=incident.id,
            approved_by=approved_by,
            tool_name=remediation.tool_name,
            arguments=remediation.arguments,
            action_fingerprint=action_fingerprint(incident.id, remediation),
        )
        incident.approval_records.append(record)
        incident.approval_state = ApprovalState.APPROVED
        self._execute_remediation(incident, record)
        self.repository.save(incident)
        return incident

    def _activate_scenario(self, scenario: str) -> None:
        existing = self._scenario_runtimes.get(scenario)
        if existing is None:
            from relay.network.simulator import NetworkSimulator
            from relay.tools.network_tools import build_registry

            registry = build_registry(NetworkSimulator(scenario), self.registry.max_retries)
            runtime = AgentRuntime(
                registry,
                self.runtime.model,
                self.runtime.max_steps,
                self.runtime.max_repeated_calls,
                self.runtime.context_evidence_limit,
            )
            existing = (registry, runtime)
            self._scenario_runtimes[scenario] = existing
        self.registry, self.runtime = existing

    def approve_and_remediate(self, incident_id: UUID) -> Incident:
        incident = self.get(incident_id)
        if incident.proposed_remediation is None:
            raise ValueError("incident has no remediation awaiting approval")
        return self.approve_remediation(incident_id, incident.proposed_remediation.id, "legacy-api")

    def _execute_remediation(self, incident: Incident, approval: ApprovalRecord) -> None:
        remediation = incident.proposed_remediation
        if (
            remediation is None
            or approval.incident_id != incident.id
            or approval.remediation_id != remediation.id
            or approval.action_fingerprint != action_fingerprint(incident.id, remediation)
        ):
            raise ValueError("approval does not match the exact proposed action")
        incident.transition_to(IncidentStatus.REMEDIATING)
        success, _ = self._execute_and_record(
            incident,
            remediation.tool_name,
            remediation.arguments,
            "Executed approved remediation",
            approved=True,
        )
        approval.execution_status = "SUCCEEDED" if success else "FAILED"
        if not success:
            incident.transition_to(IncidentStatus.INVESTIGATING)
            return
        incident.transition_to(IncidentStatus.VERIFYING)
        self._verify(incident)

    def _verify(self, incident: Incident) -> None:
        checks: list[tuple[str, dict[str, Any], str]] = [
            (
                "ping",
                {"source": incident.source_device, "destination": incident.destination_device},
                "Post-remediation ping verification",
            )
        ]
        if incident.scenario == "acl-block":
            checks.append(
                (
                    "test_tcp_connection",
                    {
                        "source": incident.source_device,
                        "destination": incident.destination_device,
                        "port": 443,
                    },
                    "Post-remediation TCP verification",
                )
            )
        elif incident.scenario == "dns-failure":
            checks.append(
                (
                    "resolve_dns",
                    {"hostname": "payments.internal"},
                    "Post-remediation DNS verification",
                )
            )
        elif incident.scenario == "degraded-link":
            checks.append(
                (
                    "get_packet_loss",
                    {"source": incident.source_device, "destination": incident.destination_device},
                    "Post-remediation loss verification",
                )
            )
        else:
            checks.append(
                (
                    "traceroute",
                    {"source": incident.source_device, "destination": incident.destination_device},
                    "Post-remediation traceroute verification",
                )
            )
        ids: list[UUID] = []
        recovered = True
        for name, args, summary in checks:
            success, call_id = self._execute_and_record(
                incident, name, args, summary, verification=True
            )
            ids.append(call_id)
            observation = next(
                (e.observation for e in reversed(incident.evidence) if e.tool_call_id == call_id),
                {},
            )
            recovered = (
                recovered and success and self._verification_passed(name, observation, incident)
            )
        incident.verification_result = VerificationResult(
            successful=recovered,
            summary="Connectivity restored"
            if recovered
            else "Recovery verification failed; investigation resumed",
            tool_call_ids=ids,
        )
        incident.transition_to(
            IncidentStatus.RESOLVED if recovered else IncidentStatus.INVESTIGATING
        )

    @staticmethod
    def _verification_passed(name: str, observation: dict[str, Any], incident: Incident) -> bool:
        if name == "ping":
            return observation.get("reachable") is True
        if name == "traceroute":
            return observation.get("reached") is True
        if name == "test_tcp_connection":
            return observation.get("connected") is True
        if name == "resolve_dns":
            return observation.get("target") == incident.destination_device
        if name == "get_packet_loss":
            return float(observation.get("packet_loss_percent", 100)) <= 5
        return False

    def _execute_and_record(
        self,
        incident: Incident,
        tool_name: str,
        arguments: dict[str, Any],
        summary: str,
        approved: bool = False,
        verification: bool = False,
    ) -> tuple[bool, UUID]:
        risk = self.registry.risk(tool_name)
        call = ToolCall(
            tool_name=tool_name,
            arguments=arguments,
            risk=risk,
            state_changing=self.registry.is_state_changing(tool_name),
        )
        incident.tool_calls.append(call)
        result = self.registry.execute(tool_name, arguments, approved=approved)
        call.completed_at = datetime.now(UTC)
        call.duration_ms = result.duration_ms
        call.success = result.success
        call.retry_count = result.retry_count
        call.error_category = result.error_category
        call.error = result.error
        if result.success:
            incident.evidence.append(
                Evidence(
                    tool_call_id=call.id,
                    summary=summary,
                    observation=result.output,
                    is_verification=verification,
                )
            )
        return result.success, call.id
