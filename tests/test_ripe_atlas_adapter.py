from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib import error

import pytest

from relay.adapters.base import DiagnosticOperation
from relay.adapters.ripe_atlas import RIPEAtlasAdapter
from relay.domain.models import AdapterCapability, Freshness, ObservationStatus

MEASUREMENTS = {"ping": 1001, "traceroute": 5010, "dns": 7020}


def adapter(freshness: int = 3600) -> RIPEAtlasAdapter:
    return RIPEAtlasAdapter(
        "ripe-atlas",
        "RIPE Atlas public measurements",
        "https://atlas.ripe.net/api/v2",
        MEASUREMENTS,
        None,
        0.2,
        freshness,
    )


def epoch(seconds_ago: int = 30) -> int:
    return int((datetime.now(UTC) - timedelta(seconds=seconds_ago)).timestamp())


def ping_results(seconds_ago: int = 30) -> list[dict[str, Any]]:
    return [
        {
            "prb_id": 11,
            "timestamp": epoch(seconds_ago),
            "dst_name": "payments.example.net",
            "sent": 3,
            "rcvd": 3,
            "min": 10.0,
            "avg": 12.0,
            "max": 14.0,
        },
        {
            "prb_id": 12,
            "timestamp": epoch(seconds_ago + 5),
            "dst_name": "payments.example.net",
            "sent": 3,
            "rcvd": 1,
            "min": 40.0,
            "avg": 44.0,
            "max": 48.0,
        },
    ]


def traceroute_results() -> list[dict[str, Any]]:
    return [
        {
            "prb_id": 21,
            "timestamp": epoch(),
            "dst_name": "payments.example.net",
            "result": [
                {"hop": 1, "result": [{"from": "10.0.0.1", "rtt": 1.2, "as": 64500}]},
                {"hop": 2, "result": [{"from": "10.0.1.1", "rtt": 2.0, "as": 64501}]},
                {"hop": 3, "result": [{"x": "*"}, {"from": "10.0.2.1", "rtt": 90.0}]},
            ],
        }
    ]


def dns_results() -> list[dict[str, Any]]:
    return [
        {
            "prb_id": 31,
            "timestamp": epoch(),
            "dst_name": "payments.example.net",
            "result": {
                "rt": 24.5,
                "ANCOUNT": 1,
                "answers": [{"NAME": "payments.example.net", "TYPE": "A", "RDATA": "203.0.113.7"}],
            },
        },
        {"prb_id": 32, "timestamp": epoch(), "error": {"timeout": 5000}},
    ]


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode()


def patch_urlopen(monkeypatch: pytest.MonkeyPatch, payload: object) -> list[str]:
    urls: list[str] = []

    def fake_urlopen(request_object: Any, **_kwargs: object) -> FakeResponse:
        urls.append(request_object.full_url)
        return FakeResponse(payload)

    monkeypatch.setattr("relay.adapters.ripe_atlas.request.urlopen", fake_urlopen)
    return urls


def test_adapter_is_read_only_with_declared_capabilities() -> None:
    source = adapter()
    assert source.source_type == "ripe-atlas"
    assert source.read_only is True
    assert source.capabilities == frozenset(
        {AdapterCapability.REACHABILITY, AdapterCapability.PACKET_LOSS, AdapterCapability.DNS}
    )
    assert AdapterCapability.TOPOLOGY not in source.capabilities
    assert source.inventory().devices == []
    assert source.topology().devices == []


def test_ping_normalization_and_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = patch_urlopen(monkeypatch, ping_results())
    result = adapter().collect(
        DiagnosticOperation.PING, {"source": "probe", "destination": "payments.example.net"}
    )
    assert result.status is ObservationStatus.SUCCESS
    assert result.data["packet_loss_percent"] == pytest.approx(33.33)
    assert result.data["latency_min_ms"] == 10.0
    assert result.data["latency_avg_ms"] == 28.0
    assert result.data["latency_max_ms"] == 48.0
    assert result.data["reachable"] is True
    provenance = result.provenance
    assert provenance.source_type == "ripe-atlas"
    assert provenance.adapter == "ripe-atlas"
    assert provenance.resource_id == "payments.example.net"
    assert provenance.measurement == "1001"
    assert provenance.freshness is Freshness.FRESH
    assert provenance.observed_at is not None
    assert (
        provenance.source_metadata["measurement_url"] == "https://atlas.ripe.net/measurements/1001/"
    )
    assert provenance.source_metadata["probes_total"] == 2
    assert provenance.source_metadata["probes_affected"] == 1
    assert urls == ["https://atlas.ripe.net/api/v2/measurements/1001/results/?format=json"]


