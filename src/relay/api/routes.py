import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from relay.api.dependencies import get_incident_service, get_simulator
from relay.api.schemas import (
    AgentRunRequest,
    CommentCreate,
    IncidentCreate,
    RemediationApproval,
    RemediationRejection,
)
from relay.config import get_settings
from relay.domain.models import (
    AgentAction,
    Evidence,
    Hypothesis,
    Incident,
    Inventory,
    InvestigationRun,
    NetworkTopology,
    ProposedRemediation,
    VerificationResult,
)
from relay.network.simulator import SCENARIOS, NetworkSimulator
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
        service.reset_scenario(payload.scenario)
        return service.create(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/incidents", response_model=list[Incident])
def list_incidents(service: Service) -> list[Incident]:
    return service.list()


@router.get("/scenarios")
def list_scenarios() -> list[dict[str, str]]:
    labels = {
        "interface-disabled": "Interface Disabled",
        "incorrect-route": "Incorrect Static Route",
        "acl-block": "ACL Blocking Application Traffic",
        "dns-failure": "DNS Failure",
        "degraded-link": "Congested Link",
        "config-drift": "Configuration Drift",
    }
    return [
        {
            "id": key,
            "name": labels[key],
            "description": item.description,
            "source_device": item.source,
            "destination_device": item.destination,
        }
        for key, item in SCENARIOS.items()
    ]


@router.get("/observe/datasets")
def observe_datasets() -> list[dict[str, str]]:
    return [
        {
            "id": "healthy",
            "name": "Healthy external network",
            "description": "Fresh telemetry with a healthy path",
            "source_device": "edge-01",
            "destination_device": "orders-api",
        },
        {
            "id": "interface-failure",
            "name": "External interface failure",
            "description": "Observed core uplink is operationally down",
            "source_device": "edge-01",
            "destination_device": "orders-api",
        },
        {
            "id": "route-anomaly",
            "name": "External route anomaly",
            "description": "Observed edge route points to a discard next hop",
            "source_device": "edge-01",
            "destination_device": "orders-api",
        },
        {
            "id": "degraded-link",
            "name": "External degraded link",
            "description": "Observed latency and packet loss exceed thresholds",
            "source_device": "edge-01",
            "destination_device": "orders-api",
        },
        {
            "id": "stale-link",
            "name": "Stale degraded telemetry",
            "description": "A degraded measurement older than the freshness threshold",
            "source_device": "edge-01",
            "destination_device": "orders-api",
        },
    ]


@router.get("/integrations")
def integrations(service: Service) -> list[dict[str, object]]:
    return service.integrations()


@router.get("/sources/ripe-atlas/measurements/{measurement_id}")
def ripe_measurement(measurement_id: str, service: Service) -> dict[str, object]:
    try:
        return service.ripe_measurement_metadata(measurement_id)
    except (RuntimeError, TimeoutError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/inventory", response_model=Inventory)
def inventory(service: Service, source_id: str | None = None) -> Inventory:
    try:
        return service.inventory(source_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/capabilities")
def capabilities() -> dict[str, object]:
    settings = get_settings()
    return {
        "deterministic_planner": True,
        "ai_planner": settings.agent_provider != "deterministic" and bool(settings.agent_api_key),
        "agent_provider": settings.agent_provider
        if settings.agent_provider != "deterministic"
        else None,
        "max_investigation_steps": settings.max_investigation_steps,
    }


def _evaluation_results() -> dict[str, object]:
    path = Path(get_settings().evaluation_results_path)
    if not path.exists():
        from relay.eval import evaluate

        return evaluate()
    return cast(dict[str, object], json.loads(path.read_text()))


@router.get("/evaluations/latest")
def latest_evaluation() -> dict[str, object]:
    return _evaluation_results()


@router.get("/dashboard/summary")
def dashboard_summary(service: Service) -> dict[str, object]:
    incidents = service.list()
    runs = [run for item in incidents for run in item.investigation_runs]
    calls = [call for item in incidents for call in item.tool_calls]
    evaluation = _evaluation_results()
    summary = evaluation["summary"]
    assert isinstance(summary, dict)
    scenarios = evaluation["scenarios"]
    assert isinstance(scenarios, list)
    return {
        "open_incidents": sum(item.status.value != "RESOLVED" for item in incidents),
        "awaiting_approval": sum(item.status.value == "AWAITING_APPROVAL" for item in incidents),
        "resolved_incidents": sum(item.status.value == "RESOLVED" for item in incidents),
        "mean_investigation_steps": sum(run.steps_used for run in runs) / len(runs) if runs else 0,
        "average_tool_calls": len(calls) / len(runs) if runs else 0,
        "root_cause_accuracy": summary["root_cause_accuracy"],
        "resolution_success_rate": summary["resolution_success_rate"],
        "safety_violations": sum(int(row["safety_violations"]) for row in scenarios),
        "recent_incidents": incidents[:6],
    }


@router.get("/agent-runs")
def agent_runs(service: Service) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for incident in service.list():
        for run in incident.investigation_runs:
            rows.append(
                {
                    **run.model_dump(mode="json"),
                    "incident_id": str(incident.id),
                    "incident_title": incident.title,
                    "scenario": incident.scenario,
                    "operating_mode": incident.operating_mode.value,
                    "data_sources": incident.data_source_ids,
                    "planner": run.provider,
                    "latest_event": next(
                        (
                            event.model_dump(mode="json")
                            for event in reversed(incident.events)
                            if event.run_id == run.id
                        ),
                        None,
                    ),
                    "events": [
                        event.model_dump(mode="json")
                        for event in incident.events
                        if event.run_id == run.id
                    ],
                    "root_cause": next(
                        (h.statement for h in incident.hypotheses if h.status.value == "CONFIRMED"),
                        None,
                    ),
                    "remediation": incident.remediation_history[-1].description
                    if incident.remediation_history
                    else None,
                    "resolved": incident.status.value == "RESOLVED",
                }
            )
    return sorted(rows, key=lambda row: str(row["requested_at"]), reverse=True)


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


@router.post(
    "/incidents/{incident_id}/agent/start", response_model=InvestigationRun, status_code=202
)
def start_agent(
    incident_id: UUID,
    payload: AgentRunRequest,
    background_tasks: BackgroundTasks,
    service: Service,
) -> InvestigationRun:
    incident = _get(service, incident_id)
    if payload.planner == "ai" and not capabilities()["ai_planner"]:
        raise HTTPException(status_code=409, detail="AI Agent mode is not configured")
    if incident.status.value not in {"OPEN", "INVESTIGATING", "BLOCKED", "FAILED"}:
        raise HTTPException(
            status_code=409, detail=f"cannot investigate incident in {incident.status}"
        )
    run = service.queue_agent_run(incident_id, payload.planner)
    background_tasks.add_task(service.execute_queued_run, incident_id, run.id)
    return run


@router.get("/incidents/{incident_id}/runs/{run_id}/events")
async def run_events(
    incident_id: UUID,
    run_id: UUID,
    service: Service,
    after: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    try:
        cursor = max(after, int(last_event_id or 0))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Last-Event-ID must be a sequence") from exc
    incident = _get(service, incident_id)
    if not any(run.id == run_id for run in incident.investigation_runs):
        raise HTTPException(status_code=404, detail="run not found for incident")

    async def stream() -> AsyncIterator[str]:
        sequence = cursor
        while True:
            current = service.get(incident_id)
            pending = [
                event
                for event in current.events
                if event.run_id == run_id and event.sequence > sequence
            ]
            for event in pending:
                sequence = event.sequence
                data = event.model_dump_json()
                yield f"id: {sequence}\ndata: {data}\n\n"
            run = next(item for item in current.investigation_runs if item.id == run_id)
            if run.status.value in {
                "AWAITING_APPROVAL",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "BLOCKED",
            }:
                break
            yield ": keep-alive\n\n"
            await asyncio.sleep(0.15)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/incidents/{incident_id}/runs/{run_id}/cancel", response_model=InvestigationRun)
def cancel_run(incident_id: UUID, run_id: UUID, service: Service) -> InvestigationRun:
    try:
        return service.cancel_run(incident_id, run_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@router.post(
    "/incidents/{incident_id}/remediations/{remediation_id}/reject", response_model=Incident
)
def reject_specific_remediation(
    incident_id: UUID,
    remediation_id: UUID,
    payload: RemediationRejection,
    service: Service,
) -> Incident:
    incident = _get(service, incident_id)
    if incident.proposed_remediation is None or incident.proposed_remediation.id != remediation_id:
        raise HTTPException(status_code=409, detail="incident has no matching remediation")
    try:
        return service.reject_remediation(incident_id, payload.rejected_by, payload.reason)
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


@router.post("/incidents/{incident_id}/comments", response_model=Incident)
def add_comment(incident_id: UUID, payload: CommentCreate, service: Service) -> Incident:
    try:
        return service.add_comment(incident_id, **payload.model_dump())
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/incidents/{incident_id}/remediations", response_model=list[ProposedRemediation])
def get_remediations(incident_id: UUID, service: Service) -> list[ProposedRemediation]:
    return _get(service, incident_id).remediation_history


@router.get("/incidents/{incident_id}/verification", response_model=VerificationResult | None)
def get_verification(incident_id: UUID, service: Service) -> VerificationResult | None:
    return _get(service, incident_id).verification_result


@router.get("/network/topology", response_model=NetworkTopology)
def topology(simulator: Simulator) -> NetworkTopology:
    return simulator.topology()


@router.get("/network/topology/incident/{incident_id}", response_model=NetworkTopology)
def incident_topology(incident_id: UUID, service: Service) -> NetworkTopology:
    try:
        return service.topology_for_incident(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _get(service: IncidentService, incident_id: UUID) -> Incident:
    try:
        return service.get(incident_id)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
