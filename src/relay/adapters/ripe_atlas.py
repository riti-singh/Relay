from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from statistics import fmean
from typing import Any
from urllib import error, parse, request

from pydantic import ValidationError

from relay.adapters.base import OPERATION_CAPABILITY, DiagnosticOperation, NetworkAdapter
from relay.domain.models import (
    AdapterCapability,
    AdapterObservation,
    Freshness,
    Inventory,
    NetworkTopology,
    ObservationProvenance,
    ObservationStatus,
)

MEASUREMENT_KIND: dict[DiagnosticOperation, str] = {
    DiagnosticOperation.PING: "ping",
    DiagnosticOperation.PACKET_LOSS: "ping",
    DiagnosticOperation.TRACEROUTE: "traceroute",
    DiagnosticOperation.RESOLVE_DNS: "dns",
}


class RIPEAtlasAdapter(NetworkAdapter):
    """Read-only view over existing public RIPE Atlas measurements; it never creates one."""

    source_type = "ripe-atlas"
    read_only = True

    def __init__(
        self,
        adapter_id: str,
        display_name: str,
        base_url: str = "https://atlas.ripe.net/api/v2",
        measurement_ids: Mapping[str, int] | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 5,
        freshness_seconds: int = 3600,
    ) -> None:
        self.adapter_id, self.display_name = adapter_id, display_name
        self.base_url = base_url.rstrip("/")
        self.measurement_ids = dict(measurement_ids or {})
        self.api_key = api_key
        self.timeout_seconds, self.freshness_seconds = timeout_seconds, freshness_seconds
        self.capabilities = frozenset(
            {
                AdapterCapability.REACHABILITY,
                AdapterCapability.PACKET_LOSS,
                AdapterCapability.DNS,
            }
        )
        self.last_successful_observation: datetime | None = None

    def collect(
        self, operation: DiagnosticOperation, arguments: dict[str, Any]
    ) -> AdapterObservation:
        capability = OPERATION_CAPABILITY[operation]
        now = datetime.now(UTC)
        provenance = ObservationProvenance(
            source_type=self.source_type,
            adapter=self.adapter_id,
            resource_id=self._resource(arguments),
            collected_at=now,
            freshness=Freshness.UNAVAILABLE,
            query_identity=operation.value,
        )
        if capability not in self.capabilities or operation not in MEASUREMENT_KIND:
            return AdapterObservation(
                status=ObservationStatus.UNSUPPORTED,
                provenance=provenance,
                message=(
                    f"{self.display_name} does not expose "
                    f"{capability.value.lower().replace('_', ' ')}"
                ),
            )
        kind = MEASUREMENT_KIND[operation]
        measurement_id = self._measurement_id(kind, arguments)
        if measurement_id is None:
            return AdapterObservation(
                status=ObservationStatus.UNAVAILABLE,
                provenance=provenance,
                message=f"no RIPE Atlas {kind} measurement is configured for this adapter",
            )
        provenance.measurement = str(measurement_id)
        try:
            results = self._results(measurement_id)
            data, observed_at, probes_total, probes_affected = _NORMALIZERS[kind](results)
        except (error.URLError, TimeoutError) as exc:
            return AdapterObservation(
                status=ObservationStatus.UNAVAILABLE,
                provenance=provenance,
                message=f"RIPE Atlas measurement {measurement_id} unavailable: {exc}",
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError, ValidationError) as exc:
            return AdapterObservation(
                status=ObservationStatus.FAILED,
                provenance=provenance,
                message=f"malformed RIPE Atlas response: {exc}",
            )
        provenance.observed_at = observed_at
        provenance.resource_id = provenance.resource_id or data.get("target")
        provenance.source_metadata = {
            "measurement_id": measurement_id,
            "measurement_type": kind,
            "measurement_url": f"{self._public_base()}/measurements/{measurement_id}/",
            "probes_total": probes_total,
            "probes_affected": probes_affected,
        }
        is_stale = now - observed_at > timedelta(seconds=self.freshness_seconds)
        provenance.freshness = Freshness.STALE if is_stale else Freshness.FRESH
        self.last_successful_observation = now
        return AdapterObservation(
            status=ObservationStatus.STALE if is_stale else ObservationStatus.SUCCESS,
            data=data,
            provenance=provenance,
            message="Measurement results are older than the configured freshness threshold"
            if is_stale
            else None,
        )

    def inventory(self) -> Inventory:
        """RIPE Atlas exposes public probes rather than an operator inventory."""
        return Inventory()

    def topology(self) -> NetworkTopology:
        """Atlas paths are not an owned topology, so the adapter never claims TOPOLOGY."""
        return NetworkTopology(devices=[], links=[])

    def _measurement_id(self, kind: str, arguments: dict[str, Any]) -> int | None:
        override = arguments.get("measurement_id")
        if override is not None:
            return int(override)
        configured = self.measurement_ids.get(kind)
        return int(configured) if configured is not None else None

    def _results(self, measurement_id: int) -> list[dict[str, Any]]:
        url = f"{self.base_url}/measurements/{measurement_id}/results/?format=json"
        headers = {"Authorization": f"Key {self.api_key}"} if self.api_key else {}
        with request.urlopen(
            request.Request(url, headers=headers), timeout=self.timeout_seconds
        ) as response:
            body = json.loads(response.read())
        if not isinstance(body, list):
            raise ValueError("measurement results must be a list")
        results = [item for item in body if isinstance(item, dict)]
        if not results:
            raise ValueError(f"measurement {measurement_id} returned no results")
        return results

    def _public_base(self) -> str:
        parts = parse.urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}" if parts.netloc else self.base_url

    @staticmethod
    def _resource(arguments: dict[str, Any]) -> str | None:
        target = arguments.get("destination") or arguments.get("hostname")
        return str(target) if target else None


