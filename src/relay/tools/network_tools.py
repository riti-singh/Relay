from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

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


class PingTool(Tool[ConnectivityInput]):
    name = "ping"
    input_model = ConnectivityInput

    def run(self, inputs: ConnectivityInput) -> dict[str, Any]:
        path = self.simulator.path(inputs.source, inputs.destination)
        return {"reachable": path is not None, "latency_ms": path[1] if path else None}


class TracerouteTool(Tool[ConnectivityInput]):
    name = "traceroute"
    input_model = ConnectivityInput

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


class SetInterfaceAdminStateTool(Tool[SetInterfaceAdminStateInput]):
    name = "set_interface_admin_state"
    input_model = SetInterfaceAdminStateInput
    state_changing = True

    def run(self, inputs: SetInterfaceAdminStateInput) -> dict[str, Any]:
        interface = self.simulator.set_interface_admin_state(
            inputs.device_id, inputs.interface_name, inputs.admin_up
        )
        return interface.model_dump(mode="json")


def build_registry(simulator: NetworkSimulator) -> "ToolRegistry":
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
            SetInterfaceAdminStateTool(simulator),
        ]
    )
