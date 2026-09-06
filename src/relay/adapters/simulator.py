from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from relay.adapters.base import DiagnosticOperation, NetworkAdapter
from relay.domain.models import (
    AdapterCapability,
    AdapterObservation,
    Device,
    Freshness,
    Inventory,
    InventoryInterface,
    InventoryLink,
    NetworkTopology,
    ObservationProvenance,
    ObservationStatus,
    ResourceStatus,
    ServiceResource,
)
from relay.network.simulator import NetworkSimulator


class SimulatorNetworkAdapter(NetworkAdapter):
    adapter_id = "lab-simulator"
    display_name = "Deterministic network simulator"
    source_type = "simulator"
    read_only = False
    capabilities = frozenset(AdapterCapability)

    def __init__(self, simulator: NetworkSimulator) -> None:
        self.simulator = simulator

    def collect(
        self, operation: DiagnosticOperation, arguments: dict[str, Any]
    ) -> AdapterObservation:
        handlers: dict[DiagnosticOperation, Callable[[], dict[str, Any]]] = {
            DiagnosticOperation.TOPOLOGY: lambda: self.simulator.topology().model_dump(mode="json"),
            DiagnosticOperation.PING: lambda: self._ping(arguments),
            DiagnosticOperation.TRACEROUTE: lambda: self.simulator.trace(**arguments),
            DiagnosticOperation.INTERFACE_STATUS: lambda: self.simulator.interface(
                arguments["device_id"], arguments["interface_name"]
            ).model_dump(mode="json"),
            DiagnosticOperation.ROUTE_TABLE: lambda: {
                "routes": self.simulator.device(arguments["device_id"]).routes
            },
            DiagnosticOperation.DEVICE_LOGS: lambda: {
                "logs": self.simulator.device(arguments["device_id"]).logs
            },
            DiagnosticOperation.DEVICE_CONFIG: lambda: {
                "config": self.simulator.device(arguments["device_id"]).config
            },
            DiagnosticOperation.RESOLVE_DNS: lambda: self._dns(arguments["hostname"]),
            DiagnosticOperation.TEST_TCP: lambda: self.simulator.tcp_test(**arguments),
            DiagnosticOperation.ACL_RULES: lambda: {
                "rules": self.simulator.device(arguments["device_id"]).acl_rules
            },
            DiagnosticOperation.LINK_METRICS: lambda: self.simulator._find_link(
                arguments["device_a"], arguments["device_b"]
            ).model_dump(mode="json"),
            DiagnosticOperation.PACKET_LOSS: lambda: {
                "packet_loss_percent": self.simulator.packet_loss(**arguments)
            },
            DiagnosticOperation.COMPARE_CONFIG: lambda: self._config(arguments["device_id"]),
            DiagnosticOperation.RECENT_CHANGES: lambda: self._changes(arguments["device_id"]),
        }
        now = datetime.now(UTC)
        return AdapterObservation(
            status=ObservationStatus.SUCCESS,
            data=handlers[operation](),
            provenance=ObservationProvenance(
                source_type=self.source_type,
                adapter=self.adapter_id,
                resource_id=self._resource(arguments),
                observed_at=now,
                collected_at=now,
                freshness=Freshness.FRESH,
                query_identity=operation.value,
            ),
        )

    def _ping(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self.simulator.path(arguments["source"], arguments["destination"])
        return {"reachable": path is not None, "latency_ms": path[1] if path else None}

    def _dns(self, hostname: str) -> dict[str, Any]:
        return {
            "hostname": hostname,
            "target": self.simulator.dns_records.get(hostname),
            "resolved": hostname in self.simulator.dns_records,
        }

    def _config(self, device_id: str) -> dict[str, Any]:
        device = self.simulator.device(device_id)
        return {
            "matches": device.config == device.baseline_config,
            "current": device.config,
            "baseline": device.baseline_config,
        }

    def _changes(self, device_id: str) -> dict[str, Any]:
        self.simulator.device(device_id)
        return {"changes": [c for c in self.simulator.recent_changes if c["device"] == device_id]}

    @staticmethod
    def _resource(arguments: dict[str, Any]) -> str | None:
        if "device_id" in arguments:
            suffix = f"/{arguments['interface_name']}" if "interface_name" in arguments else ""
            return f"{arguments['device_id']}{suffix}"
        if "device_a" in arguments:
            return f"{arguments['device_a']}--{arguments['device_b']}"
        return arguments.get("destination") or arguments.get("hostname")

    def inventory(self) -> Inventory:
        topology = self.simulator.topology()
        now = datetime.now(UTC)
        devices: list[Device] = []
        interfaces: list[InventoryInterface] = []
        services: list[ServiceResource] = []
        for item in topology.devices:
            status = (
                ResourceStatus.UP
                if all(x.operational_up for x in item.interfaces)
                else ResourceStatus.DOWN
            )
            if item.kind == "service":
                services.append(
                    ServiceResource(
                        id=item.id,
                        display_name=item.name,
                        telemetry_source=self.adapter_id,
                        status=status,
                        last_observed_at=now,
                    )
                )
            else:
                devices.append(
                    Device(
                        id=item.id,
                        hostname=item.id,
                        display_name=item.name,
                        type=item.kind,
                        site=str(item.config.get("site")) if item.config.get("site") else None,
                        telemetry_source=self.adapter_id,
                        status=status,
                        last_observed_at=now,
                    )
                )
            interfaces.extend(
                InventoryInterface(
                    id=f"{item.id}/{x.name}",
                    device_id=item.id,
                    name=x.name,
                    management_address=x.ip_address,
                    telemetry_source=self.adapter_id,
                    status=ResourceStatus.UP if x.operational_up else ResourceStatus.DOWN,
                    last_observed_at=now,
                )
                for x in item.interfaces
            )
        links = [
            InventoryLink(
                id=f"{x.device_a}--{x.device_b}",
                device_a=x.device_a,
                device_b=x.device_b,
                interface_a=x.interface_a,
                interface_b=x.interface_b,
                telemetry_source=self.adapter_id,
                status=ResourceStatus.DEGRADED if x.packet_loss_percent > 5 else ResourceStatus.UP,
                last_observed_at=now,
            )
            for x in topology.links
        ]
        return Inventory(devices=devices, interfaces=interfaces, services=services, links=links)

    def topology(self) -> NetworkTopology:
        return self.simulator.topology()
