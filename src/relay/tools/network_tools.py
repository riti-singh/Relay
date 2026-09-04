from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from relay.domain.models import ToolRisk
from relay.network.simulator import NetworkSimulator
from relay.tools.registry import Tool

if TYPE_CHECKING:
    from relay.tools.registry import ToolRegistry


class EmptyInput(BaseModel):
    pass


class DeviceInput(BaseModel):
    device_id: str


class ConnectivityInput(BaseModel):
    source: str
    destination: str


class InterfaceInput(BaseModel):
    device_id: str
    interface_name: str


class SetInterfaceAdminStateInput(InterfaceInput):
    admin_up: bool


class TCPInput(ConnectivityInput):
    port: int = Field(ge=1, le=65535)


class DNSInput(BaseModel):
    hostname: str


class RouteInput(BaseModel):
    device_id: str
    destination: str
    next_hop: str


class ACLWriteInput(BaseModel):
    device_id: str
    rule_id: str
    enabled: bool


class DNSWriteInput(BaseModel):
    hostname: str
    target: str


class LinkInput(BaseModel):
    device_a: str
    device_b: str


class PingTool(Tool[ConnectivityInput]):
    name = "ping"
    input_model = ConnectivityInput
    retryable = True

    def run(self, inputs: ConnectivityInput) -> dict[str, Any]:
        path = self.simulator.path(inputs.source, inputs.destination)
        return {"reachable": path is not None, "latency_ms": path[1] if path else None}


class TracerouteTool(Tool[ConnectivityInput]):
    name = "traceroute"
    input_model = ConnectivityInput
    retryable = True

    def run(self, inputs: ConnectivityInput) -> dict[str, Any]:
        return self.simulator.trace(inputs.source, inputs.destination)


class TopologyTool(Tool[EmptyInput]):
    name = "get_network_topology"
    input_model = EmptyInput

    def run(self, inputs: EmptyInput) -> dict[str, Any]:
        return self.simulator.topology().model_dump(mode="json")


class InterfaceStatusTool(Tool[InterfaceInput]):
    name = "get_interface_status"
    input_model = InterfaceInput

    def run(self, inputs: InterfaceInput) -> dict[str, Any]:
        return self.simulator.interface(inputs.device_id, inputs.interface_name).model_dump(
            mode="json"
        )


class RouteTableTool(Tool[DeviceInput]):
    name = "get_route_table"
    input_model = DeviceInput

    def run(self, inputs: DeviceInput) -> dict[str, Any]:
        return {"routes": self.simulator.device(inputs.device_id).routes}


class DeviceLogsTool(Tool[DeviceInput]):
    name = "get_device_logs"
    input_model = DeviceInput

    def run(self, inputs: DeviceInput) -> dict[str, Any]:
        return {"logs": self.simulator.device(inputs.device_id).logs}


class DeviceConfigTool(Tool[DeviceInput]):
    name = "get_device_config"
    input_model = DeviceInput

    def run(self, inputs: DeviceInput) -> dict[str, Any]:
        return {"config": self.simulator.device(inputs.device_id).config}


class ResolveDNSTool(Tool[DNSInput]):
    name = "resolve_dns"
    input_model = DNSInput
    retryable = True

    def run(self, inputs: DNSInput) -> dict[str, Any]:
        return {
            "hostname": inputs.hostname,
            "target": self.simulator.dns_records.get(inputs.hostname),
            "resolved": inputs.hostname in self.simulator.dns_records,
        }


class TestTCPTool(Tool[TCPInput]):
    name = "test_tcp_connection"
    input_model = TCPInput
    retryable = True

    def run(self, inputs: TCPInput) -> dict[str, Any]:
        return self.simulator.tcp_test(inputs.source, inputs.destination, inputs.port)


class ACLRulesTool(Tool[DeviceInput]):
    name = "get_acl_rules"
    input_model = DeviceInput

    def run(self, inputs: DeviceInput) -> dict[str, Any]:
        return {"rules": self.simulator.device(inputs.device_id).acl_rules}


class LinkMetricsTool(Tool[LinkInput]):
    name = "get_link_metrics"
    input_model = LinkInput

    def run(self, inputs: LinkInput) -> dict[str, Any]:
        return self.simulator._find_link(inputs.device_a, inputs.device_b).model_dump(mode="json")


