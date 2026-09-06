from uuid import UUID

from pydantic import BaseModel, Field


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    source_device: str = Field(min_length=1)
    destination_device: str = Field(min_length=1)
    scenario: str = "interface-disabled"


class RemediationApproval(BaseModel):
    approved_by: str = Field(min_length=1)
    remediation_id: UUID


class RemediationRejection(BaseModel):
    rejected_by: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


class AgentRunRequest(BaseModel):
    planner: str = Field(default="deterministic", pattern="^(deterministic|ai)$")
