from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from relay.api.dependencies import get_incident_service, get_simulator
from relay.api.schemas import IncidentCreate, RemediationApproval
from relay.domain.models import (
    AgentAction,
    Evidence,
    Hypothesis,
    Incident,
    NetworkTopology,
    ProposedRemediation,
    VerificationResult,
)
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


@router.post("/incidents/{incident_id}/agent/run", response_model=Incident)
def run_agent(incident_id: UUID, service: Service) -> Incident:
    return _agent_call(service, incident_id, continue_run=False)


@router.post("/incidents/{incident_id}/agent/continue", response_model=Incident)
def continue_agent(incident_id: UUID, service: Service) -> Incident:
    return _agent_call(service, incident_id, continue_run=True)


def _agent_call(service: IncidentService, incident_id: UUID, continue_run: bool) -> Incident:
    try:
        return (
            service.agent_continue(incident_id) if continue_run else service.agent_run(incident_id)
        )
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


@router.post(
    "/incidents/{incident_id}/remediations/{remediation_id}/approve", response_model=Incident
)
def approve_specific_remediation(
    incident_id: UUID,
    remediation_id: UUID,
    payload: RemediationApproval,
    service: Service,
) -> Incident:
    if payload.remediation_id != remediation_id:
        raise HTTPException(status_code=422, detail="path and body remediation IDs differ")
    try:
        return service.approve_remediation(incident_id, remediation_id, payload.approved_by)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/incidents/{incident_id}/evidence", response_model=list[Evidence])
def get_evidence(incident_id: UUID, service: Service) -> list[Evidence]:
    return _get(service, incident_id).evidence


@router.get("/incidents/{incident_id}/investigation", response_model=Incident)
def get_investigation(incident_id: UUID, service: Service) -> Incident:
    return _get(service, incident_id)


@router.get("/incidents/{incident_id}/hypotheses", response_model=list[Hypothesis])
def get_hypotheses(incident_id: UUID, service: Service) -> list[Hypothesis]:
    return _get(service, incident_id).hypotheses


@router.get("/incidents/{incident_id}/actions", response_model=list[AgentAction])
def get_actions(incident_id: UUID, service: Service) -> list[AgentAction]:
    return _get(service, incident_id).actions


@router.get("/incidents/{incident_id}/remediations", response_model=list[ProposedRemediation])
def get_remediations(incident_id: UUID, service: Service) -> list[ProposedRemediation]:
    return _get(service, incident_id).remediation_history


@router.get("/incidents/{incident_id}/verification", response_model=VerificationResult | None)
def get_verification(incident_id: UUID, service: Service) -> VerificationResult | None:
    return _get(service, incident_id).verification_result


@router.get("/network/topology", response_model=NetworkTopology)
def topology(simulator: Simulator) -> NetworkTopology:
    return simulator.topology()


def _get(service: IncidentService, incident_id: UUID) -> Incident:
    try:
        return service.get(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
