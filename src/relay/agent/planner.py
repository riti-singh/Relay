from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import error, request

from pydantic import ValidationError

from relay.domain.models import (
    ActionKind,
    AgentDecision,
    Freshness,
    HypothesisStatus,
    Incident,
    InvestigationContext,
    OperatingMode,
)


class AgentModelError(RuntimeError):
    pass


class MalformedModelResponseError(AgentModelError):
    pass


class AgentModel(Protocol):
    async def decide_next_action(self, context: InvestigationContext) -> AgentDecision: ...


@dataclass(frozen=True)
class PlannedToolCall:
    tool_name: str
    arguments: dict[str, object]
    evidence_summary: str


class InvestigationPlanner(Protocol):
    def plan(self, incident: Incident) -> list[PlannedToolCall]: ...


class DeterministicPlanner:
    """Evidence-driven deterministic model and Milestone 1 plan compatibility adapter."""

    def plan(self, incident: Incident) -> list[PlannedToolCall]:
        args: dict[str, object] = {
            "source": incident.source_device,
            "destination": incident.destination_device,
        }
        return [
            PlannedToolCall("get_network_topology", {}, "Captured current network topology"),
            PlannedToolCall("ping", args, "Tested end-to-end reachability"),
            PlannedToolCall("traceroute", args, "Located the connectivity failure boundary"),
            PlannedToolCall(
                "get_route_table",
                {"device_id": incident.source_device},
                "Inspected source routing state",
            ),
        ]

    async def decide_next_action(self, context: InvestigationContext) -> AgentDecision:
        done = [call.tool_name for call in context.recent_tool_calls]
        endpoints = {"source": context.source_device, "destination": context.destination_device}
        if context.operating_mode is OperatingMode.OBSERVE:
            sequence: list[tuple[str, dict[str, Any], str]] = [
                ("get_network_topology", {}, "Capture external topology"),
                ("ping", endpoints, "Test observed reachability"),
                ("traceroute", endpoints, "Locate observed path failure"),
                (
                    "get_route_table",
                    {"device_id": context.source_device},
                    "Inspect observed source route",
                ),
                (
                    "get_prefix_visibility",
                    {"resource": context.destination_device},
                    "Check global BGP visibility of the destination prefix",
                ),
                (
                    "get_interface_status",
                    {"device_id": "core-01", "interface_name": "eth1"},
                    "Inspect observed uplink",
                ),
                (
                    "get_link_metrics",
                    {"device_a": context.source_device, "device_b": "core-01"},
                    "Inspect observed link health",
                ),
                ("get_packet_loss", endpoints, "Measure observed packet loss"),
            ]
        else:
            sequence = [
                ("get_network_topology", {}, "Capture bounded topology"),
                ("ping", endpoints, "Test IP reachability"),
                ("traceroute", endpoints, "Locate path failure"),
                ("get_route_table", {"device_id": context.source_device}, "Inspect source route"),
                (
                    "get_interface_status",
                    {"device_id": "core-router-02", "interface_name": "eth1"},
                    "Inspect branch uplink",
                ),
                ("test_tcp_connection", {**endpoints, "port": 443}, "Test application service"),
                ("resolve_dns", {"hostname": "payments.internal"}, "Test service DNS"),
                ("get_acl_rules", {"device_id": "core-router-02"}, "Inspect traffic policy"),
                (
                    "get_link_metrics",
                    {"device_a": "branch-03", "device_b": "core-router-02"},
                    "Inspect link health",
                ),
                ("get_packet_loss", endpoints, "Measure packet loss"),
                (
                    "compare_config_to_baseline",
                    {"device_id": "core-router-02"},
                    "Check configuration drift",
                ),
            ]
        for name, arguments, summary in sequence:
            if name not in done:
                return AgentDecision(
                    kind=ActionKind.RUN_TOOL, tool_name=name, arguments=arguments, summary=summary
                )
        finding = self._finding(context)
        active = context.active_hypotheses
        if not active:
            return AgentDecision(
                kind=ActionKind.UPDATE_HYPOTHESIS,
                summary="Evidence supports a root-cause hypothesis",
                hypothesis=finding[0],
                suspected_component=finding[1],
                confidence=0.98,
                hypothesis_status=HypothesisStatus.CONFIRMED,
                supporting_evidence_ids=[e.id for e in context.evidence],
            )
        if context.operating_mode is OperatingMode.OBSERVE:
            return AgentDecision(
                kind=ActionKind.DECLARE_RESOLVED,
                summary=(
                    "Read-only root-cause assessment completed; remediation is intentionally "
                    "unavailable in OBSERVE mode"
                ),
            )
        return AgentDecision(
            kind=ActionKind.PROPOSE_REMEDIATION,
            summary="Propose evidence-backed remediation",
            tool_name=finding[2],
            arguments=finding[3],
            remediation_description=finding[4],
        )

    @staticmethod
    def _finding(context: InvestigationContext) -> tuple[str, str, str, dict[str, Any], str]:
        valid_evidence = [e for e in context.evidence if e.provenance.freshness is Freshness.FRESH]
        observations = {
            c.tool_name: next(
                (e.observation for e in reversed(valid_evidence) if e.tool_call_id == c.id), {}
            )
            for c in context.recent_tool_calls
        }
        interface = observations.get("get_interface_status", {})
        route_table = observations.get("get_route_table", {})
        route = route_table.get("routes", {})
        bgp = observations.get("get_prefix_visibility", {})
        tcp = observations.get("test_tcp_connection", {})
        dns = observations.get("resolve_dns", {})
        acl = observations.get("get_acl_rules", {}).get("rules", [])
        metrics = observations.get("get_link_metrics", {})
        config = observations.get("compare_config_to_baseline", {})
        if context.operating_mode is OperatingMode.OBSERVE:
            topology = observations.get("get_network_topology", {})
            down = next(
                (
                    f"{d['id']}/{i['name']}"
                    for d in topology.get("devices", [])
                    for i in d.get("interfaces", [])
                    if i.get("operational_up") is False
                ),
                None,
            )
            if down:
                return (
                    f"{down} is operationally down",
                    down,
                    "",
                    {},
                    "OBSERVE mode does not permit remediation",
                )
            prefix = bgp.get("prefix") or context.destination_device
            if bgp.get("announced") is False or (
                bgp.get("announced") is True and bgp.get("globally_visible") is False
            ):
                withdrawals = (bgp.get("recent_changes") or {}).get("withdrawals", 0)
                detail = (
                    f"; {withdrawals} withdrawal(s) seen in the recent BGP update window"
                    if withdrawals
                    else ""
                )
                return (
                    f"{prefix} is not globally visible in BGP (origin route withdrawn){detail}",
                    f"{prefix} origin announcement",
                    "",
                    {},
                    "OBSERVE mode does not permit remediation",
                )
            if "routes" in route_table and route.get(context.destination_device) in {
                None,
                "discard",
            }:
                return (
                    (
                        f"{context.source_device} has an anomalous route to "
                        f"{context.destination_device}"
                    ),
                    f"{context.source_device} route",
                    "",
                    {},
                    "OBSERVE mode does not permit remediation",
                )
            if metrics.get("packet_loss_percent", 0) > 5 or metrics.get("latency_ms", 0) > 100:
                component = f"{context.source_device}/core-01 link"
                return (
                    f"{component} is degraded",
                    component,
                    "",
                    {},
                    "OBSERVE mode does not permit remediation",
                )
            ping = observations.get("ping", {})
            if ping.get("reachable") is True:
                return (
                    "No active network fault detected in fresh telemetry",
                    context.destination_device,
                    "",
                    {},
                    "No remediation required",
                )
            if bgp.get("globally_visible") is True:
                origins = ", ".join(f"AS{asn}" for asn in bgp.get("origin_asns", [])) or "unknown"
                seen = (bgp.get("visibility") or {}).get("ris_peers_seeing", 0)
                return (
                    (
                        f"{prefix} is globally announced by {origins} ({seen} RIS peers); "
                        "the fault is in transit or locally, not an origin withdrawal"
                    ),
                    f"{context.source_device} -> {prefix} transit path",
                    "",
                    {},
                    "OBSERVE mode does not permit remediation",
                )
            raise AgentModelError("fresh external telemetry does not identify a root cause")
        if interface.get("admin_up") is False:
            return (
                "core-router-02/eth1 is administratively disabled",
                "core-router-02/eth1",
                "set_interface_admin_state",
                {"device_id": "core-router-02", "interface_name": "eth1", "admin_up": True},
                "Enable the branch uplink",
            )
        if route.get(context.destination_device) != "core-router-02":
            return (
                "branch-03 route to payments-api has wrong next hop core-router-01",
                "branch-03 route",
                "set_static_route",
                {
                    "device_id": "branch-03",
                    "destination": context.destination_device,
                    "next_hop": "core-router-02",
                },
                "Restore the correct static route",
            )
        if tcp.get("reason") == "ACL_DENY" or any(
            r.get("enabled") and r.get("action") == "deny" for r in acl
        ):
            return (
                "core-router-02 ACL denies TCP port 443",
                "core-router-02 ACL",
                "set_acl_rule_enabled",
                {"device_id": "core-router-02", "rule_id": "deny-payments", "enabled": False},
                "Disable the erroneous deny rule",
            )
        if dns.get("target") != context.destination_device:
            return (
                "payments.internal has an incorrect DNS record",
                "payments.internal",
                "set_dns_record",
                {"hostname": "payments.internal", "target": context.destination_device},
                "Restore the service DNS record",
            )
        if metrics.get("packet_loss_percent", 0) > 5 or metrics.get("latency_ms", 0) > 100:
            return (
                "branch-03 uplink is degraded",
                "branch-03/core-router-02 link",
                "repair_link",
                {"device_a": "branch-03", "device_b": "core-router-02"},
                "Repair the degraded branch uplink",
            )
        if config.get("matches") is False:
            return (
                "core-router-02 forwarding configuration drift",
                "core-router-02 config",
                "restore_config_baseline",
                {"device_id": "core-router-02"},
                "Restore the approved configuration baseline",
            )
        raise AgentModelError("evidence does not identify a known deterministic root cause")


