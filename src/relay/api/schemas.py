from pydantic import BaseModel, Field


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    source_device: str = Field(min_length=1)
    destination_device: str = Field(min_length=1)
