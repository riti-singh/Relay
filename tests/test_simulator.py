import pytest

from relay.network.simulator import NetworkError, NetworkSimulator


def test_seeded_topology_has_required_nodes_and_disabled_interface(
    simulator: NetworkSimulator,
) -> None:
    ids = {device.id for device in simulator.topology().devices}
    assert {"branch-01", "branch-03", "core-router-01", "core-router-02", "payments-api"} <= ids
    interface = simulator.interface("core-router-02", "eth1")
    assert not interface.admin_up
    assert not interface.operational_up


def test_seeded_failure_and_control_path(simulator: NetworkSimulator) -> None:
    assert simulator.path("branch-03", "payments-api") is None
    assert simulator.path("branch-01", "payments-api") == (
        ["branch-01", "core-router-01", "core-router-02", "payments-api"],
        10,
    )
    trace = simulator.trace("branch-03", "payments-api")
    assert trace == {"reached": False, "hops": ["branch-03"], "failure_after": "branch-03"}


def test_enabling_interface_restores_path(simulator: NetworkSimulator) -> None:
    simulator.set_interface_admin_state("core-router-02", "eth1", True)
    assert simulator.path("branch-03", "payments-api") == (
        ["branch-03", "core-router-02", "payments-api"],
        8,
    )


def test_invalid_device_and_interface_are_useful(simulator: NetworkSimulator) -> None:
    with pytest.raises(NetworkError, match="unknown device: missing"):
        simulator.device("missing")
    with pytest.raises(NetworkError, match="unknown interface: branch-03/missing"):
        simulator.interface("branch-03", "missing")
