from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from relay.agent.planner import DeterministicPlanner
from relay.api.dependencies import get_incident_service, get_simulator
from relay.main import create_app
from relay.network.simulator import NetworkSimulator
from relay.repositories.incidents import SQLiteIncidentRepository
from relay.services.incidents import IncidentService
from relay.tools.network_tools import build_registry


@pytest.fixture
def simulator() -> NetworkSimulator:
    return NetworkSimulator()


@pytest.fixture
def service(tmp_path, simulator: NetworkSimulator) -> IncidentService:
    return IncidentService(
        SQLiteIncidentRepository(str(tmp_path / "relay.db")),
        build_registry(simulator),
        DeterministicPlanner(),
    )


@pytest.fixture
def client(service: IncidentService, simulator: NetworkSimulator) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_incident_service] = lambda: service
    app.dependency_overrides[get_simulator] = lambda: simulator
    with TestClient(app) as test_client:
        yield test_client
