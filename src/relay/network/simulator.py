from __future__ import annotations

from collections import deque
from copy import deepcopy

from relay.domain.models import Interface, NetworkDevice, NetworkLink, NetworkTopology


class NetworkError(ValueError):
    pass


class NetworkSimulator:
    """In-memory deterministic topology. It is re-seeded on process startup."""

    def __init__(self) -> None:
        self._devices, self._links = self._seed()

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
            ),
            NetworkDevice(
                id="branch-03",
                name="Branch 03",
                kind="branch-router",
                interfaces=[Interface(name="wan0", ip_address="10.3.0.1")],
                routes={"payments-api": "core-router-02"},
                config={"site": "branch-03"},
            ),
            NetworkDevice(
                id="core-router-01",
                name="Core Router 01",
                kind="core-router",
                interfaces=[Interface(name="eth1"), Interface(name="eth2")],
                routes={"payments-api": "core-router-02"},
                config={"routing": "static"},
            ),
            NetworkDevice(
                id="core-router-02",
                name="Core Router 02",
                kind="core-router",
                interfaces=[
                    Interface(name="eth1", admin_up=False, operational_up=False),
                    Interface(name="eth2"),
                    Interface(name="eth3"),
                ],
                routes={"payments-api": "payments-api"},
                logs=["2026-01-01T00:00:00Z interface eth1 administratively disabled"],
                config={"interfaces": {"eth1": {"shutdown": True}}, "routing": "static"},
            ),
            NetworkDevice(
                id="payments-api",
                name="Payments API",
                kind="service",
                interfaces=[Interface(name="eth0", ip_address="172.16.0.10")],
                config={"service": "payments"},
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

    def topology(self) -> NetworkTopology:
        return NetworkTopology(
            devices=deepcopy(list(self._devices.values())), links=deepcopy(self._links)
        )

    def device(self, device_id: str) -> NetworkDevice:
        try:
            return self._devices[device_id]
        except KeyError as exc:
            raise NetworkError(f"unknown device: {device_id}") from exc

    def interface(self, device_id: str, interface_name: str) -> Interface:
        device = self.device(device_id)
        for interface in device.interfaces:
            if interface.name == interface_name:
                return interface
        raise NetworkError(f"unknown interface: {device_id}/{interface_name}")

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
        visited = {source}
        queue = deque([(source, [source])])
        furthest = [source]
        while queue:
            current, path = queue.popleft()
            if len(path) > len(furthest):
                furthest = path
            for neighbor, _ in self._active_neighbors(current):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, [*path, neighbor]))
        return {"reached": False, "hops": furthest, "failure_after": furthest[-1]}

    def set_interface_admin_state(
        self, device_id: str, interface_name: str, admin_up: bool
    ) -> Interface:
        interface = self.interface(device_id, interface_name)
        interface.admin_up = admin_up
        interface.operational_up = admin_up
        device = self.device(device_id)
        device.logs.append(
            f"relay: interface {interface_name} admin state set to {'up' if admin_up else 'down'}"
        )
        if device.id == "core-router-02" and interface_name == "eth1":
            interfaces = device.config.setdefault("interfaces", {})
            assert isinstance(interfaces, dict)
            interfaces[interface_name] = {"shutdown": not admin_up}
        return deepcopy(interface)
