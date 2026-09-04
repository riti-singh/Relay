from fastapi.testclient import TestClient


def test_agent_api_surfaces_and_exact_approval(client: TestClient) -> None:
    created = client.post(
        "/incidents",
        json={
            "title": "Agent case",
            "description": "branch outage",
            "source_device": "branch-03",
            "destination_device": "payments-api",
        },
    ).json()
    incident_id = created["id"]
    investigated = client.post(f"/incidents/{incident_id}/agent/run")
    assert investigated.status_code == 200
    body = investigated.json()
    remediation_id = body["proposed_remediation"]["id"]
    assert body["status"] == "AWAITING_APPROVAL"
    assert client.get(f"/incidents/{incident_id}/actions").json()
    assert client.get(f"/incidents/{incident_id}/hypotheses").json()
    assert client.get(f"/incidents/{incident_id}/remediations").json()
    mismatch = client.post(
        f"/incidents/{incident_id}/remediations/{remediation_id}/approve",
        json={"remediation_id": "00000000-0000-0000-0000-000000000000", "approved_by": "alice"},
    )
    assert mismatch.status_code == 422
    approved = client.post(
        f"/incidents/{incident_id}/remediations/{remediation_id}/approve",
        json={"remediation_id": remediation_id, "approved_by": "alice"},
    )
    assert approved.status_code == 200 and approved.json()["status"] == "RESOLVED"
    assert client.get(f"/incidents/{incident_id}/verification").json()["successful"] is True
