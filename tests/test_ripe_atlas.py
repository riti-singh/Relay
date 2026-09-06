from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error

import pytest

from relay.adapters.base import DiagnosticOperation
from relay.adapters.ripe_atlas import RIPEAtlasAdapter
from relay.agent.planner import DeterministicPlanner
from relay.domain.models import (
    CommentTarget,
    ObservationStatus,
    OperatingMode,
)
from relay.network.simulator import NetworkSimulator
from relay.repositories.incidents import SQLiteIncidentRepository
from relay.services.incidents import IncidentService
from relay.tools.network_tools import build_registry
from relay.tools.registry import ToolError


def recorded_get(measurement_type: str = "ping", old: bool = False):
    stamp = 1_700_000_000 if old else datetime.now(UTC).timestamp()

    def get(url: str) -> Any:
        if "/probes/" in url:
            probe_id = int(url.rstrip("/").split("/")[-1])
            return {
                "id": probe_id,
                "country_code": "NL" if probe_id == 1 else "DE",
                "asn_v4": 64500 + probe_id,
                "address_v4": f"192.0.2.{probe_id}",
                "status": {"id": 1},
            }
        if "/latest/" in url:
            if measurement_type == "traceroute":
                return [
                    {
                        "msm_id": 200,
                        "prb_id": 1,
                        "timestamp": stamp,
                        "dst_addr": "192.0.2.80",
                        "result": [
                            {"hop": 1, "result": [{"from": "10.0.0.1", "rtt": 1.0}]},
                            {"hop": 2, "result": [{"from": "198.51.100.1", "rtt": 8.0}]},
                        ],
                    },
                    {
                        "msm_id": 200,
                        "prb_id": 2,
                        "timestamp": stamp,
                        "dst_addr": "192.0.2.80",
                        "result": [
                            {"hop": 1, "result": [{"from": "10.0.0.2", "rtt": 1.0}]},
                            {"hop": 2, "result": [{"x": "*"}]},
                        ],
                    },
                ]
            return [
                {
                    "msm_id": 100,
                    "prb_id": 1,
                    "timestamp": stamp,
                    "dst_addr": "192.0.2.80",
                    "result": [{"rtt": 20.0}, {"rtt": 22.0}, {"rtt": 21.0}],
                },
                {
                    "msm_id": 100,
                    "prb_id": 2,
                    "timestamp": stamp,
                    "dst_addr": "192.0.2.80",
                    "result": [{"x": "*"}, {"x": "*"}, {"rtt": 250.0}],
                },
            ]
        return {
            "id": 200 if measurement_type == "traceroute" else 100,
            "type": measurement_type,
            "target_ip": "192.0.2.80",
            "description": "Recorded public measurement",
            "status": {"id": 2, "name": "Ongoing"},
        }

    return get


def test_ping_loss_latency_and_provenance_normalization() -> None:
    adapter = RIPEAtlasAdapter(get_json=recorded_get())
    observation = adapter.collect(DiagnosticOperation.PACKET_LOSS, {"measurement_id": "100"})
    assert observation.status is ObservationStatus.SUCCESS
    assert observation.data["probe_count"] == 2
    assert observation.data["reachable_probe_count"] == 2
    assert observation.data["average_packet_loss_percent"] == 33.34
    assert observation.data["probes"][1]["avg_rtt_ms"] == 250
    assert observation.provenance.measurement_id == "100"
    assert observation.provenance.target == "192.0.2.80"
    assert observation.provenance.measurement_type == "ping"
    assert observation.provenance.observed_at is not None


def test_traceroute_path_comparison_preserves_unknown_hops() -> None:
    adapter = RIPEAtlasAdapter(get_json=recorded_get("traceroute"))
    observation = adapter.collect(DiagnosticOperation.PATH_COMPARISON, {"measurement_id": "200"})
    assert observation.data["distinct_path_count"] == 2
    assert observation.data["paths"][1]["hops"][1]["addresses"] == []
    topology = adapter.topology()
    assert any(device.name == "unknown" for device in topology.devices)


def test_probe_metadata_only_uses_source_fields() -> None:
    adapter = RIPEAtlasAdapter(get_json=recorded_get())
    observation = adapter.collect(
        DiagnosticOperation.PROBE_METADATA,
        {"measurement_id": "100", "probe_ids": [1, 2]},
    )
    assert observation.data["probes"][0] == {
        "probe_id": 1,
        "country_code": "NL",
        "asn_v4": 64501,
        "asn_v6": None,
        "address_v4": "192.0.2.1",
        "address_v6": None,
        "status_id": 1,
    }


