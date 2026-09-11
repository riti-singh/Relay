from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from relay.domain.models import AdapterCapability, AdapterObservation, Inventory, NetworkTopology


class DiagnosticOperation(StrEnum):
    TOPOLOGY = "topology"
    PING = "ping"
    TRACEROUTE = "traceroute"
    INTERFACE_STATUS = "interface_status"
    ROUTE_TABLE = "route_table"
    PREFIX_VISIBILITY = "prefix_visibility"
    DEVICE_LOGS = "device_logs"
    DEVICE_CONFIG = "device_config"
    RESOLVE_DNS = "resolve_dns"
    TEST_TCP = "test_tcp"
    ACL_RULES = "acl_rules"
    LINK_METRICS = "link_metrics"
    PACKET_LOSS = "packet_loss"
    COMPARE_CONFIG = "compare_config"
    RECENT_CHANGES = "recent_changes"


OPERATION_CAPABILITY: dict[DiagnosticOperation, AdapterCapability] = {
    DiagnosticOperation.TOPOLOGY: AdapterCapability.TOPOLOGY,
    DiagnosticOperation.PING: AdapterCapability.REACHABILITY,
    DiagnosticOperation.TRACEROUTE: AdapterCapability.REACHABILITY,
    DiagnosticOperation.INTERFACE_STATUS: AdapterCapability.INTERFACE_STATE,
    DiagnosticOperation.ROUTE_TABLE: AdapterCapability.ROUTES,
    DiagnosticOperation.PREFIX_VISIBILITY: AdapterCapability.BGP_VISIBILITY,
    DiagnosticOperation.DEVICE_LOGS: AdapterCapability.RECENT_CHANGES,
    DiagnosticOperation.DEVICE_CONFIG: AdapterCapability.CONFIGURATION,
    DiagnosticOperation.RESOLVE_DNS: AdapterCapability.DNS,
    DiagnosticOperation.TEST_TCP: AdapterCapability.SERVICE_CONNECTIVITY,
    DiagnosticOperation.ACL_RULES: AdapterCapability.POLICY,
    DiagnosticOperation.LINK_METRICS: AdapterCapability.LINK_METRICS,
    DiagnosticOperation.PACKET_LOSS: AdapterCapability.PACKET_LOSS,
    DiagnosticOperation.COMPARE_CONFIG: AdapterCapability.CONFIGURATION,
    DiagnosticOperation.RECENT_CHANGES: AdapterCapability.RECENT_CHANGES,
}


class NetworkAdapter(ABC):
    """Bounded network data source. It intentionally has no command execution primitive."""

    adapter_id: str
    display_name: str
    source_type: str
    read_only: bool
    capabilities: frozenset[AdapterCapability]

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