class PacketLossTool(Tool[ConnectivityInput]):
    name = "get_packet_loss"
    input_model = ConnectivityInput
    retryable = True

    def run(self, inputs: ConnectivityInput) -> dict[str, Any]:
        return {
            "packet_loss_percent": self.simulator.packet_loss(inputs.source, inputs.destination)
        }


class CompareConfigTool(Tool[DeviceInput]):
    name = "compare_config_to_baseline"
    input_model = DeviceInput

    def run(self, inputs: DeviceInput) -> dict[str, Any]:
        device = self.simulator.device(inputs.device_id)
        return {
            "matches": device.config == device.baseline_config,
            "current": device.config,
            "baseline": device.baseline_config,
        }


class RecentChangesTool(Tool[DeviceInput]):
    name = "get_recent_config_changes"
    input_model = DeviceInput

    def run(self, inputs: DeviceInput) -> dict[str, Any]:
        self.simulator.device(inputs.device_id)
        return {
            "changes": [c for c in self.simulator.recent_changes if c["device"] == inputs.device_id]
        }


class WriteTool[T: BaseModel](Tool[T]):
    risk = ToolRisk.LOW_RISK_WRITE


class SetInterfaceAdminStateTool(WriteTool[SetInterfaceAdminStateInput]):
    name = "set_interface_admin_state"
    input_model = SetInterfaceAdminStateInput

    def run(self, inputs: SetInterfaceAdminStateInput) -> dict[str, Any]:
        return self.simulator.set_interface_admin_state(
            inputs.device_id, inputs.interface_name, inputs.admin_up
        ).model_dump(mode="json")


class SetStaticRouteTool(WriteTool[RouteInput]):
    name = "set_static_route"
    input_model = RouteInput

    def run(self, inputs: RouteInput) -> dict[str, Any]:
        return self.simulator.set_route(inputs.device_id, inputs.destination, inputs.next_hop)


class SetACLRuleEnabledTool(WriteTool[ACLWriteInput]):
    name = "set_acl_rule_enabled"
    input_model = ACLWriteInput

    def run(self, inputs: ACLWriteInput) -> dict[str, Any]:
        return self.simulator.set_acl_enabled(inputs.device_id, inputs.rule_id, inputs.enabled)


class SetDNSRecordTool(WriteTool[DNSWriteInput]):
    name = "set_dns_record"
    input_model = DNSWriteInput

    def run(self, inputs: DNSWriteInput) -> dict[str, Any]:
        return self.simulator.set_dns_record(inputs.hostname, inputs.target)


class RepairLinkTool(WriteTool[LinkInput]):
    name = "repair_link"
    input_model = LinkInput

    def run(self, inputs: LinkInput) -> dict[str, Any]:
        return self.simulator.repair_link(inputs.device_a, inputs.device_b)


class RestoreConfigBaselineTool(WriteTool[DeviceInput]):
    name = "restore_config_baseline"
    input_model = DeviceInput

    def run(self, inputs: DeviceInput) -> dict[str, Any]:
        return self.simulator.restore_baseline(inputs.device_id)


def build_registry(simulator: NetworkSimulator, max_retries: int = 1) -> "ToolRegistry":
    from relay.tools.registry import ToolRegistry

    return ToolRegistry(
        [
            PingTool(simulator),
            TracerouteTool(simulator),
            TopologyTool(simulator),
            InterfaceStatusTool(simulator),
            RouteTableTool(simulator),
            DeviceLogsTool(simulator),
            DeviceConfigTool(simulator),
            ResolveDNSTool(simulator),
            TestTCPTool(simulator),
            ACLRulesTool(simulator),
            LinkMetricsTool(simulator),
            PacketLossTool(simulator),
            CompareConfigTool(simulator),
            RecentChangesTool(simulator),
            SetInterfaceAdminStateTool(simulator),
            SetStaticRouteTool(simulator),
            SetACLRuleEnabledTool(simulator),
            SetDNSRecordTool(simulator),
            RepairLinkTool(simulator),
            RestoreConfigBaselineTool(simulator),
        ],
        max_retries=max_retries,
    )
