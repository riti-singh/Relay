from uuid import UUID

from pydantic import BaseModel, Field

from relay.domain.models import CommentTarget, OperatingMode


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    source_device: str = Field(min_length=1)
    destination_device: str = Field(min_length=1)
    scenario: str = "interface-disabled"
    operating_mode: OperatingMode = OperatingMode.LAB
    data_source_ids: list[str] | None = None
    resource_ids: list[str] | None = None


class RemediationApproval(BaseModel):
    approved_by: str = Field(min_length=1)
    remediation_id: UUID


class RemediationRejection(BaseModel):
    rejected_by: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


class AgentRunRequest(BaseModel):
    planner: str = Field(default="deterministic", pattern="^(deterministic|ai)$")


class CommentCreate(BaseModel):
    author: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=2000)
    target_type: CommentTarget = CommentTarget.INVESTIGATION
    target_id: UUID | None = None
    request_agent_step: bool = False
