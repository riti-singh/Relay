import pytest

from relay.domain.models import ApprovalState
from relay.network.simulator import NetworkSimulator
from relay.tools.network_tools import build_registry
from relay.tools.registry import ApprovalRequiredError, ToolError


def test_registry_executes_typed_ping(simulator: NetworkSimulator) -> None:
    result = build_registry(simulator).execute(
        "ping", {"source": "branch-03", "destination": "payments-api"}
    )
    assert result.success
    assert result.output == {"reachable": False, "latency_ms": None}


def test_registry_reports_invalid_inputs(simulator: NetworkSimulator) -> None:
    registry = build_registry(simulator)
    assert not registry.execute(
        "ping", {"source": "missing", "destination": "payments-api"}
    ).success
    assert not registry.execute("get_interface_status", {"device_id": "branch-03"}).success
    with pytest.raises(ToolError, match="unknown tool"):
        registry.execute("invented", {})


def test_state_changing_tool_is_blocked_without_explicit_approval(
    simulator: NetworkSimulator,
) -> None:
    registry = build_registry(simulator)
    arguments = {"device_id": "core-router-02", "interface_name": "eth1", "admin_up": True}
    with pytest.raises(ApprovalRequiredError, match="requires explicit approval"):
        registry.execute("set_interface_admin_state", arguments, ApprovalState.PENDING)
    assert simulator.interface("core-router-02", "eth1").admin_up is False
    result = registry.execute("set_interface_admin_state", arguments, ApprovalState.APPROVED)
    assert result.success
    assert simulator.interface("core-router-02", "eth1").admin_up is True
