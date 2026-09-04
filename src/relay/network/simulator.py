from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from relay.domain.models import Interface, NetworkDevice, NetworkLink, NetworkTopology


class NetworkError(ValueError):
    pass


@dataclass(frozen=True)
class ScenarioDefinition:
    name: str
    description: str
    source: str
    destination: str
    expected_root_cause: str
    expected_remediation_tool: str


SCENARIOS = {
    "interface-disabled": ScenarioDefinition(
        "interface-disabled",
        "Branch 03 cannot reach payments",
        "branch-03",
        "payments-api",
        "core-router-02/eth1 is administratively disabled",
        "set_interface_admin_state",
    ),
    "incorrect-route": ScenarioDefinition(
        "incorrect-route",
        "Branch 03 uses an incorrect static route",
        "branch-03",
        "payments-api",
        "branch-03 route to payments-api has wrong next hop core-router-01",
        "set_static_route",
    ),
    "acl-block": ScenarioDefinition(
        "acl-block",
        "TCP 443 is denied while IP reachability works",
        "branch-03",
        "payments-api",
        "core-router-02 ACL denies TCP port 443",
        "set_acl_rule_enabled",
    ),
    "dns-failure": ScenarioDefinition(
        "dns-failure",
        "payments.internal does not resolve",
        "branch-03",
        "payments-api",
        "payments.internal has an incorrect DNS record",
        "set_dns_record",
    ),
    "degraded-link": ScenarioDefinition(
        "degraded-link",
        "Branch link has excessive latency and loss",
        "branch-03",
        "payments-api",
        "branch-03 uplink is degraded",
        "repair_link",
    ),
    "config-drift": ScenarioDefinition(
        "config-drift",
        "Configuration drift disables forwarding",
        "branch-03",
        "payments-api",
        "core-router-02 forwarding configuration drift",
        "restore_config_baseline",
    ),
}