def _timestamp(result: Mapping[str, Any]) -> datetime:
    return datetime.fromtimestamp(int(result["timestamp"]), UTC)


def _observed_at(results: Sequence[Mapping[str, Any]]) -> datetime:
    return max(_timestamp(result) for result in results)


def _target(results: Sequence[Mapping[str, Any]]) -> str | None:
    for result in results:
        name = result.get("dst_name") or result.get("dst_addr")
        if name:
            return str(name)
    return None


def _normalize_ping(
    results: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], datetime, int, int]:
    sent = sum(int(result.get("sent", 0)) for result in results)
    received = sum(int(result.get("rcvd", 0)) for result in results)
    if sent <= 0:
        raise ValueError("ping results contain no sent packets")
    latencies = [
        (float(result["min"]), float(result["avg"]), float(result["max"]))
        for result in results
        if float(result.get("avg", -1)) >= 0
    ]
    affected = [result for result in results if int(result.get("rcvd", 0)) < int(result["sent"])]
    packet_loss_percent = round(100 * (sent - received) / sent, 2)
    data: dict[str, Any] = {
        "target": _target(results),
        "reachable": received > 0,
        "packet_loss_percent": packet_loss_percent,
        "packets_sent": sent,
        "packets_received": received,
        "latency_min_ms": round(min(item[0] for item in latencies), 3) if latencies else None,
        "latency_avg_ms": round(fmean(item[1] for item in latencies), 3) if latencies else None,
        "latency_max_ms": round(max(item[2] for item in latencies), 3) if latencies else None,
        "probes": [
            {
                "probe_id": result.get("prb_id"),
                "packet_loss_percent": round(
                    100 * (int(result["sent"]) - int(result.get("rcvd", 0))) / int(result["sent"]),
                    2,
                )
                if int(result["sent"]) > 0
                else None,
                "latency_avg_ms": result.get("avg"),
            }
            for result in results
        ],
    }
    return data, _observed_at(results), len(results), len(affected)


