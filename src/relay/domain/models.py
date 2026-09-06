from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class IncidentStatus(StrEnum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REMEDIATING = "REMEDIATING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class AgentRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class ApprovalState(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ToolRisk(StrEnum):
    READ_ONLY = "READ_ONLY"
    LOW_RISK_WRITE = "LOW_RISK_WRITE"
    HIGH_RISK_WRITE = "HIGH_RISK_WRITE"


class ToolErrorCategory(StrEnum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TEMPORARY_FAILURE = "TEMPORARY_FAILURE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class HypothesisStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    CONFIRMED = "CONFIRMED"


class ActionKind(StrEnum):
    RUN_TOOL = "RUN_TOOL"
    UPDATE_HYPOTHESIS = "UPDATE_HYPOTHESIS"
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"
    PROPOSE_REMEDIATION = "PROPOSE_REMEDIATION"
    DECLARE_RESOLVED = "DECLARE_RESOLVED"
    DECLARE_BLOCKED = "DECLARE_BLOCKED"


class Interface(BaseModel):
    name: str
    admin_up: bool = True
    operational_up: bool = True
    ip_address: str | None = None


class NetworkDevice(BaseModel):
    id: str
    name: str
    kind: str
    interfaces: list[Interface]
    routes: dict[str, str] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    baseline_config: dict[str, Any] = Field(default_factory=dict)
    acl_rules: list[dict[str, Any]] = Field(default_factory=list)


class NetworkLink(BaseModel):
    device_a: str
    interface_a: str
    device_b: str
    interface_b: str
    latency_ms: int = 2
    packet_loss_percent: float = 0


class NetworkTopology(BaseModel):
    devices: list[NetworkDevice]
    links: list[NetworkLink]


class ToolCall(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tool_name: str
    arguments: dict[str, Any]
    risk: ToolRisk = ToolRisk.READ_ONLY
    state_changing: bool = False
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    duration_ms: float | None = None
    success: bool | None = None
    retry_count: int = 0
    error_category: ToolErrorCategory | None = None
    error: str | None = None


class ToolResult(BaseModel):
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error_category: ToolErrorCategory | None = None
    error: str | None = None
    retry_count: int = 0
    duration_ms: float = 0


class Evidence(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tool_call_id: UUID
    summary: str
    observation: dict[str, Any]
    is_verification: bool = False
    recorded_at: datetime = Field(default_factory=utc_now)


class HypothesisRevision(BaseModel):
    confidence: float = Field(ge=0, le=1)
    status: HypothesisStatus
    supporting_evidence_ids: list[UUID] = Field(default_factory=list)
    contradicting_evidence_ids: list[UUID] = Field(default_factory=list)
    summary: str
    recorded_at: datetime = Field(default_factory=utc_now)


class Hypothesis(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    statement: str
    suspected_component: str | None = None
    confidence: float = Field(ge=0, le=1)
    supporting_evidence_ids: list[UUID] = Field(default_factory=list)
    contradicting_evidence_ids: list[UUID] = Field(default_factory=list)
    status: HypothesisStatus = HypothesisStatus.ACTIVE
    history: list[HypothesisRevision] = Field(default_factory=list)


class ProposedRemediation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    description: str
    tool_name: str
    arguments: dict[str, Any]
    expected_root_cause: str | None = None
    impactful: bool = True


class ApprovalRecord(BaseModel):
    remediation_id: UUID
    incident_id: UUID
    approved_by: str
    approved_at: datetime = Field(default_factory=utc_now)
    tool_name: str
    arguments: dict[str, Any]
    action_fingerprint: str
    execution_status: str = "PENDING"


class VerificationResult(BaseModel):
    successful: bool
    summary: str
    tool_call_ids: list[UUID]
    recorded_at: datetime = Field(default_factory=utc_now)


class AgentDecision(BaseModel):
    kind: ActionKind
    summary: str
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    hypothesis_id: UUID | None = None
    hypothesis: str | None = None
    suspected_component: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    hypothesis_status: HypothesisStatus | None = None
    supporting_evidence_ids: list[UUID] = Field(default_factory=list)
    contradicting_evidence_ids: list[UUID] = Field(default_factory=list)
    remediation_description: str | None = None


class AgentAction(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    step: int
    decision: AgentDecision
    tool_call_id: UUID | None = None
    successful: bool = True
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class InvestigationRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    incident_id: UUID | None = None
    status: AgentRunStatus = AgentRunStatus.QUEUED
    provider: str = "deterministic"
    model: str = "deterministic"
    requested_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_requested_at: datetime | None = None
    current_step: int = 0
    max_steps: int = 20
    tool_call_count: int = 0
    error_category: str | None = None
    error_message: str | None = None
    last_event_sequence: int = 0
    plan: list[str] = Field(default_factory=list)
    outcome: str | None = None
    steps_used: int = 0


class InvestigationContext(BaseModel):
    incident_id: UUID
    incident_description: str
    source_device: str
    destination_device: str
    topology_summary: str
    current_plan: list[str]
    recent_tool_calls: list[ToolCall]
    evidence: list[Evidence]
    active_hypotheses: list[Hypothesis]
    rejected_hypotheses: list[Hypothesis]
    remediation_proposal: ProposedRemediation | None
    incident_status: IncidentStatus
    remaining_step_budget: int
    running_summary: str
    available_tools: dict[str, dict[str, Any]]


class InvestigationEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    sequence: int = 0
    incident_id: UUID | None = None
    run_id: UUID
    type: str = "AGENT_DECISION_RECORDED"
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="before")
    @classmethod
    def migrate_milestone_three_event(cls, value: Any) -> Any:
        if isinstance(value, dict) and "event_type" in value:
            value = dict(value)
            value["type"] = value.pop("event_type")
            value["payload"] = {"summary": value.pop("summary", "")}
        return value

    @property
    def event_type(self) -> str:
        """Compatibility alias for Milestone 3 clients."""
        return str(self.payload.get("legacy_event_type", self.type))

    @property
    def summary(self) -> str:
        return str(self.payload.get("summary", ""))


class Incident(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str
    description: str
    source_device: str
    destination_device: str
    scenario: str = "interface-disabled"
    status: IncidentStatus = IncidentStatus.OPEN
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    investigation_plan: list[str] = Field(default_factory=list)
    investigation_summary: str = ""
    investigation_runs: list[InvestigationRun] = Field(default_factory=list)
    actions: list[AgentAction] = Field(default_factory=list)
    events: list[InvestigationEvent] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    proposed_remediation: ProposedRemediation | None = None
    remediation_history: list[ProposedRemediation] = Field(default_factory=list)
    approval_state: ApprovalState = ApprovalState.NOT_REQUIRED
    approval_records: list[ApprovalRecord] = Field(default_factory=list)
    verification_result: VerificationResult | None = None

    def transition_to(self, target: IncidentStatus) -> None:
        allowed = {
            IncidentStatus.OPEN: {IncidentStatus.INVESTIGATING},
            IncidentStatus.INVESTIGATING: {
                IncidentStatus.AWAITING_APPROVAL,
                IncidentStatus.BLOCKED,
                IncidentStatus.RESOLVED,
                IncidentStatus.FAILED,
            },
            IncidentStatus.AWAITING_APPROVAL: {IncidentStatus.REMEDIATING},
            IncidentStatus.REMEDIATING: {IncidentStatus.VERIFYING, IncidentStatus.INVESTIGATING},
            IncidentStatus.VERIFYING: {IncidentStatus.RESOLVED, IncidentStatus.INVESTIGATING},
            IncidentStatus.BLOCKED: {IncidentStatus.INVESTIGATING},
            IncidentStatus.FAILED: {IncidentStatus.INVESTIGATING},
        }
        if target not in allowed.get(self.status, set()):
            raise ValueError(f"invalid incident transition: {self.status} -> {target}")
        self.status = target
        self.updated_at = utc_now()
