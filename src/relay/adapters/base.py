from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import Any

from relay.domain.models import (
    AdapterCapability,
    AdapterObservation,
    DataSource,
    DataSourceClassification,
    DataSourceStatus,
    FreshnessPolicy,
    Inventory,
    NetworkTopology,
)


class DiagnosticOperation(StrEnum):
    TOPOLOGY = "topology"
    PING = "ping"
    TRACEROUTE = "traceroute"
    INTERFACE_STATUS = "interface_status"
    ROUTE_TABLE = "route_table"
    DEVICE_LOGS = "device_logs"
    DEVICE_CONFIG = "device_config"
    RESOLVE_DNS = "resolve_dns"
    TEST_TCP = "test_tcp"
    ACL_RULES = "acl_rules"
    LINK_METRICS = "link_metrics"
    PACKET_LOSS = "packet_loss"
    LATENCY = "latency"
    PATH_TRACE = "path_trace"
    PATH_COMPARISON = "path_comparison"
    PROBE_METADATA = "probe_metadata"
    COMPARE_CONFIG = "compare_config"
    RECENT_CHANGES = "recent_changes"


OPERATION_CAPABILITY: dict[DiagnosticOperation, AdapterCapability] = {
    DiagnosticOperation.TOPOLOGY: AdapterCapability.TOPOLOGY,
    DiagnosticOperation.PING: AdapterCapability.REACHABILITY,
    DiagnosticOperation.TRACEROUTE: AdapterCapability.PATH_TRACE,
    DiagnosticOperation.INTERFACE_STATUS: AdapterCapability.INTERFACE_STATE,
    DiagnosticOperation.ROUTE_TABLE: AdapterCapability.ROUTES,
    DiagnosticOperation.DEVICE_LOGS: AdapterCapability.RECENT_CHANGES,
    DiagnosticOperation.DEVICE_CONFIG: AdapterCapability.CONFIGURATION,
    DiagnosticOperation.RESOLVE_DNS: AdapterCapability.DNS,
    DiagnosticOperation.TEST_TCP: AdapterCapability.SERVICE_CONNECTIVITY,
    DiagnosticOperation.ACL_RULES: AdapterCapability.POLICY,
    DiagnosticOperation.LINK_METRICS: AdapterCapability.LINK_METRICS,
    DiagnosticOperation.PACKET_LOSS: AdapterCapability.PACKET_LOSS,
    DiagnosticOperation.LATENCY: AdapterCapability.LATENCY,
    DiagnosticOperation.PATH_TRACE: AdapterCapability.PATH_TRACE,
    DiagnosticOperation.PATH_COMPARISON: AdapterCapability.PATH_COMPARISON,
    DiagnosticOperation.PROBE_METADATA: AdapterCapability.PROBE_METADATA,
    DiagnosticOperation.COMPARE_CONFIG: AdapterCapability.CONFIGURATION,
    DiagnosticOperation.RECENT_CHANGES: AdapterCapability.RECENT_CHANGES,
}


class NetworkAdapter(ABC):
    """Bounded network data source. It intentionally has no command execution primitive."""

    adapter_id: str
    display_name: str
    source_type: str
    query_style: str = "resources"
    read_only: bool
    capabilities: frozenset[AdapterCapability]
    classification: DataSourceClassification = DataSourceClassification.DEMO
    freshness_seconds: int = 60
    last_successful_observation: datetime | None = None

    @abstractmethod
    def collect(
        self, operation: DiagnosticOperation, arguments: dict[str, Any]
    ) -> AdapterObservation:
        raise NotImplementedError

    @abstractmethod
    def inventory(self) -> Inventory:
        raise NotImplementedError

    @abstractmethod
    def topology(self) -> NetworkTopology:
        raise NotImplementedError

    def supports(self, operation: DiagnosticOperation) -> bool:
        return OPERATION_CAPABILITY[operation] in self.capabilities

    def data_source(self) -> DataSource:
        return DataSource(
            id=self.adapter_id,
            adapter_type=self.source_type,
            name=self.display_name,
            classification=self.classification,
            read_only=self.read_only,
            capabilities=sorted(self.capabilities, key=lambda item: item.value),
            status=(
                DataSourceStatus.AVAILABLE
                if self.classification is DataSourceClassification.LAB
                or self.last_successful_observation is not None
                else DataSourceStatus.UNKNOWN
            ),
            last_successful_query=self.last_successful_observation,
            freshness_policy=FreshnessPolicy(
                max_age_seconds=self.freshness_seconds,
                description=f"observations older than {self.freshness_seconds}s are stale",
            ),
        )


class CompositeNetworkAdapter(NetworkAdapter):
    """Small ordered federation: route each diagnostic to the first capable source."""

    source_type = "composite"
    read_only = True

    def __init__(self, adapter_id: str, adapters: list[NetworkAdapter]) -> None:
        if not adapters:
            raise ValueError("a composite adapter requires at least one source")
        self.adapter_id = adapter_id
        self.display_name = " + ".join(item.display_name for item in adapters)
        self.adapters = adapters
        self.capabilities = frozenset(
            capability for item in adapters for capability in item.capabilities
        )
        self.read_only = all(item.read_only for item in adapters)

    def collect(
        self, operation: DiagnosticOperation, arguments: dict[str, Any]
    ) -> AdapterObservation:
        for adapter in self.adapters:
            if adapter.supports(operation):
                return adapter.collect(operation, arguments)
        return self.adapters[0].collect(operation, arguments)

    def inventory(self) -> Inventory:
        inventories = [item.inventory() for item in self.adapters]
        return Inventory(
            devices=[x for value in inventories for x in value.devices],
            interfaces=[x for value in inventories for x in value.interfaces],
            services=[x for value in inventories for x in value.services],
            links=[x for value in inventories for x in value.links],
        )

    def topology(self) -> NetworkTopology:
        for adapter in self.adapters:
            if AdapterCapability.TOPOLOGY in adapter.capabilities:
                return adapter.topology()
        return NetworkTopology(devices=[], links=[])
