from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from relay.agent.planner import InvestigationPlanner
from relay.domain.models import (
    ApprovalState,
    Evidence,
    Hypothesis,
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
        self, repository: IncidentRepository, registry: ToolRegistry, planner: InvestigationPlanner
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.planner = planner

    def create(
        self, title: str, description: str, source_device: str, destination_device: str
    ) -> Incident:
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

    def investigate(self, incident_id: UUID) -> Incident:
        incident = self.get(incident_id)
        incident.transition_to(IncidentStatus.INVESTIGATING)
        planned = self.planner.plan(incident)
        incident.investigation_plan = [
            f"{step.tool_name}: {step.evidence_summary}" for step in planned
        ]
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
        if suspect is not None:
            suspect_device, suspect_interface = suspect
            self._execute_and_record(
                incident,
                "get_interface_status",
                {"device_id": suspect_device, "interface_name": suspect_interface},
                "Inspected the suspect ingress interface",
            )
            self._execute_and_record(
                incident,
                "get_device_logs",
                {"device_id": suspect_device},
                "Reviewed suspect device logs",
            )
            self._execute_and_record(
                incident,
                "get_device_config",
                {"device_id": suspect_device},
                "Reviewed suspect device configuration",
            )

        status_evidence = next(
            (
                item
                for item in reversed(incident.evidence)
                if item.summary == "Inspected the suspect ingress interface"
            ),
            None,
        )
        if status_evidence and status_evidence.observation.get("admin_up") is False:
            supporting = [
                item.id
                for item in incident.evidence
                if item.summary
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
                        f"{suspect_device} interface {suspect_interface} is administratively "
                        f"disabled, isolating {incident.source_device}"
                    ),
                    confidence=0.99,
                    supporting_evidence_ids=supporting,
                )
            )
            incident.proposed_remediation = ProposedRemediation(
                description=f"Enable {suspect_device} {suspect_interface} administrative state",
                tool_name="set_interface_admin_state",
                arguments={
                    "device_id": suspect_device,
                    "interface_name": suspect_interface,
                    "admin_up": True,
                },
            )
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

    def approve_and_remediate(self, incident_id: UUID) -> Incident:
        incident = self.get(incident_id)
        if (
            incident.status is not IncidentStatus.AWAITING_APPROVAL
            or incident.proposed_remediation is None
        ):
            raise ValueError("incident has no remediation awaiting approval")
        incident.approval_state = ApprovalState.APPROVED
        incident.transition_to(IncidentStatus.REMEDIATING)
        remediation = incident.proposed_remediation
        success, _ = self._execute_and_record(
            incident, remediation.tool_name, remediation.arguments, "Executed approved remediation"
        )
        if not success:
            incident.transition_to(IncidentStatus.FAILED)
            self.repository.save(incident)
            return incident
        incident.transition_to(IncidentStatus.VERIFYING)
        verification_ids: list[UUID] = []
        for name in ("ping", "traceroute"):
            success, call_id = self._execute_and_record(
                incident,
                name,
                {"source": incident.source_device, "destination": incident.destination_device},
                f"Post-remediation {name} verification",
            )
            verification_ids.append(call_id)
            if not success:
                incident.verification_result = VerificationResult(
                    successful=False,
                    summary=f"Recovery verification failed during {name}",
                    tool_call_ids=verification_ids,
                )
                incident.transition_to(IncidentStatus.FAILED)
                self.repository.save(incident)
                return incident
        ping_evidence = incident.evidence[-2]
        recovered = ping_evidence.observation.get("reachable") is True
        incident.verification_result = VerificationResult(
            successful=recovered,
            summary="Connectivity restored" if recovered else "Connectivity remains unavailable",
            tool_call_ids=verification_ids,
        )
        incident.transition_to(IncidentStatus.RESOLVED if recovered else IncidentStatus.FAILED)
        self.repository.save(incident)
        return incident

    def _execute_and_record(
        self,
        incident: Incident,
        tool_name: str,
        arguments: dict[str, object],
        summary: str,
    ) -> tuple[bool, UUID]:
        call = ToolCall(
            tool_name=tool_name,
            arguments=arguments,
            state_changing=self.registry.is_state_changing(tool_name),
        )
        incident.tool_calls.append(call)
        result = self.registry.execute(tool_name, arguments, incident.approval_state)
        call.completed_at = datetime.now(UTC)
        call.success = result.success
        call.error = result.error
        if result.success:
            incident.evidence.append(
                Evidence(tool_call_id=call.id, summary=summary, observation=result.output)
            )
        return result.success, call.id