def test_stale_malformed_timeout_and_wrong_measurement_type() -> None:
    stale = RIPEAtlasAdapter(get_json=recorded_get(old=True)).collect(
        DiagnosticOperation.LATENCY, {"measurement_id": "100"}
    )
    assert stale.status is ObservationStatus.STALE

    malformed = RIPEAtlasAdapter(get_json=lambda _url: []).collect(
        DiagnosticOperation.LATENCY, {"measurement_id": "100"}
    )
    assert malformed.status is ObservationStatus.FAILED

    def timeout(_url: str) -> Any:
        raise TimeoutError("timed out")

    unavailable = RIPEAtlasAdapter(get_json=timeout).collect(
        DiagnosticOperation.LATENCY, {"measurement_id": "100"}
    )
    assert unavailable.status is ObservationStatus.UNAVAILABLE

    wrong = RIPEAtlasAdapter(get_json=recorded_get("traceroute")).collect(
        DiagnosticOperation.LATENCY, {"measurement_id": "200"}
    )
    assert wrong.status is ObservationStatus.UNSUPPORTED


def test_rate_limit_is_truthful_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def limited(*_args: Any, **_kwargs: Any) -> Any:
        raise error.HTTPError("url", 429, "limited", {}, None)

    monkeypatch.setattr("relay.adapters.ripe_atlas.request.urlopen", limited)
    observation = RIPEAtlasAdapter().collect(DiagnosticOperation.LATENCY, {"measurement_id": "100"})
    assert observation.status is ObservationStatus.UNAVAILABLE
    assert "rate limit" in (observation.message or "")


def service(tmp_path: Path, adapter: RIPEAtlasAdapter) -> IncidentService:
    return IncidentService(
        SQLiteIncidentRepository(str(tmp_path / "relay.db")),
        build_registry(NetworkSimulator()),
        DeterministicPlanner(),
        adapter_factories={"ripe-atlas": lambda _incident: adapter},
    )


def test_capability_registry_and_recorded_agent_investigation(tmp_path: Path) -> None:
    adapter = RIPEAtlasAdapter(get_json=recorded_get())
    registry = build_registry(adapter, include_writes=False)
    schemas = registry.schemas()
    assert set(schemas) == {
        "inspect_reachability",
        "inspect_latency",
        "measure_packet_loss",
        "trace_path",
        "compare_paths",
        "inspect_probe_metadata",
    }
    assert not any(name.startswith(("set_", "modify_", "change_")) for name in schemas)
    with pytest.raises(ToolError):
        registry.execute("get_acl_rules", {"device_id": "router"})

    relay = service(tmp_path, adapter)
    incident = relay.create(
        "Public measurement 100",
        "Investigate public reachability",
        "100",
        "192.0.2.80",
        "100",
        OperatingMode.OBSERVE,
        ["ripe-atlas"],
    )
    result = relay.agent_run(incident.id)
    assert result.conclusion is not None
    assert result.conclusion.kind == "ASSESSMENT"
    assert "packet loss" in result.conclusion.summary.lower()
    assert all(not call.state_changing for call in result.tool_calls)
    assert {call.tool_name for call in result.tool_calls} >= {
        "inspect_reachability",
        "measure_packet_loss",
        "inspect_latency",
    }


def test_comments_annotations_and_operator_follow_up(tmp_path: Path) -> None:
    relay = service(tmp_path, RIPEAtlasAdapter(get_json=recorded_get()))
    incident = relay.create(
        "Public measurement 100",
        "Investigate public reachability",
        "100",
        "192.0.2.80",
        "100",
        OperatingMode.OBSERVE,
        ["ripe-atlas"],
    )
    result = relay.agent_run(incident.id)
    annotated = relay.add_comment(
        result.id,
        "operator",
        "Compare affected probe networks",
        CommentTarget.EVIDENCE,
        result.evidence[0].id,
    )
    assert annotated.comments[-1].target_id == result.evidence[0].id
    followed = relay.add_comment(
        result.id,
        "operator",
        "Check whether affected probes share an ASN",
        request_agent_step=True,
    )
    assert followed.pending_operator_request
    follow_up = relay.agent_run(result.id)
    assert "inspect_probe_metadata" in [call.tool_name for call in follow_up.tool_calls]
    assert any(event.type == "OPERATOR_COMMENT_ADDED" for event in follow_up.events)
