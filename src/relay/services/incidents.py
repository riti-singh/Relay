from __future__ import annotations

import builtins
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from typing import Any, cast
from uuid import UUID

from relay.adapters.base import NetworkAdapter
from relay.agent.planner import AgentModel, DeterministicPlanner, InvestigationPlanner
from relay.agent.runtime import AgentRuntime, action_fingerprint
from relay.domain.models import (
    AgentRunStatus,
    ApprovalRecord,
    ApprovalState,
    Evidence,
    Hypothesis,
    HypothesisStatus,
    Incident,
    IncidentStatus,
    Inventory,
    InvestigationEvent,
    InvestigationRun,
    NetworkTopology,
    ObservationProvenance,
    OperatingMode,
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
        adapter_factories: dict[str, Callable[[Incident], NetworkAdapter]] | None = None,
    ) -> None:
        self.repository, self.registry, self.planner = repository, registry, planner
        model = (
            cast(AgentModel, planner)
            if hasattr(planner, "decide_next_action")
            else DeterministicPlanner()
        )
        self.runtime = runtime or AgentRuntime(registry, model)
        self.adapter_factories = adapter_factories or {}
        self._incident_runtimes: dict[UUID, tuple[ToolRegistry, AgentRuntime]] = {}
        self._base_claimed = False
        self._cancelled_runs: set[UUID] = set()
        self._lock = Lock()

    def create(
        self,
        title: str,
        description: str,
        source_device: str,
        destination_device: str,
        scenario: str = "interface-disabled",
        operating_mode: OperatingMode = OperatingMode.LAB,
        data_source_ids: list[str] | None = None,
        resource_ids: list[str] | None = None,
    ) -> Incident:
        incident = Incident(
            title=title,
            description=description,
            source_device=source_device,
            destination_device=destination_device,
            scenario=scenario,
            operating_mode=operating_mode,
            data_source_ids=data_source_ids
            or (["lab-simulator"] if operating_mode is OperatingMode.LAB else ["fixture-http"]),
            resource_ids=resource_ids or [source_device, destination_device],
        )
        registry, runtime = self._new_incident_runtime(incident)
        self._incident_runtimes[incident.id] = (registry, runtime)
        topology = registry.adapter.topology()
        device_ids = {device.id for device in topology.devices}
        unknown = {source_device, destination_device} - device_ids
        if unknown:
            raise ValueError(f"unknown incident device(s): {', '.join(sorted(unknown))}")
        self.repository.save(incident)
        return incident

    def get(self, incident_id: UUID) -> Incident:
        incident = self.repository.get(incident_id)
        if incident is None:
            raise IncidentNotFoundError(f"incident not found: {incident_id}")
        return incident

    def list(self) -> list[Incident]:
        return self.repository.list()

    def reset_scenario(self, scenario: str) -> None:
        # Kept for API compatibility. New incidents always receive isolated state.
        return None

    def topology_for_incident(self, incident_id: UUID) -> NetworkTopology:
        incident = self.get(incident_id)
        registry, _ = self._runtime_for(incident)
        return registry.adapter.topology()

    def inventory(self, source_id: str | None = None) -> Inventory:
        if source_id in {None, "lab-simulator"}:
            return self.registry.adapter.inventory()
        assert source_id is not None
        factory = self.adapter_factories.get(source_id)
        if factory is None:
            raise ValueError(f"unknown data source: {source_id}")
        placeholder = Incident(
            title="inventory",
            description="inventory",
            source_device="",
            destination_device="",
            operating_mode=OperatingMode.OBSERVE,
            data_source_ids=[source_id],
            scenario="healthy",
        )
        return factory(placeholder).inventory()

    def integrations(self) -> builtins.list[dict[str, Any]]:
        rows = [
            {
                "id": "lab-simulator",
                "name": self.registry.adapter.display_name,
                "type": self.registry.adapter.source_type,
                "status": "CONNECTED",
                "capabilities": sorted(x.value for x in self.registry.adapter.capabilities),
                "read_only": False,
                "last_successful_observation": None,
            }
        ]
        for source_id, factory in self.adapter_factories.items():
            placeholder = Incident(
                title="integration",
                description="integration",
                source_device="",
                destination_device="",
                operating_mode=OperatingMode.OBSERVE,
                data_source_ids=[source_id],
                scenario="healthy",
            )
            adapter = factory(placeholder)
            connection_status = "CONNECTED"
            last_observed = None
            try:
                inventory = adapter.inventory()
                timestamps = [
                    item.last_observed_at
                    for group in (
                        inventory.devices,
                        inventory.interfaces,
                        inventory.services,
                        inventory.links,
                    )
                    for item in group
                    if item.last_observed_at is not None
                ]
                last_observed = max(timestamps, default=None)
            except RuntimeError:
                connection_status = "UNAVAILABLE"
            rows.append(
                {
                    "id": source_id,
                    "name": adapter.display_name,
                    "type": adapter.source_type,
                    "status": connection_status,
                    "capabilities": sorted(x.value for x in adapter.capabilities),
                    "read_only": adapter.read_only,
                    "last_successful_observation": last_observed,
                }
            )
        return rows

    def reject_remediation(self, incident_id: UUID, rejected_by: str, reason: str) -> Incident:
        incident = self.get(incident_id)
        if incident.status is not IncidentStatus.AWAITING_APPROVAL:
            raise ValueError("incident has no remediation awaiting approval")
        incident.approval_state = ApprovalState.REJECTED
        incident.events.append(
            InvestigationEvent(
                sequence=max((event.sequence for event in incident.events), default=0) + 1,
                incident_id=incident.id,
                run_id=incident.investigation_runs[-1].id,
                type="AGENT_DECISION_RECORDED",
                payload={
                    "summary": f"{rejected_by} rejected remediation: {reason}",
                    "decision": "REMEDIATION_REJECTED",
                },
            )
        )
        incident.proposed_remediation = None
        incident.status = IncidentStatus.INVESTIGATING
        incident.updated_at = datetime.now(UTC)
        self.repository.save(incident)
        return incident

    def agent_run(self, incident_id: UUID) -> Incident:
        incident = self.get(incident_id)
        _, runtime = self._runtime_for(incident)
        incident = runtime.run(incident)
        self.repository.save(incident)
        return incident

    def queue_agent_run(
        self, incident_id: UUID, provider: str = "deterministic"
    ) -> InvestigationRun:
        incident = self.get(incident_id)
        run = InvestigationRun(
            incident_id=incident.id,
            status=AgentRunStatus.QUEUED,
            provider=provider,
            model=provider,
            max_steps=self.runtime.max_steps,
            operating_mode=incident.operating_mode,
            data_sources=incident.data_source_ids,
        )
        incident.investigation_runs.append(run)
        _, runtime = self._runtime_for(incident)
        runtime._event(incident, run.id, "RUN_QUEUED", "Investigation queued")
        self.repository.save(incident)
        return run

    def execute_queued_run(self, incident_id: UUID, run_id: UUID) -> None:
        incident = self.get(incident_id)
        run = next((item for item in incident.investigation_runs if item.id == run_id), None)
        if run is None or run.status is not AgentRunStatus.QUEUED:
            return
        _, runtime = self._runtime_for(incident)
        runtime.run(incident, run)
        self.repository.save(incident)

    def cancel_run(self, incident_id: UUID, run_id: UUID) -> InvestigationRun:
        incident = self.get(incident_id)
        run = next((item for item in incident.investigation_runs if item.id == run_id), None)
        if run is None:
            raise ValueError("run not found for incident")
        if run.status not in {AgentRunStatus.QUEUED, AgentRunStatus.RUNNING}:
            raise ValueError(f"cannot cancel run in {run.status}")
        with self._lock:
            self._cancelled_runs.add(run_id)
        run.cancellation_requested_at = datetime.now(UTC)
        if run.status is AgentRunStatus.QUEUED:
            run.status = AgentRunStatus.CANCELLED
            run.cancelled_at = run.completed_at = datetime.now(UTC)
            _, runtime = self._runtime_for(incident)
            runtime._event(incident, run.id, "RUN_CANCELLED", "Cancelled before execution")
            self.repository.save(incident)
        else:
            self.repository.save(incident)
        return run

    def agent_continue(self, incident_id: UUID) -> Incident:
        return self.agent_run(incident_id)

    def investigate(self, incident_id: UUID) -> Incident:
        """Milestone 1 deterministic endpoint retained byte-for-byte in behavior."""
        incident = self.get(incident_id)
        self.registry, self.runtime = self._runtime_for(incident)
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
        if incident.operating_mode is OperatingMode.OBSERVE:
            self._record_observe_write_rejection(incident, "approval endpoint rejected")
            raise ValueError("OBSERVE mode is read-only; remediation approval is unavailable")
        self.registry, self.runtime = self._runtime_for(incident)
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

    def _new_incident_runtime(self, incident: Incident) -> tuple[ToolRegistry, AgentRuntime]:
        if incident.operating_mode is OperatingMode.OBSERVE:
            from relay.tools.network_tools import build_registry

            source_id = incident.data_source_ids[0]
            factory = self.adapter_factories.get(source_id)
            if factory is None:
                raise ValueError(f"unknown OBSERVE data source: {source_id}")
            registry = build_registry(
                factory(incident), self.registry.max_retries, include_writes=False
            )
        elif not self._base_claimed and self.registry.simulator.scenario == incident.scenario:
            self._base_claimed = True
            registry = self.registry
        else:
            from relay.network.simulator import NetworkSimulator
            from relay.tools.network_tools import build_registry

            registry = build_registry(
                NetworkSimulator(incident.scenario), self.registry.max_retries
            )
        runtime = AgentRuntime(
            registry,
            self.runtime.model,
            self.runtime.max_steps,
            self.runtime.max_repeated_calls,
            self.runtime.context_evidence_limit,
            checkpoint=self.repository.save,
            should_cancel=lambda run_id: run_id in self._cancelled_runs,
        )
        return registry, runtime

    def _runtime_for(self, incident: Incident) -> tuple[ToolRegistry, AgentRuntime]:
        existing = self._incident_runtimes.get(incident.id)
        if existing:
            return existing
        existing = self._new_incident_runtime(incident)
        # Reconstruct durable simulator state by replaying only completed, approved writes.
        registry, _ = existing
        for approval in incident.approval_records:
            if approval.execution_status == "SUCCEEDED":
                registry.execute(approval.tool_name, approval.arguments, approved=True)
        self._incident_runtimes[incident.id] = existing
        return existing

    def approve_and_remediate(self, incident_id: UUID) -> Incident:
        incident = self.get(incident_id)
        if incident.proposed_remediation is None:
            raise ValueError("incident has no remediation awaiting approval")
        return self.approve_remediation(incident_id, incident.proposed_remediation.id, "legacy-api")

    def _execute_remediation(self, incident: Incident, approval: ApprovalRecord) -> None:
        if incident.operating_mode is OperatingMode.OBSERVE:
            self._record_observe_write_rejection(incident, "remediation execution rejected")
            raise ValueError("OBSERVE mode is read-only; remediation execution is forbidden")
        remediation = incident.proposed_remediation
        if (
            remediation is None
            or approval.incident_id != incident.id
            or approval.remediation_id != remediation.id
            or approval.action_fingerprint != action_fingerprint(incident.id, remediation)
        ):
            raise ValueError("approval does not match the exact proposed action")
        _, runtime = self._runtime_for(incident)
        run = incident.investigation_runs[-1]
        runtime._event(incident, run.id, "REMEDIATION_STARTED", remediation.description)
        incident.transition_to(IncidentStatus.REMEDIATING)
        success, _ = self._execute_and_record(
            incident,
            remediation.tool_name,
            remediation.arguments,
            "Executed approved remediation",
            approved=True,
        )
        approval.execution_status = "SUCCEEDED" if success else "FAILED"
        runtime._event(
            incident,
            run.id,
            "REMEDIATION_COMPLETED",
            "Approved remediation completed" if success else "Approved remediation failed",
            {"success": success, "tool_call_id": str(incident.tool_calls[-1].id)},
        )
        if not success:
            incident.transition_to(IncidentStatus.INVESTIGATING)
            return
        incident.transition_to(IncidentStatus.VERIFYING)
        runtime._event(incident, run.id, "VERIFICATION_STARTED", "Recovery checks started")
        self._verify(incident)
        successful = bool(incident.verification_result and incident.verification_result.successful)
        runtime._event(
            incident,
            run.id,
            "VERIFICATION_COMPLETED",
            incident.verification_result.summary
            if incident.verification_result
            else "Verification failed",
            {"successful": successful},
        )
        if successful:
            run.status = AgentRunStatus.COMPLETED
            run.completed_at = datetime.now(UTC)
            runtime._event(
                incident, run.id, "RUN_COMPLETED", "Remediation verified; incident resolved"
            )

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
            provenance = result.provenance or ObservationProvenance(
                source_type=self.registry.adapter.source_type,
                adapter=self.registry.adapter.adapter_id,
            )
            incident.evidence.append(
                Evidence(
                    tool_call_id=call.id,
                    summary=summary,
                    observation=result.output,
                    status=result.status,
                    provenance=provenance,
                    run_id=incident.investigation_runs[-1].id
                    if incident.investigation_runs
                    else None,
                    is_verification=verification,
                )
            )
        return result.success, call.id

    def _record_observe_write_rejection(self, incident: Incident, reason: str) -> None:
        run_id = (
            incident.investigation_runs[-1].id
            if incident.investigation_runs
            else InvestigationRun(
                incident_id=incident.id,
                operating_mode=incident.operating_mode,
                data_sources=incident.data_source_ids,
            ).id
        )
        incident.events.append(
            InvestigationEvent(
                sequence=max((event.sequence for event in incident.events), default=0) + 1,
                incident_id=incident.id,
                run_id=run_id,
                type="OBSERVE_WRITE_REJECTED",
                payload={
                    "summary": reason,
                    "mode": incident.operating_mode.value,
                    "read_only": True,
                },
            )
        )
        self.repository.save(incident)
