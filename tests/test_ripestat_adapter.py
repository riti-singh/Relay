from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib import error, parse

import pytest

from relay.adapters import RIPEstatAdapter
from relay.adapters.base import DiagnosticOperation
from relay.domain.models import AdapterCapability, Freshness, ObservationStatus

PREFIX = "193.0.0.0/21"
NOW = datetime.now(UTC).replace(microsecond=0)


def envelope(data: dict[str, Any], time: datetime = NOW) -> dict[str, Any]:
    return {
        "status": "ok",
        "status_code": 200,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "data_call_name": "test",
        "messages": [],
        "data": data,
    }


def routing_status(time: datetime = NOW, announced: bool = True) -> dict[str, Any]:
    return envelope(
        {
            "resource": PREFIX,
            "announced": announced,
            "visibility": {
                "v4": {"ris_peers_seeing": 300 if announced else 0, "total_ris_peers": 320},
                "v6": {"ris_peers_seeing": 0, "total_ris_peers": 300},
            },
            "origins": [{"origin": 3333, "route_objects": ["RIPE"]}] if announced else [],
            "first_seen": {"time": "2000-08-01T00:00:00", "prefix": PREFIX, "origin": "3333"},
            "last_seen": {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "origin": "3333"},
            "less_specifics": [],
            "more_specifics": [{"prefix": "193.0.0.0/22", "origin": "3333"}],
            "query_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        time,
    )


def prefix_overview() -> dict[str, Any]:
    return envelope(
        {
            "resource": PREFIX,
            "announced": True,
            "asns": [{"asn": 3333, "holder": "RIPE-NCC-AS - RIPE NCC"}],
            "block": {"resource": "193.0.0.0/8", "desc": "RIPE NCC"},
        }
    )


def bgp_updates() -> dict[str, Any]:
    return envelope(
        {
            "resource": PREFIX,
            "query_starttime": "2026-01-01T00:00:00",
            "query_endtime": "2026-01-01T02:00:00",
            "updates": [
                {
                    "timestamp": "2026-01-01T00:10:00",
                    "type": "W",
                    "attrs": {"target_prefix": PREFIX, "source_id": "00-1.2.3.4"},
                },
                {
                    "timestamp": "2026-01-01T00:12:00",
                    "type": "A",
                    "attrs": {
                        "target_prefix": PREFIX,
                        "source_id": "00-1.2.3.4",
                        "path": [1, 2, 3333],
                    },
                },
            ],
        }
    )


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def install_ripestat(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, dict[str, Any] | bytes],
) -> list[str]:
    calls: list[str] = []

    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        calls.append(url)
        data_call = url.split("/data/")[1].split("/")[0]
        body = responses[data_call]
        return FakeResponse(body if isinstance(body, bytes) else json.dumps(body).encode())

    monkeypatch.setattr("relay.adapters.ripestat.request.urlopen", fake_urlopen)
    return calls


def adapter(freshness: int = 43200) -> RIPEstatAdapter:
    return RIPEstatAdapter(base_url="https://stat.ripe.net/data/", freshness_seconds=freshness)


def test_adapter_contract_is_read_only_routes_only() -> None:
    source = adapter()
    assert source.source_type == "ripestat" and source.read_only is True
    assert source.capabilities == frozenset(
        {AdapterCapability.ROUTES, AdapterCapability.BGP_VISIBILITY}
    )
    assert source.supports(DiagnosticOperation.ROUTE_TABLE)
    assert source.supports(DiagnosticOperation.PREFIX_VISIBILITY)
    assert not source.supports(DiagnosticOperation.TOPOLOGY)
    assert source.inventory().devices == []
    assert source.topology().devices == []


def test_visibility_and_origin_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_ripestat(
        monkeypatch,
        {
            "routing-status": routing_status(),
            "prefix-overview": prefix_overview(),
            "bgp-updates": bgp_updates(),
        },
    )
    result = adapter().collect(DiagnosticOperation.ROUTE_TABLE, {"destination": "193.0.0.1"})
    assert result.status is ObservationStatus.SUCCESS
    assert result.data["announced"] is True and result.data["globally_visible"] is True
    assert result.data["origin_asns"] == [3333]
    assert result.data["origins"] == [{"asn": 3333, "holder": "RIPE-NCC-AS - RIPE NCC"}]
    assert result.data["visibility"]["ris_peers_seeing"] == 300
    assert result.data["visibility"]["total_ris_peers"] == 620
    assert result.data["recent_changes"]["announcements"] == 1
    assert result.data["recent_changes"]["withdrawals"] == 1
    assert result.data["recent_changes"]["updates"][0]["type"] == "W"
    assert result.data["more_specifics"][0]["prefix"] == "193.0.0.0/22"
    assert result.provenance.freshness is Freshness.FRESH
    assert result.provenance.observed_at == NOW
    assert result.provenance.resource_id == "193.0.0.1"
    assert result.provenance.source_type == "ripestat"
    status_url = result.provenance.source_metadata["routing_status_url"]
    assert status_url.startswith("https://stat.ripe.net/data/routing-status/data.json?")
    assert parse.parse_qs(parse.urlparse(status_url).query)["resource"] == ["193.0.0.1"]
    assert result.provenance.source_metadata["prefix_overview_url"] in calls
    assert result.provenance.source_metadata["bgp_updates_url"] in calls
    assert all(url.startswith("https://stat.ripe.net/data/") for url in calls)


