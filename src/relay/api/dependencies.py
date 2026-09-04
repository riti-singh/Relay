from functools import lru_cache

from relay.agent.planner import AgentModel, DeterministicPlanner, OpenAICompatibleAgentModel
from relay.agent.runtime import AgentRuntime
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
    settings = get_settings()
    repository = SQLiteIncidentRepository(settings.database_path)
    simulator = get_simulator()
    registry = build_registry(simulator, settings.max_tool_retries)
    deterministic = DeterministicPlanner()
    model: AgentModel = deterministic
    if settings.agent_provider != "deterministic" and settings.agent_api_key:
        model = OpenAICompatibleAgentModel(
            settings.agent_api_key,
            settings.agent_model,
            settings.agent_base_url,
            settings.agent_timeout_seconds,
        )
    runtime = AgentRuntime(
        registry,
        model,
        settings.max_investigation_steps,
        settings.max_repeated_tool_calls,
    )
    return IncidentService(repository, registry, deterministic, runtime)
