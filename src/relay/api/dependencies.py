from functools import lru_cache

from relay.agent.planner import DeterministicPlanner
from relay.config import get_settings
from relay.network.simulator import NetworkSimulator
from relay.repositories.incidents import SQLiteIncidentRepository
from relay.services.incidents import IncidentService
from relay.tools.network_tools import build_registry


@lru_cache
def get_simulator() -> NetworkSimulator:
    return NetworkSimulator()


@lru_cache
def get_incident_service() -> IncidentService:
    repository = SQLiteIncidentRepository(get_settings().database_path)
    simulator = get_simulator()
    return IncidentService(repository, build_registry(simulator), DeterministicPlanner())
