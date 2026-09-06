from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException

from relay.domain.models import (
    Device,
    Inventory,
    InventoryInterface,
    InventoryLink,
    NetworkDevice,
    NetworkLink,
    NetworkTopology,
    ResourceStatus,
    ServiceResource,
)

app = FastAPI(title="Relay Fixture Telemetry", version="1.0")

DATASETS = {"healthy", "interface-failure", "route-anomaly", "degraded-link", "stale-link"}


def _observed(dataset: str) -> datetime:
    age = timedelta(minutes=10) if dataset == "stale-link" else timedelta(seconds=5)
    return datetime.now(UTC) - age


def _topology(dataset: str) -> NetworkTopology:
    down = dataset == "interface-failure"
    loss = 28.0 if dataset in {"degraded-link", "stale-link"} else 0.0
    devices = [
        NetworkDevice(
            id="edge-01",
            name="Edge Router 01",
            kind="router",
            interfaces=[],
            routes={"orders-api": "core-01" if dataset != "route-anomaly" else "discard"},
        ),
        NetworkDevice(
            id="core-01",
            name="Core Router 01",
            kind="router",
            interfaces=[],
            routes={"orders-api": "orders-api"},
        ),
        NetworkDevice(id="orders-api", name="Orders API", kind="service", interfaces=[]),
    ]
    from relay.domain.models import Interface

    devices[0].interfaces = [
        Interface(name="wan0", admin_up=True, operational_up=not down, ip_address="10.20.0.1")
    ]
    devices[1].interfaces = [
        Interface(name="eth1", admin_up=True, operational_up=not down),
        Interface(name="eth2"),
    ]
    devices[2].interfaces = [Interface(name="eth0", ip_address="172.20.0.10")]
    return NetworkTopology(
        devices=devices,
        links=[
            NetworkLink(
                device_a="edge-01",
                interface_a="wan0",
                device_b="core-01",
                interface_b="eth1",
                latency_ms=180 if loss else 8,
                packet_loss_percent=loss,
            ),
            NetworkLink(
                device_a="core-01",
                interface_a="eth2",
                device_b="orders-api",
                interface_b="eth0",
                latency_ms=3,
            ),
        ],
    )


def _inventory(dataset: str) -> Inventory:
    now = _observed(dataset)
    topology = _topology(dataset)
    devices = [
        Device(
            id=x.id,
            hostname=x.id,
            display_name=x.name,
            type=x.kind,
            vendor="fixture-neutral",
            platform="structured-http",
            site="demo",
            telemetry_source="fixture-http",
            status=ResourceStatus.DOWN
            if any(not i.operational_up for i in x.interfaces)
            else ResourceStatus.UP,
            last_observed_at=now,
        )
        for x in topology.devices
        if x.kind != "service"
    ]
    services = [
        ServiceResource(
            id="orders-api",
            display_name="Orders API",
            endpoint="https://orders.internal",
            telemetry_source="fixture-http",
            status=ResourceStatus.UP,
            last_observed_at=now,
        )
    ]
    interfaces = [
        InventoryInterface(
            id=f"{d.id}/{i.name}",
            device_id=d.id,
            name=i.name,
            management_address=i.ip_address,
            telemetry_source="fixture-http",
            status=ResourceStatus.UP if i.operational_up else ResourceStatus.DOWN,
            last_observed_at=now,
        )
        for d in topology.devices
        for i in d.interfaces
    ]
    links = [
        InventoryLink(
            id=f"{x.device_a}--{x.device_b}",
            device_a=x.device_a,
            device_b=x.device_b,
            interface_a=x.interface_a,
            interface_b=x.interface_b,
            telemetry_source="fixture-http",
            status=ResourceStatus.DEGRADED if x.packet_loss_percent > 5 else ResourceStatus.UP,
            last_observed_at=now,
        )
        for x in topology.links
    ]
    return Inventory(devices=devices, interfaces=interfaces, services=services, links=links)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/datasets")
def datasets() -> list[str]:
    return sorted(DATASETS)


@app.get("/v1/datasets/{dataset}/inventory")
def inventory(dataset: str) -> Inventory:
    _check(dataset)
    return _inventory(dataset)


@app.get("/v1/datasets/{dataset}/topology")
def topology(dataset: str) -> NetworkTopology:
    _check(dataset)
    return _topology(dataset)


@app.get("/v1/datasets/{dataset}/observations/{operation}")
def observation(
    dataset: str,
    operation: str,
    device_id: str | None = None,
    interface_name: str | None = None,
    source: str | None = None,
    destination: str | None = None,
    device_a: str | None = None,
    device_b: str | None = None,
) -> dict[str, Any]:
    _check(dataset)
    topology = _topology(dataset)
    reached = dataset not in {"interface-failure", "route-anomaly"}
    data: dict[str, dict[str, Any]] = {
        "topology": topology.model_dump(mode="json"),
        "ping": {"reachable": reached, "latency_ms": 191 if reached else None},
        "traceroute": {
            "reached": reached,
            "hops": [source, "core-01", destination] if reached else [source],
            "failure_after": None if reached else source,
        },
        "interface_status": next(
            (
                i.model_dump(mode="json")
                for d in topology.devices
                if d.id == device_id
                for i in d.interfaces
                if i.name == interface_name
            ),
            {},
        ),
        "route_table": {
            "routes": next((d.routes for d in topology.devices if d.id == device_id), {})
        },
        "link_metrics": next(
            (
                x.model_dump(mode="json")
                for x in topology.links
                if {x.device_a, x.device_b} == {device_a, device_b}
            ),
            {},
        ),
        "packet_loss": {
            "packet_loss_percent": 100.0
            if not reached
            else (28.0 if dataset in {"degraded-link", "stale-link"} else 0.0)
        },
    }
    if operation not in data:
        raise HTTPException(status_code=404, detail="operation unavailable")
    return {"observed_at": _observed(dataset), "data": data[operation]}


def _check(dataset: str) -> None:
    if dataset not in DATASETS:
        raise HTTPException(status_code=404, detail="unknown dataset")
