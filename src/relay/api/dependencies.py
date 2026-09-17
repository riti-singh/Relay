from functools import lru_cache

from relay.adapters.http_telemetry import HTTPTelemetryAdapter
from relay.adapters.ripe_atlas import RIPEAtlasAdapter
from relay.adapters.ripestat import RIPEstatAdapter
from relay.agent.planner import AgentModel, DeterministicPlanner, OpenAICompatibleAgentModel
from relay.agent.runtime import AgentRuntime
from relay.config import get_settings
from relay.domain.models import AdapterCapability
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
    external_capabilities = frozenset(
        {
            AdapterCapability.TOPOLOGY,
            AdapterCapability.INVENTORY,
            AdapterCapability.REACHABILITY,
            AdapterCapability.INTERFACE_STATE,
            AdapterCapability.ROUTES,
            AdapterCapability.LINK_METRICS,
            AdapterCapability.PACKET_LOSS,
        }
    )
    service = IncidentService(
        repository,
        registry,
        deterministic,
        runtime,
        adapter_factories={
            "fixture-http": lambda incident: HTTPTelemetryAdapter(
                "fixture-http",
                "Local structured HTTP telemetry",
                settings.fixture_telemetry_url,
                incident.scenario,
                external_capabilities,
                settings.telemetry_timeout_seconds,
                settings.telemetry_freshness_seconds,
            ),
            "ripestat": lambda incident: RIPEstatAdapter(
                base_url=settings.ripestat_base_url,
                timeout_seconds=settings.telemetry_timeout_seconds,
                freshness_seconds=settings.ripestat_freshness_seconds,
            ),
            "ripe-atlas": lambda incident: RIPEAtlasAdapter(
                "ripe-atlas",
                "RIPE Atlas public measurements",
                settings.ripe_atlas_base_url,
                {
                    kind: measurement_id
                    for kind, measurement_id in (
                        ("ping", settings.ripe_atlas_ping_measurement_id),
                        ("traceroute", settings.ripe_atlas_traceroute_measurement_id),
                        ("dns", settings.ripe_atlas_dns_measurement_id),
                    )
                    if measurement_id is not None
                },
                settings.ripe_atlas_api_key,
                settings.ripe_atlas_timeout_seconds,
                settings.ripe_atlas_freshness_seconds,
            ),
        },
    )
    if settings.seed_demo_data and not service.list():
        _seed_demo_data(service)
    return service


def _seed_demo_data(service: IncidentService) -> None:
    """Seed simulator-backed examples; every value comes from a real Relay run."""
    from relay.network.simulator import SCENARIOS

    resolved_definition = SCENARIOS["config-drift"]
    resolved = service.create(
        "Forwarding drift detected",
        resolved_definition.description,
        resolved_definition.source,
        resolved_definition.destination,
        resolved_definition.name,
    )
    resolved = service.agent_run(resolved.id)
    if resolved.proposed_remediation:
        service.approve_remediation(
            resolved.id, resolved.proposed_remediation.id, "relay-demo-seed"
        )

    pending_definition = SCENARIOS["dns-failure"]
    pending = service.create(
        "Payments DNS resolution failure",
        pending_definition.description,
        pending_definition.source,
        pending_definition.destination,
        pending_definition.name,
    )
    service.agent_run(pending.id)

    open_definition = SCENARIOS["acl-block"]
    service.create(
        "Payments application traffic blocked",
        open_definition.description,
        open_definition.source,
        open_definition.destination,
        open_definition.name,
    )