def test_packet_loss_reuses_ping_measurement(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = patch_urlopen(monkeypatch, ping_results())
    result = adapter().collect(
        DiagnosticOperation.PACKET_LOSS, {"source": "probe", "destination": "payments.example.net"}
    )
    assert result.status is ObservationStatus.SUCCESS
    assert result.provenance.measurement == "1001"
    assert "measurements/1001/results/" in urls[0]


def test_stale_results_are_classified_as_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_urlopen(monkeypatch, ping_results(seconds_ago=7200))
    result = adapter(freshness=600).collect(
        DiagnosticOperation.PING, {"source": "probe", "destination": "payments.example.net"}
    )
    assert result.status is ObservationStatus.STALE
    assert result.provenance.freshness is Freshness.STALE
    assert result.message is not None


def test_traceroute_normalizes_hops_and_flags_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_urlopen(monkeypatch, traceroute_results())
    result = adapter().collect(
        DiagnosticOperation.TRACEROUTE, {"source": "probe", "destination": "payments.example.net"}
    )
    assert result.status is ObservationStatus.SUCCESS
    assert result.data["hop_count"] == 3
    assert result.data["as_path"] == [64500, 64501]
    assert result.data["first_loss_hop"] == 3
    assert result.data["first_latency_increase_hop"] == 3
    assert result.data["hops"][2]["rtt_avg_ms"] == 90.0
    assert result.provenance.measurement == "5010"


def test_dns_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_urlopen(monkeypatch, dns_results())
    result = adapter().collect(
        DiagnosticOperation.RESOLVE_DNS, {"hostname": "payments.example.net"}
    )
    assert result.status is ObservationStatus.SUCCESS
    assert result.data["resolved"] is True
    assert result.data["addresses"] == ["203.0.113.7"]
    assert result.data["probes_failed"] == 1
    assert result.data["response_time_avg_ms"] == 24.5
    assert result.provenance.source_metadata["measurement_id"] == 7020


def test_measurement_id_argument_overrides_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = patch_urlopen(monkeypatch, ping_results())
    result = adapter().collect(
        DiagnosticOperation.PING,
        {"source": "probe", "destination": "payments.example.net", "measurement_id": 4242},
    )
    assert result.provenance.measurement == "4242"
    assert "measurements/4242/results/" in urls[0]


def test_unsupported_operation() -> None:
    result = adapter().collect(DiagnosticOperation.DEVICE_CONFIG, {"device_id": "core-01"})
    assert result.status is ObservationStatus.UNSUPPORTED
    assert result.provenance.freshness is Freshness.UNAVAILABLE


def test_unconfigured_measurement_is_unavailable() -> None:
    source = RIPEAtlasAdapter("ripe-atlas", "RIPE Atlas", "https://atlas.ripe.net/api/v2", {})
    result = source.collect(DiagnosticOperation.PING, {"destination": "payments.example.net"})
    assert result.status is ObservationStatus.UNAVAILABLE


@pytest.mark.parametrize("exception", [error.URLError("no route"), TimeoutError("deadline")])
def test_network_errors_are_unavailable(
    monkeypatch: pytest.MonkeyPatch, exception: Exception
) -> None:
    def raise_error(*_args: object, **_kwargs: object) -> None:
        raise exception

    monkeypatch.setattr("relay.adapters.ripe_atlas.request.urlopen", raise_error)
    result = adapter().collect(DiagnosticOperation.PING, {"destination": "payments.example.net"})
    assert result.status is ObservationStatus.UNAVAILABLE
    assert result.provenance.measurement == "1001"


@pytest.mark.parametrize(
    "payload",
    [b"not-json", {"detail": "not a list"}, [], [{"prb_id": 1, "sent": 0, "rcvd": 0}]],
)
def test_malformed_responses_fail(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
    patch_urlopen(monkeypatch, payload)
    result = adapter().collect(DiagnosticOperation.PING, {"destination": "payments.example.net"})
    assert result.status is ObservationStatus.FAILED


def test_api_key_is_sent_as_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    headers: list[dict[str, str]] = []

    def fake_urlopen(request_object: Any, **_kwargs: object) -> FakeResponse:
        headers.append(dict(request_object.headers))
        return FakeResponse(ping_results())

    monkeypatch.setattr("relay.adapters.ripe_atlas.request.urlopen", fake_urlopen)
    source = RIPEAtlasAdapter(
        "ripe-atlas", "RIPE Atlas", "https://atlas.ripe.net/api/v2", MEASUREMENTS, "secret-key"
    )
    source.collect(DiagnosticOperation.PING, {"destination": "payments.example.net"})
    assert headers[0]["Authorization"] == "Key secret-key"


@pytest.mark.skipif(
    os.environ.get("RELAY_RIPE_ATLAS_LIVE_SMOKE") != "1",
    reason="opt-in live smoke test against the public RIPE Atlas API",
)
def test_live_public_measurement_smoke() -> None:
    measurement_id = int(os.environ.get("RELAY_RIPE_ATLAS_LIVE_MEASUREMENT_ID", "1001"))
    source = RIPEAtlasAdapter(
        "ripe-atlas",
        "RIPE Atlas",
        "https://atlas.ripe.net/api/v2",
        {"ping": measurement_id},
        timeout_seconds=15,
    )
    result = source.collect(DiagnosticOperation.PING, {"destination": "live"})
    assert result.status in {ObservationStatus.SUCCESS, ObservationStatus.STALE}
    assert result.provenance.measurement == str(measurement_id)