def test_withdrawn_prefix_reports_not_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    install_ripestat(
        monkeypatch,
        {
            "routing-status": routing_status(announced=False),
            "prefix-overview": envelope({"resource": PREFIX, "announced": False, "asns": []}),
            "bgp-updates": envelope({"resource": PREFIX, "updates": []}),
        },
    )
    result = adapter().collect(DiagnosticOperation.ROUTE_TABLE, {"prefix": PREFIX})
    assert result.status is ObservationStatus.SUCCESS
    assert result.data["announced"] is False
    assert result.data["globally_visible"] is False
    assert result.data["origin_asns"] == []
    assert result.data["visibility"]["ris_peers_seeing"] == 0


def test_stale_data_is_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    old = NOW - timedelta(minutes=30)
    install_ripestat(
        monkeypatch,
        {
            "routing-status": routing_status(time=old),
            "prefix-overview": prefix_overview(),
            "bgp-updates": bgp_updates(),
        },
    )
    result = adapter(freshness=60).collect(DiagnosticOperation.ROUTE_TABLE, {"prefix": PREFIX})
    assert result.status is ObservationStatus.STALE
    assert result.provenance.freshness is Freshness.STALE
    assert result.provenance.observed_at == old
    assert result.message and "freshness" in result.message


def test_unsupported_and_missing_resource() -> None:
    source = adapter()
    unsupported = source.collect(DiagnosticOperation.PING, {"destination": "193.0.0.1"})
    assert unsupported.status is ObservationStatus.UNSUPPORTED
    assert unsupported.provenance.freshness is Freshness.UNAVAILABLE
    missing = source.collect(DiagnosticOperation.ROUTE_TABLE, {})
    assert missing.status is ObservationStatus.FAILED
    assert missing.message and "resource" in missing.message


def http_error(code: int) -> error.HTTPError:
    return error.HTTPError("https://stat.ripe.net/data/x", code, "err", {}, None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "raise_exc, expected",
    [
        (lambda: error.URLError("connection refused"), ObservationStatus.UNAVAILABLE),
        (lambda: TimeoutError("deadline exceeded"), ObservationStatus.UNAVAILABLE),
        (lambda: http_error(503), ObservationStatus.UNAVAILABLE),
        (lambda: http_error(400), ObservationStatus.FAILED),
    ],
)
def test_unavailable_paths(
    monkeypatch: pytest.MonkeyPatch,
    raise_exc: Callable[[], Exception],
    expected: ObservationStatus,
) -> None:
    def failing(*_args: object, **_kwargs: object) -> None:
        raise raise_exc()

    monkeypatch.setattr("relay.adapters.ripestat.request.urlopen", failing)
    result = adapter().collect(DiagnosticOperation.ROUTE_TABLE, {"prefix": PREFIX})
    assert result.status is expected
    assert result.provenance.freshness is Freshness.UNAVAILABLE
    assert "routing_status_url" in result.provenance.source_metadata


@pytest.mark.parametrize(
    "responses",
    [
        {"routing-status": b"not-json"},
        {"routing-status": envelope({"resource": PREFIX, "origins": [{"origin": "AS3333"}]})},
        {"routing-status": {"status": "error", "messages": [["error", "bad"]], "data": {}}},
        {"routing-status": {"status": "ok", "data": []}},
    ],
)
def test_malformed_paths(
    monkeypatch: pytest.MonkeyPatch, responses: dict[str, dict[str, Any] | bytes]
) -> None:
    install_ripestat(
        monkeypatch,
        {"prefix-overview": prefix_overview(), "bgp-updates": bgp_updates(), **responses},
    )
    result = adapter().collect(DiagnosticOperation.ROUTE_TABLE, {"prefix": PREFIX})
    assert result.status is ObservationStatus.FAILED
    assert result.message and "malformed" in result.message


def test_registered_in_incident_service_factories(monkeypatch: pytest.MonkeyPatch) -> None:
    from relay.api import dependencies
    from relay.config import Settings

    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: Settings(database_path=":memory:", seed_demo_data=False),
    )
    dependencies.get_incident_service.cache_clear()
    service = dependencies.get_incident_service()
    factories = service.adapter_factories
    assert "ripestat" in factories
    dependencies.get_incident_service.cache_clear()
