from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from relay.api.dependencies import get_incident_service, get_simulator
from relay.api.schemas import IncidentCreate
from relay.domain.models import Evidence, Incident, NetworkTopology
from relay.network.simulator import NetworkSimulator
from relay.services.incidents import IncidentNotFoundError, IncidentService

router = APIRouter()
Service = Annotated[IncidentService, Depends(get_incident_service)]
Simulator = Annotated[NetworkSimulator, Depends(get_simulator)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/incidents", response_model=Incident, status_code=status.HTTP_201_CREATED)
def create_incident(payload: IncidentCreate, service: Service) -> Incident:
    try:
        return service.create(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/incidents", response_model=list[Incident])
def list_incidents(service: Service) -> list[Incident]:
    return service.list()


@router.get("/incidents/{incident_id}", response_model=Incident)
def get_incident(incident_id: UUID, service: Service) -> Incident:
    return _get(service, incident_id)


@router.post("/incidents/{incident_id}/investigate", response_model=Incident)
def investigate(incident_id: UUID, service: Service) -> Incident:
    try:
        return service.investigate(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/incidents/{incident_id}/approve-remediation", response_model=Incident)
def approve_remediation(incident_id: UUID, service: Service) -> Incident:
    try:
        return service.approve_and_remediate(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/incidents/{incident_id}/evidence", response_model=list[Evidence])
def get_evidence(incident_id: UUID, service: Service) -> list[Evidence]:
    return _get(service, incident_id).evidence


@router.get("/network/topology", response_model=NetworkTopology)
def topology(simulator: Simulator) -> NetworkTopology:
    return simulator.topology()


def _get(service: IncidentService, incident_id: UUID) -> Incident:
    try:
        return service.get(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
