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


class OperatingMode(StrEnum):
    LAB = "LAB"
    OBSERVE = "OBSERVE"


class ObservationStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"


class Freshness(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class AdapterCapability(StrEnum):
    TOPOLOGY = "TOPOLOGY"
    INTERFACE_STATE = "INTERFACE_STATE"
    ROUTES = "ROUTES"
    REACHABILITY = "REACHABILITY"
    LATENCY = "LATENCY"
    PATH_TRACE = "PATH_TRACE"
    PATH_COMPARISON = "PATH_COMPARISON"
    PROBE_METADATA = "PROBE_METADATA"
    DNS = "DNS"
    SERVICE_CONNECTIVITY = "SERVICE_CONNECTIVITY"
    POLICY = "POLICY"
    LINK_METRICS = "LINK_METRICS"
    PACKET_LOSS = "PACKET_LOSS"
    CONFIGURATION = "CONFIGURATION"
    RECENT_CHANGES = "RECENT_CHANGES"
    INVENTORY = "INVENTORY"


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


class ResourceStatus(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class InventoryInterface(BaseModel):
    id: str
    device_id: str
    name: str
    status: ResourceStatus = ResourceStatus.UNKNOWN
    management_address: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    telemetry_source: str
    last_observed_at: datetime | None = None


class Device(BaseModel):
    id: str
    hostname: str
    display_name: str
    type: str
    management_address: str | None = None
    vendor: str | None = None
    platform: str | None = None
    site: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    telemetry_source: str
    status: ResourceStatus = ResourceStatus.UNKNOWN
    last_observed_at: datetime | None = None


class ServiceResource(BaseModel):
    id: str
    display_name: str
    endpoint: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    telemetry_source: str
    status: ResourceStatus = ResourceStatus.UNKNOWN
    last_observed_at: datetime | None = None


class InventoryLink(BaseModel):
    id: str
    device_a: str
    device_b: str
    interface_a: str | None = None
    interface_b: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    telemetry_source: str
    status: ResourceStatus = ResourceStatus.UNKNOWN
    last_observed_at: datetime | None = None


class Inventory(BaseModel):
    devices: list[Device] = Field(default_factory=list)
    interfaces: list[InventoryInterface] = Field(default_factory=list)
    services: list[ServiceResource] = Field(default_factory=list)
    links: list[InventoryLink] = Field(default_factory=list)


class ObservationProvenance(BaseModel):
    source_type: str
    adapter: str
    resource_id: str | None = None
    observed_at: datetime | None = None
    collected_at: datetime = Field(default_factory=utc_now)
    freshness: Freshness = Freshness.FRESH
    query_identity: str | None = None
    measurement: str | None = None
    measurement_id: str | None = None
    probe_id: str | None = None
    target: str | None = None
    measurement_type: str | None = None
    probe_asn: int | None = None
    probe_country: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class DataSourceClassification(StrEnum):
    LAB = "LAB"
    DEMO = "DEMO"
    LIVE = "LIVE"


class DataSourceStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class FreshnessPolicy(BaseModel):
    max_age_seconds: int = Field(ge=0)
    description: str


class DataSource(BaseModel):
    id: str
    adapter_type: str
    name: str
    classification: DataSourceClassification
    read_only: bool
    capabilities: list[AdapterCapability]
    status: DataSourceStatus = DataSourceStatus.UNKNOWN
    last_successful_query: datetime | None = None
    freshness_policy: FreshnessPolicy
    configuration: dict[str, Any] = Field(default_factory=dict)


class AdapterObservation(BaseModel):
    status: ObservationStatus
    data: dict[str, Any] = Field(default_factory=dict)
    provenance: ObservationProvenance
    message: str | None = None


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
    status: ObservationStatus = ObservationStatus.SUCCESS
    provenance: ObservationProvenance | None = None
    error_category: ToolErrorCategory | None = None
    error: str | None = None
    retry_count: int = 0
    duration_ms: float = 0


class Evidence(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tool_call_id: UUID
    summary: str
    observation: dict[str, Any]
    status: ObservationStatus = ObservationStatus.SUCCESS
    provenance: ObservationProvenance = Field(
        default_factory=lambda: ObservationProvenance(source_type="simulator", adapter="lab")
    )
    run_id: UUID | None = None
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
    operating_mode: OperatingMode = OperatingMode.LAB
    data_sources: list[str] = Field(default_factory=lambda: ["lab-simulator"])


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
    operating_mode: OperatingMode = OperatingMode.LAB
    operator_request: str | None = None


class CommentTarget(StrEnum):
    INVESTIGATION = "INVESTIGATION"
    EVIDENCE = "EVIDENCE"
    HYPOTHESIS = "HYPOTHESIS"
    RUN_EVENT = "RUN_EVENT"


class InvestigationComment(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    author: str
    body: str
    target_type: CommentTarget = CommentTarget.INVESTIGATION
    target_id: UUID | None = None
    request_agent_step: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class InvestigationConclusion(BaseModel):
    kind: str = Field(pattern="^(ROOT_CAUSE|ASSESSMENT)$")
    summary: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[UUID] = Field(default_factory=list)
    recorded_at: datetime = Field(default_factory=utc_now)


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
    operating_mode: OperatingMode = OperatingMode.LAB
    data_source_ids: list[str] = Field(default_factory=lambda: ["lab-simulator"])
    resource_ids: list[str] = Field(default_factory=list)
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
    comments: list[InvestigationComment] = Field(default_factory=list)
    pending_operator_request: str | None = None
    conclusion: InvestigationConclusion | None = None

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