class NetworkSimulator:
    """Deterministic scenario simulator. Each instance owns one scenario state."""

    def __init__(self, scenario: str = "interface-disabled") -> None:
        if scenario not in SCENARIOS:
            raise NetworkError(f"unknown scenario: {scenario}")
        self.scenario = scenario
        self._devices, self._links = self._seed()
        self.dns_records: dict[str, str] = {"payments.internal": "payments-api"}
        self.recent_changes: list[dict[str, str]] = []
        self._injected_failures: dict[str, int] = {}
        self._apply_scenario(scenario)

    @staticmethod
    def scenario_definitions() -> list[ScenarioDefinition]:
        return list(SCENARIOS.values())

    @staticmethod
    def _seed() -> tuple[dict[str, NetworkDevice], list[NetworkLink]]:
        devices = [
            NetworkDevice(
                id="branch-01",
                name="Branch 01",
                kind="branch-router",
                interfaces=[Interface(name="wan0", ip_address="10.1.0.1")],
                routes={"payments-api": "core-router-01"},
                config={"site": "branch-01"},
                baseline_config={"site": "branch-01"},
            ),
            NetworkDevice(
                id="branch-03",
                name="Branch 03",
                kind="branch-router",
                interfaces=[Interface(name="wan0", ip_address="10.3.0.1")],
                routes={"payments-api": "core-router-02"},
                config={"site": "branch-03"},
                baseline_config={"site": "branch-03"},
            ),
            NetworkDevice(
                id="core-router-01",
                name="Core Router 01",
                kind="core-router",
                interfaces=[Interface(name="eth1"), Interface(name="eth2")],
                routes={"payments-api": "core-router-02"},
                config={"routing": "static"},
                baseline_config={"routing": "static"},
            ),
            NetworkDevice(
                id="core-router-02",
                name="Core Router 02",
                kind="core-router",
                interfaces=[Interface(name="eth1"), Interface(name="eth2"), Interface(name="eth3")],
                routes={"payments-api": "payments-api"},
                config={"interfaces": {"eth1": {"shutdown": False}}, "ip_forwarding": True},
                baseline_config={
                    "interfaces": {"eth1": {"shutdown": False}},
                    "ip_forwarding": True,
                },
            ),
            NetworkDevice(
                id="payments-api",
                name="Payments API",
                kind="service",
                interfaces=[Interface(name="eth0", ip_address="172.16.0.10")],
                config={"service": "payments"},
                baseline_config={"service": "payments"},
            ),
        ]
        links = [
            NetworkLink(
                device_a="branch-01",
                interface_a="wan0",
                device_b="core-router-01",
                interface_b="eth1",
                latency_ms=5,
            ),
            NetworkLink(
                device_a="core-router-01",
                interface_a="eth2",
                device_b="core-router-02",
                interface_b="eth2",
                latency_ms=2,
            ),
            NetworkLink(
                device_a="branch-03",
                interface_a="wan0",
                device_b="core-router-02",
                interface_b="eth1",
                latency_ms=5,
            ),
            NetworkLink(
                device_a="core-router-02",
                interface_a="eth3",
                device_b="payments-api",
                interface_b="eth0",
                latency_ms=3,
            ),
        ]
        return {device.id: device for device in devices}, links

    def _apply_scenario(self, scenario: str) -> None:
        if scenario == "interface-disabled":
            interface = self.interface("core-router-02", "eth1")
            interface.admin_up = interface.operational_up = False
            self.device("core-router-02").config["interfaces"] = {"eth1": {"shutdown": True}}
            self.device("core-router-02").logs.append("interface eth1 administratively disabled")
        elif scenario == "incorrect-route":
            self.device("branch-03").routes["payments-api"] = "core-router-01"
            self.recent_changes.append(
                {"device": "branch-03", "change": "static route next hop changed"}
            )
        elif scenario == "acl-block":
            self.device("core-router-02").acl_rules.append(
                {
                    "id": "deny-payments",
                    "protocol": "tcp",
                    "port": 443,
                    "action": "deny",
                    "enabled": True,
                }
            )
        elif scenario == "dns-failure":
            self.dns_records["payments.internal"] = "192.0.2.99"
        elif scenario == "degraded-link":
            link = self._find_link("branch-03", "core-router-02")
            link.latency_ms = 250
            link.packet_loss_percent = 35
        elif scenario == "config-drift":
            self.device("core-router-02").config["ip_forwarding"] = False
            self.recent_changes.append(
                {"device": "core-router-02", "change": "ip_forwarding disabled"}
            )

    def inject_failure(self, tool_name: str, count: int = 1) -> None:
        self._injected_failures[tool_name] = count

    def consume_failure(self, tool_name: str) -> bool:
        remaining = self._injected_failures.get(tool_name, 0)
        if remaining <= 0:
            return False
        self._injected_failures[tool_name] = remaining - 1
        return True

    def topology(self) -> NetworkTopology:
        return NetworkTopology(
            devices=deepcopy(list(self._devices.values())), links=deepcopy(self._links)
        )

    def topology_summary(self) -> str:
        return (
            f"{len(self._devices)} devices, {len(self._links)} links; "
            "endpoints branch-03 and payments-api"
        )

    def device(self, device_id: str) -> NetworkDevice:
        try:
            return self._devices[device_id]
        except KeyError as exc:
            raise NetworkError(f"unknown device: {device_id}") from exc

    def interface(self, device_id: str, interface_name: str) -> Interface:
        for interface in self.device(device_id).interfaces:
            if interface.name == interface_name:
                return interface
        raise NetworkError(f"unknown interface: {device_id}/{interface_name}")

    def _find_link(self, left: str, right: str) -> NetworkLink:
        for link in self._links:
            if {link.device_a, link.device_b} == {left, right}:
                return link
        raise NetworkError(f"unknown link: {left}/{right}")

    def _active_neighbors(self, device_id: str) -> list[tuple[str, int]]:
        neighbors: list[tuple[str, int]] = []
        for link in self._links:
            if link.device_a == device_id:
                local, remote, remote_if = link.interface_a, link.device_b, link.interface_b
            elif link.device_b == device_id:
                local, remote, remote_if = link.interface_b, link.device_a, link.interface_a
            else:
                continue
            if (
                self.interface(device_id, local).admin_up
                and self.interface(device_id, local).operational_up
                and self.interface(remote, remote_if).admin_up
                and self.interface(remote, remote_if).operational_up
            ):
                neighbors.append((remote, link.latency_ms))
        return sorted(neighbors)

    def path(self, source: str, destination: str) -> tuple[list[str], int] | None:
        self.device(source)
        self.device(destination)
        if self.device("core-router-02").config.get("ip_forwarding") is False:
            return None
        if (
            source == "branch-03"
            and self.device(source).routes.get(destination) != "core-router-02"
        ):
            return None
        queue = deque([(source, [source], 0)])
        visited = {source}
        while queue:
            current, path, latency = queue.popleft()
            if current == destination:
                return path, latency
            for neighbor, cost in self._active_neighbors(current):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, [*path, neighbor], latency + cost))
        return None

    def trace(self, source: str, destination: str) -> dict[str, object]:
        complete = self.path(source, destination)
        if complete:
            return {"reached": True, "hops": complete[0], "latency_ms": complete[1]}
        self.device(source)
        self.device(destination)
        return {"reached": False, "hops": [source], "failure_after": source}

    def packet_loss(self, source: str, destination: str) -> float:
        path = self.path(source, destination)
        if path is None:
            return 100
        pairs = zip(path[0], path[0][1:], strict=False)
        return max((self._find_link(a, b).packet_loss_percent for a, b in pairs), default=0)

    def tcp_test(self, source: str, destination: str, port: int) -> dict[str, Any]:
        reachable = self.path(source, destination) is not None
        denied = any(
            rule.get("enabled") and rule.get("action") == "deny" and rule.get("port") == port
            for rule in self.device("core-router-02").acl_rules
        )
        return {
            "connected": reachable and not denied,
            "port": port,
            "network_reachable": reachable,
            "reason": "ACL_DENY" if denied else None,
        }

    def set_interface_admin_state(
        self, device_id: str, interface_name: str, admin_up: bool
    ) -> Interface:
        interface = self.interface(device_id, interface_name)
        interface.admin_up = interface.operational_up = admin_up
        self.device(device_id).config.setdefault("interfaces", {})[interface_name] = {
            "shutdown": not admin_up
        }
        self.device(device_id).logs.append(
            f"relay: interface {interface_name} admin state set to {'up' if admin_up else 'down'}"
        )
        return deepcopy(interface)

    def set_route(self, device_id: str, destination: str, next_hop: str) -> dict[str, str]:
        self.device(next_hop)
        self.device(device_id).routes[destination] = next_hop
        return {"destination": destination, "next_hop": next_hop}

    def set_acl_enabled(self, device_id: str, rule_id: str, enabled: bool) -> dict[str, Any]:
        for rule in self.device(device_id).acl_rules:
            if rule["id"] == rule_id:
                rule["enabled"] = enabled
                return deepcopy(rule)
        raise NetworkError(f"unknown ACL rule: {device_id}/{rule_id}")

    def set_dns_record(self, hostname: str, target: str) -> dict[str, str]:
        self.device(target)
        self.dns_records[hostname] = target
        return {"hostname": hostname, "target": target}

    def repair_link(self, device_a: str, device_b: str) -> dict[str, Any]:
        link = self._find_link(device_a, device_b)
        link.latency_ms = 5
        link.packet_loss_percent = 0
        return link.model_dump(mode="json")

    def restore_baseline(self, device_id: str) -> dict[str, Any]:
        device = self.device(device_id)
        device.config = deepcopy(device.baseline_config)
        return {"device_id": device_id, "config": deepcopy(device.config)}
