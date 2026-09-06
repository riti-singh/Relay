from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from relay.agent.planner import AgentModel, AgentModelError, MalformedModelResponseError
from relay.domain.models import (
    ActionKind,
    AgentAction,
    AgentRunStatus,
    ApprovalState,
    Evidence,
    Hypothesis,
    HypothesisRevision,
    HypothesisStatus,
    Incident,
    IncidentStatus,
    InvestigationConclusion,
    InvestigationContext,
    InvestigationEvent,
    InvestigationRun,
    ObservationProvenance,
    ProposedRemediation,
    ToolCall,
)
from relay.tools.registry import ApprovalRequiredError, ToolRegistry

logger = logging.getLogger("relay.agent")


def action_fingerprint(incident_id: UUID, remediation: ProposedRemediation) -> str:
    canonical = json.dumps(
        {
            "incident_id": str(incident_id),
            "remediation_id": str(remediation.id),
            "tool_name": remediation.tool_name,
            "arguments": remediation.arguments,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class AgentRuntime:
    def __init__(
        self,
        registry: ToolRegistry,
        model: AgentModel,
        max_steps: int = 20,
        max_repeated_calls: int = 2,
        context_evidence_limit: int = 20,
        checkpoint: Callable[[Incident], None] | None = None,
        should_cancel: Callable[[UUID], bool] | None = None,
    ) -> None:
        self.registry, self.model = registry, model
        self.max_steps, self.max_repeated_calls, self.context_evidence_limit = (
            max_steps,
            max_repeated_calls,
            context_evidence_limit,
        )
        self.checkpoint = checkpoint
        self.should_cancel = should_cancel or (lambda _run_id: False)

    def run(self, incident: Incident, run: InvestigationRun | None = None) -> Incident:
        return asyncio.run(self.run_async(incident, run))

    async def run_async(self, incident: Incident, run: InvestigationRun | None = None) -> Incident:
        if incident.status in {IncidentStatus.OPEN, IncidentStatus.BLOCKED, IncidentStatus.FAILED}:
            incident.transition_to(IncidentStatus.INVESTIGATING)
        elif incident.status is not IncidentStatus.INVESTIGATING:
            raise ValueError(f"cannot investigate incident in {incident.status}")
        plan = [
            "Discover available diagnostic capabilities",
            "Collect source-backed observations",
            "Maintain evidence-backed hypotheses",
            "Conclude at the certainty supported by the selected source",
        ]
        incident.investigation_plan = plan
        if run is None:
            run = InvestigationRun(incident_id=incident.id, max_steps=self.max_steps, plan=plan)
            incident.investigation_runs.append(run)
            self._event(incident, run.id, "RUN_QUEUED", "Investigation queued")
        run.plan = plan
        run.operating_mode = incident.operating_mode
        run.data_sources = list(incident.data_source_ids)
        run.status = AgentRunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        self._event(incident, run.id, "RUN_STARTED", "Investigation started")
        repeated: dict[str, int] = {}
        for step in range(1, self.max_steps + 1):
            if self.should_cancel(run.id):
                run.cancellation_requested_at = run.cancellation_requested_at or datetime.now(UTC)
                run.status = AgentRunStatus.CANCELLED
                run.cancelled_at = run.completed_at = datetime.now(UTC)
                run.outcome = "Cancelled before the next safe agent step"
                incident.status = IncidentStatus.OPEN
                self._event(incident, run.id, "RUN_CANCELLED", run.outcome)
                return incident
            run.current_step = step
            context = self._context(incident, self.max_steps - step + 1)
            self._event(incident, run.id, "AGENT_DECISION_RECORDED", f"Choosing step {step}")
            try:
                decision = await self.model.decide_next_action(context)
            except (TimeoutError, AgentModelError, MalformedModelResponseError) as exc:
                run.outcome = f"Investigation blocked by planner failure: {exc}"
                run.completed_at = datetime.now(UTC)
                run.steps_used = step
                run.status = AgentRunStatus.BLOCKED
                run.error_category = "PROVIDER_ERROR"
                run.error_message = str(exc)
                incident.transition_to(IncidentStatus.BLOCKED)
                self._event(
                    incident,
                    run.id,
                    "RUN_FAILED",
                    str(exc),
                    {"legacy_event_type": "planner_failed", "category": "PROVIDER_ERROR"},
                )
                self._summarize(incident)
                return incident
            action = AgentAction(run_id=run.id, step=step, decision=decision)
            incident.actions.append(action)
            run.steps_used = step
            self._event(incident, run.id, "AGENT_DECISION_RECORDED", decision.summary)
            if decision.kind in {ActionKind.RUN_TOOL, ActionKind.REQUEST_EVIDENCE}:
                if not decision.tool_name:
                    action.successful = False
                    action.error = "tool_name is required"
                    continue
                signature = json.dumps([decision.tool_name, decision.arguments], sort_keys=True)
                repeated[signature] = repeated.get(signature, 0) + 1
                if repeated[signature] > self.max_repeated_calls:
                    action.successful = False
                    action.error = "repeated tool-call limit exceeded"
                    self._event(incident, run.id, "AGENT_DECISION_RECORDED", action.error)
                    continue
                call = self._execute(
                    incident, decision.tool_name, decision.arguments, decision.summary, run.id
                )
                action.tool_call_id, action.successful, action.error = (
                    call.id,
                    bool(call.success),
                    call.error,
                )
            elif decision.kind is ActionKind.UPDATE_HYPOTHESIS:
                self._update_hypothesis(incident, decision)
                event_type = (
                    "HYPOTHESIS_CREATED"
                    if len(incident.hypotheses[-1].history) == 1
                    else "HYPOTHESIS_REVISED"
                )
                self._event(incident, run.id, event_type, decision.summary)
            elif decision.kind is ActionKind.PROPOSE_REMEDIATION:
                if (
                    not decision.tool_name
                    or self.registry.risk(decision.tool_name).value == "READ_ONLY"
                ):
                    action.successful = False
                    action.error = "remediation must name an available write tool"
                    continue
                proposal = ProposedRemediation(
                    description=decision.remediation_description or decision.summary,
                    tool_name=decision.tool_name,
                    arguments=decision.arguments,
                    expected_root_cause=next(
                        (
                            h.statement
                            for h in incident.hypotheses
                            if h.status is HypothesisStatus.CONFIRMED
                        ),
                        None,
                    ),
                )
                incident.proposed_remediation = proposal
                incident.remediation_history.append(proposal)
                incident.approval_state = ApprovalState.PENDING
                incident.transition_to(IncidentStatus.AWAITING_APPROVAL)
                run.outcome = "Root cause identified; remediation awaits exact-action approval"
                run.completed_at = datetime.now(UTC)
                run.status = AgentRunStatus.AWAITING_APPROVAL
                self._event(incident, run.id, "REMEDIATION_PROPOSED", proposal.description)
                self._event(
                    incident, run.id, "APPROVAL_REQUIRED", "Exact-action human approval required"
                )
                self._summarize(incident)
                return incident
            elif decision.kind is ActionKind.DECLARE_RESOLVED:
                incident.transition_to(IncidentStatus.RESOLVED)
                confirmed = [
                    item
                    for item in incident.hypotheses
                    if item.status is HypothesisStatus.CONFIRMED
                ]
                if confirmed:
                    finding = confirmed[-1]
                    incident.conclusion = InvestigationConclusion(
                        kind="ASSESSMENT"
                        if incident.operating_mode.value == "OBSERVE"
                        else "ROOT_CAUSE",
                        summary=finding.statement,
                        confidence=finding.confidence,
                        evidence_ids=finding.supporting_evidence_ids,
                    )
                incident.pending_operator_request = None
                run.outcome = decision.summary
                run.completed_at = datetime.now(UTC)
                run.status = AgentRunStatus.COMPLETED
                self._event(incident, run.id, "RUN_COMPLETED", decision.summary)
                self._summarize(incident)
                return incident
            elif decision.kind is ActionKind.DECLARE_BLOCKED:
                incident.transition_to(IncidentStatus.BLOCKED)
                run.outcome = decision.summary
                run.completed_at = datetime.now(UTC)
                run.status = AgentRunStatus.BLOCKED
                self._event(incident, run.id, "RUN_FAILED", decision.summary)
                self._summarize(incident)
                return incident
        incident.transition_to(IncidentStatus.BLOCKED)
        run.outcome = "Investigation reached configured step limit"
        run.completed_at = datetime.now(UTC)
        run.status = AgentRunStatus.BLOCKED
        self._event(incident, run.id, "RUN_FAILED", run.outcome)
        self._summarize(incident)
        return incident

    def _context(self, incident: Incident, remaining: int) -> InvestigationContext:
        recent_calls = incident.tool_calls[-self.context_evidence_limit :]
        call_ids = {call.id for call in recent_calls}
        evidence = [item for item in incident.evidence if item.tool_call_id in call_ids][
            -self.context_evidence_limit :
        ]
        return InvestigationContext(
            incident_id=incident.id,
            incident_description=incident.description,
            source_device=incident.source_device,
            destination_device=incident.destination_device,
            topology_summary=(
                "Topology and paths are available only through registered source capabilities"
            ),
            current_plan=incident.investigation_plan,
            recent_tool_calls=recent_calls,
            evidence=evidence,
            active_hypotheses=[
                h for h in incident.hypotheses if h.status is not HypothesisStatus.REJECTED
            ],
            rejected_hypotheses=[
                h for h in incident.hypotheses if h.status is HypothesisStatus.REJECTED
            ],
            remediation_proposal=incident.proposed_remediation,
            incident_status=incident.status,
            remaining_step_budget=remaining,
            running_summary=incident.investigation_summary,
            available_tools=self.registry.schemas(),
            operating_mode=incident.operating_mode,
            operator_request=incident.pending_operator_request,
        )

    def _execute(
        self,
        incident: Incident,
        name: str,
        arguments: dict[str, object],
        summary: str,
        run_id: UUID,
        approved: bool = False,
        verification: bool = False,
    ) -> ToolCall:
        risk = self.registry.risk(name)
        call = ToolCall(
            tool_name=name, arguments=arguments, risk=risk, state_changing=risk.value != "READ_ONLY"
        )
        incident.tool_calls.append(call)
        self._event(
            incident,
            run_id,
            "TOOL_CALL_STARTED",
            name,
            {"tool_call_id": str(call.id), "tool_name": name, "arguments": arguments},
        )
        try:
            result = self.registry.execute(name, arguments, approved=approved)
        except ApprovalRequiredError as exc:
            call.success = False
            call.error = str(exc)
            self._event(
                incident, run_id, "TOOL_CALL_FAILED", str(exc), {"tool_call_id": str(call.id)}
            )
            return call
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
                    run_id=run_id,
                    is_verification=verification,
                )
            )
            run = next(r for r in incident.investigation_runs if r.id == run_id)
            run.tool_call_count += 1
            self._event(
                incident,
                run_id,
                "TOOL_CALL_COMPLETED",
                f"{name} completed after {result.retry_count} retries",
                {"tool_call_id": str(call.id), "success": True},
            )
            self._event(
                incident,
                run_id,
                "EVIDENCE_ADDED",
                summary,
                {
                    "evidence_id": str(incident.evidence[-1].id),
                    "tool_call_id": str(call.id),
                    "status": result.status.value,
                    "mode": incident.operating_mode.value,
                    "provenance": provenance.model_dump(mode="json"),
                },
            )
        else:
            run = next(r for r in incident.investigation_runs if r.id == run_id)
            run.tool_call_count += 1
            self._event(
                incident,
                run_id,
                "TOOL_CALL_FAILED",
                f"{name}: {result.error_category}: {result.error}",
                {"tool_call_id": str(call.id)},
            )
        return call

    @staticmethod
    def _update_hypothesis(incident: Incident, decision: object) -> None:
        from relay.domain.models import AgentDecision

        assert isinstance(decision, AgentDecision)
        hypothesis = next((h for h in incident.hypotheses if h.id == decision.hypothesis_id), None)
        if hypothesis is None:
            hypothesis = Hypothesis(
                statement=decision.hypothesis or decision.summary,
                suspected_component=decision.suspected_component,
                confidence=decision.confidence or 0.5,
                supporting_evidence_ids=decision.supporting_evidence_ids,
                contradicting_evidence_ids=decision.contradicting_evidence_ids,
                status=decision.hypothesis_status or HypothesisStatus.ACTIVE,
            )
            incident.hypotheses.append(hypothesis)
        else:
            hypothesis.confidence = (
                decision.confidence if decision.confidence is not None else hypothesis.confidence
            )
            hypothesis.status = decision.hypothesis_status or hypothesis.status
            hypothesis.supporting_evidence_ids = list(
                dict.fromkeys(
                    [*hypothesis.supporting_evidence_ids, *decision.supporting_evidence_ids]
                )
            )
            hypothesis.contradicting_evidence_ids = list(
                dict.fromkeys(
                    [*hypothesis.contradicting_evidence_ids, *decision.contradicting_evidence_ids]
                )
            )
        hypothesis.history.append(
            HypothesisRevision(
                confidence=hypothesis.confidence,
                status=hypothesis.status,
                supporting_evidence_ids=hypothesis.supporting_evidence_ids,
                contradicting_evidence_ids=hypothesis.contradicting_evidence_ids,
                summary=decision.summary,
            )
        )

    def _event(
        self,
        incident: Incident,
        run_id: UUID,
        event_type: str,
        summary: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        sequence = max((event.sequence for event in incident.events), default=0) + 1
        body = {"summary": summary, "mode": incident.operating_mode.value, **(payload or {})}
        incident.events.append(
            InvestigationEvent(
                sequence=sequence,
                incident_id=incident.id,
                run_id=run_id,
                type=event_type,
                payload=body,
            )
        )
        run = next((item for item in incident.investigation_runs if item.id == run_id), None)
        if run:
            run.last_event_sequence = sequence
        incident.updated_at = datetime.now(UTC)
        if self.checkpoint:
            self.checkpoint(incident)
        logger.info(
            "relay_event",
            extra={"run_id": str(run_id), "event_type": event_type, "summary": summary},
        )

    @staticmethod
    def _summarize(incident: Incident) -> None:
        confirmed = [
            h.statement for h in incident.hypotheses if h.status is HypothesisStatus.CONFIRMED
        ]
        finding = ", ".join(confirmed) if confirmed else "none"
        incident.investigation_summary = (
            f"{len(incident.tool_calls)} tool calls, {len(incident.evidence)} observations. "
            f"Confirmed: {finding}. Status: {incident.status}."
        )
