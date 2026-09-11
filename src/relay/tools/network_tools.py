from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from relay.adapters.base import DiagnosticOperation, NetworkAdapter
from relay.adapters.simulator import SimulatorNetworkAdapter
from relay.domain.models import AdapterObservation, ToolRisk
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


class PrefixInput(BaseModel):
    resource: str


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

    def run(self, inputs: ConnectivityInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.PING, inputs.model_dump())


class TracerouteTool(Tool[ConnectivityInput]):
    name = "traceroute"
    input_model = ConnectivityInput
    retryable = True

    def run(self, inputs: ConnectivityInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.TRACEROUTE, inputs.model_dump())


class TopologyTool(Tool[EmptyInput]):
    name = "get_network_topology"
    input_model = EmptyInput

    def run(self, inputs: EmptyInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.TOPOLOGY, {})


class InterfaceStatusTool(Tool[InterfaceInput]):
    name = "get_interface_status"
    input_model = InterfaceInput

    def run(self, inputs: InterfaceInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.INTERFACE_STATUS, inputs.model_dump())


class RouteTableTool(Tool[DeviceInput]):
    name = "get_route_table"
    input_model = DeviceInput

    def run(self, inputs: DeviceInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.ROUTE_TABLE, inputs.model_dump())


class PrefixVisibilityTool(Tool[PrefixInput]):
    name = "get_prefix_visibility"
    input_model = PrefixInput

    def run(self, inputs: PrefixInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.PREFIX_VISIBILITY, inputs.model_dump())


class DeviceLogsTool(Tool[DeviceInput]):
    name = "get_device_logs"
    input_model = DeviceInput

    def run(self, inputs: DeviceInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.DEVICE_LOGS, inputs.model_dump())


class DeviceConfigTool(Tool[DeviceInput]):
    name = "get_device_config"
    input_model = DeviceInput

    def run(self, inputs: DeviceInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.DEVICE_CONFIG, inputs.model_dump())


class ResolveDNSTool(Tool[DNSInput]):
    name = "resolve_dns"
    input_model = DNSInput
    retryable = True

    def run(self, inputs: DNSInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.RESOLVE_DNS, inputs.model_dump())


class TestTCPTool(Tool[TCPInput]):
    name = "test_tcp_connection"
    input_model = TCPInput
    retryable = True

    def run(self, inputs: TCPInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.TEST_TCP, inputs.model_dump())


class ACLRulesTool(Tool[DeviceInput]):
    name = "get_acl_rules"
    input_model = DeviceInput

    def run(self, inputs: DeviceInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.ACL_RULES, inputs.model_dump())


class LinkMetricsTool(Tool[LinkInput]):
    name = "get_link_metrics"
    input_model = LinkInput

    def run(self, inputs: LinkInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.LINK_METRICS, inputs.model_dump())


class PacketLossTool(Tool[ConnectivityInput]):
    name = "get_packet_loss"
    input_model = ConnectivityInput
    retryable = True

    def run(self, inputs: ConnectivityInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.PACKET_LOSS, inputs.model_dump())


class CompareConfigTool(Tool[DeviceInput]):
    name = "compare_config_to_baseline"
    input_model = DeviceInput

    def run(self, inputs: DeviceInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.COMPARE_CONFIG, inputs.model_dump())


class RecentChangesTool(Tool[DeviceInput]):
    name = "get_recent_config_changes"
    input_model = DeviceInput

    def run(self, inputs: DeviceInput) -> AdapterObservation:
        return self.adapter.collect(DiagnosticOperation.RECENT_CHANGES, inputs.model_dump())


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


def build_registry(
    source: NetworkSimulator | NetworkAdapter, max_retries: int = 1, include_writes: bool = True
) -> "ToolRegistry":
    from relay.tools.registry import ToolRegistry

    adapter = SimulatorNetworkAdapter(source) if isinstance(source, NetworkSimulator) else source
    reads: list[Tool[Any]] = [
        PingTool(adapter),
        TracerouteTool(adapter),
        TopologyTool(adapter),
        InterfaceStatusTool(adapter),
        RouteTableTool(adapter),
        PrefixVisibilityTool(adapter),
        DeviceLogsTool(adapter),
        DeviceConfigTool(adapter),
        ResolveDNSTool(adapter),
        TestTCPTool(adapter),
        ACLRulesTool(adapter),
        LinkMetricsTool(adapter),
        PacketLossTool(adapter),
        CompareConfigTool(adapter),
        RecentChangesTool(adapter),
    ]
    writes: list[Tool[Any]] = (
        [
            SetInterfaceAdminStateTool(adapter),
            SetStaticRouteTool(adapter),
            SetACLRuleEnabledTool(adapter),
            SetDNSRecordTool(adapter),
            RepairLinkTool(adapter),
            RestoreConfigBaselineTool(adapter),
        ]
        if include_writes
        else []
    )
    return ToolRegistry([*reads, *writes], max_retries=max_retries, read_only=not include_writes)
