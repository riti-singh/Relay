from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from relay.agent.planner import AgentModel, AgentModelError, MalformedModelResponseError
from relay.domain.models import (
    ActionKind,
    AgentAction,
    ApprovalState,
    Evidence,
    Hypothesis,
    HypothesisRevision,
    HypothesisStatus,
    Incident,
    IncidentStatus,
    InvestigationContext,
    InvestigationEvent,
    InvestigationRun,
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
    ) -> None:
        self.registry, self.model = registry, model
        self.max_steps, self.max_repeated_calls, self.context_evidence_limit = (
            max_steps,
            max_repeated_calls,
            context_evidence_limit,
        )

    def run(self, incident: Incident) -> Incident:
        return asyncio.run(self.run_async(incident))

    async def run_async(self, incident: Incident) -> Incident:
        if incident.status in {IncidentStatus.OPEN, IncidentStatus.BLOCKED, IncidentStatus.FAILED}:
            incident.transition_to(IncidentStatus.INVESTIGATING)
        elif incident.status is not IncidentStatus.INVESTIGATING:
            raise ValueError(f"cannot investigate incident in {incident.status}")
        plan = [
            "Establish connectivity and path",
            "Inspect routing, interfaces, service, DNS, policy, link health, and drift",
            "Maintain evidence-backed hypotheses",
            "Propose an exact remediation and pause for approval",
        ]
        incident.investigation_plan = plan
        run = InvestigationRun(plan=plan)
        incident.investigation_runs.append(run)
        self._event(incident, run.id, "investigation_started", "Bounded investigation started")
        repeated: dict[str, int] = {}
        for step in range(1, self.max_steps + 1):
            context = self._context(incident, self.max_steps - step + 1)
            self._event(incident, run.id, "planner_invoked", f"Planner invoked for step {step}")
            try:
                decision = await self.model.decide_next_action(context)
            except (TimeoutError, AgentModelError, MalformedModelResponseError) as exc:
                run.outcome = f"Investigation blocked by planner failure: {exc}"
                run.completed_at = datetime.now(UTC)
                run.steps_used = step
                incident.transition_to(IncidentStatus.BLOCKED)
                self._event(incident, run.id, "planner_failed", str(exc))
                self._summarize(incident)
                return incident
            action = AgentAction(run_id=run.id, step=step, decision=decision)
            incident.actions.append(action)
            run.steps_used = step
            self._event(incident, run.id, "action_selected", decision.summary)
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
                    self._event(incident, run.id, "action_rejected", action.error)
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
                self._event(incident, run.id, "hypothesis_updated", decision.summary)
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
                self._event(incident, run.id, "remediation_proposed", proposal.description)
                self._summarize(incident)
                return incident
            elif decision.kind is ActionKind.DECLARE_RESOLVED:
                incident.transition_to(IncidentStatus.RESOLVED)
                run.outcome = decision.summary
                run.completed_at = datetime.now(UTC)
                self._summarize(incident)
                return incident
            elif decision.kind is ActionKind.DECLARE_BLOCKED:
                incident.transition_to(IncidentStatus.BLOCKED)
                run.outcome = decision.summary
                run.completed_at = datetime.now(UTC)
                self._summarize(incident)
                return incident
        incident.transition_to(IncidentStatus.BLOCKED)
        run.outcome = "Investigation reached configured step limit"
        run.completed_at = datetime.now(UTC)
        self._event(incident, run.id, "step_limit_reached", run.outcome)
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
                "5-device simulated WAN; details available through get_network_topology"
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
        self._event(incident, run_id, "tool_started", name)
        try:
            result = self.registry.execute(name, arguments, approved=approved)
        except ApprovalRequiredError as exc:
            call.success = False
            call.error = str(exc)
            self._event(incident, run_id, "tool_failed", str(exc))
            return call
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
            self._event(
                incident,
                run_id,
                "tool_completed",
                f"{name} completed after {result.retry_count} retries",
            )
        else:
            self._event(
                incident, run_id, "tool_failed", f"{name}: {result.error_category}: {result.error}"
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

    @staticmethod
    def _event(incident: Incident, run_id: UUID, event_type: str, summary: str) -> None:
        incident.events.append(
            InvestigationEvent(run_id=run_id, event_type=event_type, summary=summary)
        )
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
