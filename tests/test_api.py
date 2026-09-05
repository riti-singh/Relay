from fastapi.testclient import TestClient

PAYLOAD = {
    "title": "Branch connectivity failure",
    "description": "Users at branch-03 cannot reach the payments API.",
    "source_device": "branch-03",
    "destination_device": "payments-api",
}


def test_api_complete_happy_path(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    topology = client.get("/network/topology")
    assert topology.status_code == 200
    assert len(topology.json()["devices"]) == 5

    created = client.post("/incidents", json=PAYLOAD)
    assert created.status_code == 201
    incident_id = created.json()["id"]
    assert created.json()["status"] == "OPEN"
    assert len(client.get("/incidents").json()) == 1

    investigated = client.post(f"/incidents/{incident_id}/investigate")
    assert investigated.status_code == 200
    body = investigated.json()
    assert body["status"] == "AWAITING_APPROVAL"
    assert body["approval_state"] == "PENDING"
    assert len(body["tool_calls"]) == 7
    assert client.get(f"/incidents/{incident_id}/evidence").json()

    resolved = client.post(f"/incidents/{incident_id}/approve-remediation")
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"
    assert resolved.json()["verification_result"]["successful"] is True
    assert client.get(f"/incidents/{incident_id}").json()["status"] == "RESOLVED"


def test_api_errors(client: TestClient) -> None:
    assert client.get("/incidents/not-a-uuid").status_code == 422
    assert client.get("/incidents/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.post("/incidents", json={}).status_code == 422
    invalid = {**PAYLOAD, "source_device": "unknown-branch"}
    response = client.post("/incidents", json=invalid)
    assert response.status_code == 422
    assert "unknown incident device" in response.json()["detail"]
    created = client.post("/incidents", json=PAYLOAD).json()
    assert client.post(f"/incidents/{created['id']}/approve-remediation").status_code == 409


def test_local_frontend_origins_can_reach_api(client: TestClient) -> None:
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        response = client.options(
            "/dashboard/summary",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