class ScriptedAgentModel:
    def __init__(self, decisions: list[AgentDecision | dict[str, Any] | Exception]) -> None:
        self.decisions = list(decisions)

    async def decide_next_action(self, context: InvestigationContext) -> AgentDecision:
        if not self.decisions:
            raise AgentModelError("script exhausted")
        item = self.decisions.pop(0)
        if isinstance(item, Exception):
            raise item
        try:
            return item if isinstance(item, AgentDecision) else AgentDecision.model_validate(item)
        except ValidationError as exc:
            raise MalformedModelResponseError(str(exc)) from exc


class OpenAICompatibleAgentModel:
    """Provider adapter using a JSON-schema response; no provider types escape this module."""

    def __init__(
        self, api_key: str, model: str, base_url: str, timeout_seconds: float = 30
    ) -> None:
        self.api_key, self.model, self.base_url, self.timeout_seconds = (
            api_key,
            model,
            base_url.rstrip("/"),
            timeout_seconds,
        )

    async def decide_next_action(self, context: InvestigationContext) -> AgentDecision:
        return await asyncio.wait_for(
            asyncio.to_thread(self._request, context), timeout=self.timeout_seconds + 1
        )

    def _request(self, context: InvestigationContext) -> AgentDecision:
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "Choose one safe Relay action from the supplied bounded investigation "
                        "context. Return only the structured decision. Never request shell or "
                        "code execution."
                    ),
                },
                {"role": "user", "content": context.model_dump_json()},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "agent_decision",
                    "strict": True,
                    "schema": AgentDecision.model_json_schema(),
                }
            },
        }
        req = request.Request(
            f"{self.base_url}/responses",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read())
            text = raw["output"][0]["content"][0]["text"]
            return AgentDecision.model_validate_json(text)
        except (error.URLError, TimeoutError) as exc:
            raise AgentModelError(f"provider request failed: {exc}") from exc
        except (KeyError, ValueError, ValidationError) as exc:
            raise MalformedModelResponseError(f"malformed provider response: {exc}") from exc