def _hop_replies(hop: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    replies = hop.get("result", [])
    return [reply for reply in replies if isinstance(reply, dict)]


def _normalize_traceroute(
    results: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], datetime, int, int]:
    hops: dict[int, dict[str, Any]] = {}
    for result in results:
        for hop in result.get("result", []):
            if not isinstance(hop, dict):
                continue
            number = int(hop["hop"])
            entry = hops.setdefault(
                number, {"hop": number, "addresses": [], "rtts": [], "timeouts": 0}
            )
            for reply in _hop_replies(hop):
                if "rtt" not in reply:
                    entry["timeouts"] += 1
                    continue
                entry["rtts"].append(float(reply["rtt"]))
                address = reply.get("from")
                if address and address not in entry["addresses"]:
                    entry["addresses"].append(str(address))
                asn = reply.get("as") or reply.get("asn")
                if asn is not None and asn not in entry.setdefault("as_path", []):
                    entry["as_path"].append(asn)
    ordered = [hops[key] for key in sorted(hops)]
    if not ordered:
        raise ValueError("traceroute results contain no hops")
    normalized_hops = [
        {
            "hop": entry["hop"],
            "addresses": entry["addresses"],
            "asns": entry.get("as_path", []),
            "rtt_min_ms": round(min(entry["rtts"]), 3) if entry["rtts"] else None,
            "rtt_avg_ms": round(fmean(entry["rtts"]), 3) if entry["rtts"] else None,
            "rtt_max_ms": round(max(entry["rtts"]), 3) if entry["rtts"] else None,
            "timeouts": entry["timeouts"],
        }
        for entry in ordered
    ]
    first_loss_hop = next(
        (hop["hop"] for hop in normalized_hops if hop["timeouts"] > 0),
        None,
    )
    first_latency_increase_hop = _first_latency_increase(normalized_hops)
    data: dict[str, Any] = {
        "target": _target(results),
        "hops": normalized_hops,
        "hop_count": len(normalized_hops),
        "as_path": [asn for hop in normalized_hops for asn in hop["asns"]],
        "first_loss_hop": first_loss_hop,
        "first_latency_increase_hop": first_latency_increase_hop,
    }
    affected = sum(1 for hop in normalized_hops if hop["timeouts"] > 0)
    return data, _observed_at(results), len(results), affected


def _first_latency_increase(hops: Sequence[Mapping[str, Any]], factor: float = 2.0) -> int | None:
    previous: float | None = None
    for hop in hops:
        current = hop["rtt_avg_ms"]
        if current is None:
            continue
        if previous is not None and previous > 0 and current > previous * factor:
            return int(hop["hop"])
        previous = float(current)
    return None


def _normalize_dns(
    results: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], datetime, int, int]:
    answers: list[dict[str, Any]] = []
    response_times: list[float] = []
    failures = 0
    for result in results:
        if result.get("error") is not None:
            failures += 1
            continue
        payload = result.get("result")
        if not isinstance(payload, dict):
            failures += 1
            continue
        if "rt" in payload:
            response_times.append(float(payload["rt"]))
        for answer in payload.get("answers", []):
            if isinstance(answer, dict) and answer not in answers:
                answers.append(answer)
        if int(payload.get("ANCOUNT", 0)) == 0 and not payload.get("answers"):
            failures += 1
    data: dict[str, Any] = {
        "target": _target(results) or None,
        "resolved": failures < len(results),
        "answers": answers,
        "addresses": [
            str(answer["RDATA"]) if not isinstance(answer.get("RDATA"), list) else answer["RDATA"]
            for answer in answers
            if "RDATA" in answer
        ],
        "response_time_avg_ms": round(fmean(response_times), 3) if response_times else None,
        "probes_failed": failures,
    }
    return data, _observed_at(results), len(results), failures


_NORMALIZERS = {
    "ping": _normalize_ping,
    "traceroute": _normalize_traceroute,
    "dns": _normalize_dns,
}
