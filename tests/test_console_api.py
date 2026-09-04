from fastapi.testclient import TestClient


def test_console_surfaces_and_rejection(client: TestClient) -> None:
    assert len(client.get("/scenarios").json()) == 6
    assert client.get("/capabilities").json()["deterministic_planner"] is True
    assert client.get("/evaluations/latest").json()["summary"]["root_cause_accuracy"] == 1
    created = client.post(
        "/incidents",
        json={
            "title": "Console incident",
            "description": "Branch cannot reach payments",
            "source_device": "branch-03",
            "destination_device": "payments-api",
            "scenario": "interface-disabled",
        },
    ).json()
    incident_id = created["id"]
    assert client.get(f"/network/topology/incident/{incident_id}").status_code == 200
    investigated = client.post(f"/incidents/{incident_id}/agent/run").json()
    remediation_id = investigated["proposed_remediation"]["id"]
    rejected = client.post(
        f"/incidents/{incident_id}/remediations/{remediation_id}/reject",
        json={"rejected_by": "operator", "reason": "collect more evidence"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["approval_state"] == "REJECTED"
    assert rejected.json()["status"] == "INVESTIGATING"


def test_dashboard_and_agent_runs_use_persisted_incidents(client: TestClient) -> None:
    assert client.get("/dashboard/summary").status_code == 200
    assert client.get("/agent-runs").json() == []
