from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class IncidentStatus(StrEnum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REMEDIATING = "REMEDIATING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"


class ApprovalState(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


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


class NetworkLink(BaseModel):
    device_a: str
    interface_a: str
    device_b: str
    interface_b: str
    latency_ms: int = 2


class NetworkTopology(BaseModel):
    devices: list[NetworkDevice]
    links: list[NetworkLink]


class ToolCall(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tool_name: str
    arguments: dict[str, Any]
    state_changing: bool = False
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    success: bool | None = None
    error: str | None = None


class ToolResult(BaseModel):
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class Evidence(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tool_call_id: UUID
    summary: str
    observation: dict[str, Any]
    recorded_at: datetime = Field(default_factory=utc_now)


class Hypothesis(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    statement: str
    confidence: float = Field(ge=0, le=1)
    supporting_evidence_ids: list[UUID]


class ProposedRemediation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    description: str
    tool_name: str
    arguments: dict[str, Any]
    impactful: bool = True


class VerificationResult(BaseModel):
    successful: bool
    summary: str
    tool_call_ids: list[UUID]


class InvestigationRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    plan: list[str]
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    outcome: str | None = None


class Incident(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str
    description: str
    source_device: str
    destination_device: str
    status: IncidentStatus = IncidentStatus.OPEN
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    investigation_plan: list[str] = Field(default_factory=list)
    investigation_runs: list[InvestigationRun] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    proposed_remediation: ProposedRemediation | None = None
    approval_state: ApprovalState = ApprovalState.NOT_REQUIRED
    verification_result: VerificationResult | None = None

    def transition_to(self, target: IncidentStatus) -> None:
        allowed = {
            IncidentStatus.OPEN: {IncidentStatus.INVESTIGATING},
            IncidentStatus.INVESTIGATING: {
                IncidentStatus.AWAITING_APPROVAL,
                IncidentStatus.FAILED,
            },
            IncidentStatus.AWAITING_APPROVAL: {IncidentStatus.REMEDIATING},
            IncidentStatus.REMEDIATING: {IncidentStatus.VERIFYING, IncidentStatus.FAILED},
            IncidentStatus.VERIFYING: {IncidentStatus.RESOLVED, IncidentStatus.FAILED},
        }
        if target not in allowed.get(self.status, set()):
            raise ValueError(f"invalid incident transition: {self.status} -> {target}")
        self.status = target
        self.updated_at = utc_now()
