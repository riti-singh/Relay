from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib import error, parse, request

from relay.adapters.base import DiagnosticOperation, NetworkAdapter
from relay.domain.models import (
    AdapterCapability,
    AdapterObservation,
    DataSourceClassification,
    Freshness,
    Inventory,
    NetworkDevice,
    NetworkLink,
    NetworkTopology,
    ObservationProvenance,
    ObservationStatus,
)

JSONGetter = Callable[[str], Any]


class RIPEAtlasAdapter(NetworkAdapter):
    """Read-only adapter for public RIPE Atlas measurement and probe data."""

    adapter_id = "ripe-atlas"
    display_name = "RIPE Atlas"
    source_type = "ripe-atlas"
    query_style = "measurement"
    classification = DataSourceClassification.LIVE
    read_only = True
    capabilities = frozenset(
        {
            AdapterCapability.REACHABILITY,
            AdapterCapability.LATENCY,
            AdapterCapability.PACKET_LOSS,
            AdapterCapability.PATH_TRACE,
            AdapterCapability.PATH_COMPARISON,
            AdapterCapability.PROBE_METADATA,
            AdapterCapability.INVENTORY,
            AdapterCapability.TOPOLOGY,
        }
    )

    def __init__(
        self,
        base_url: str = "https://atlas.ripe.net/api/v2",
        timeout_seconds: float = 10,
        freshness_seconds: int = 900,
        get_json: JSONGetter | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.freshness_seconds = freshness_seconds
        self._get_json = get_json or self._http_get_json
        self.last_successful_observation: datetime | None = None
        self._last_paths: list[dict[str, Any]] = []

    def collect(
        self, operation: DiagnosticOperation, arguments: dict[str, Any]
    ) -> AdapterObservation:
        now = datetime.now(UTC)
        measurement_id = str(arguments.get("measurement_id", ""))
        provenance = ObservationProvenance(
            source_type=self.source_type,
            adapter=self.adapter_id,
            resource_id=measurement_id or None,
            measurement_id=measurement_id or None,
            collected_at=now,
            freshness=Freshness.UNAVAILABLE,
            query_identity=f"{operation.value}:{measurement_id}",
        )
        if not measurement_id:
            return AdapterObservation(
                status=ObservationStatus.FAILED,
                provenance=provenance,
                message="measurement_id is required",
            )

        try:
            metadata = self._get_json(
                f"{self.base_url}/measurements/{parse.quote(measurement_id)}/"
            )
            measurement_type = str(metadata.get("type", ""))
            target = metadata.get("target_ip") or metadata.get("target")
            provenance.measurement_type = measurement_type or None
            provenance.measurement = measurement_type or None
            provenance.target = str(target) if target else None
            if operation is DiagnosticOperation.PROBE_METADATA:
                return self._probe_metadata(arguments, metadata, provenance, now)
            expected = (
                "traceroute"
                if operation
                in {
                    DiagnosticOperation.TRACEROUTE,
                    DiagnosticOperation.PATH_TRACE,
                    DiagnosticOperation.PATH_COMPARISON,
                    DiagnosticOperation.TOPOLOGY,
                }
                else "ping"
            )
            if measurement_type != expected:
                return AdapterObservation(
                    status=ObservationStatus.UNSUPPORTED,
                    provenance=provenance,
                    message=(
                        f"operation requires a {expected} measurement, "
                        f"got {measurement_type or 'unknown'}"
                    ),
                )
            results = self._results(measurement_id, arguments)
            data, observed_at = (
                self._normalize_traceroute(results, target)
                if expected == "traceroute"
                else self._normalize_ping(results, target, operation)
            )
            provenance.observed_at = observed_at
            stale = observed_at is None or now - observed_at > timedelta(
                seconds=self.freshness_seconds
            )
            provenance.freshness = Freshness.STALE if stale else Freshness.FRESH
            self.last_successful_observation = now
            status = ObservationStatus.STALE if stale else ObservationStatus.SUCCESS
            return AdapterObservation(
                status=status,
                data={
                    **data,
                    "measurement_id": measurement_id,
                    "measurement_type": measurement_type,
                },
                provenance=provenance,
                message="RIPE Atlas results exceed the configured freshness threshold"
                if stale
                else None,
            )
        except (error.URLError, TimeoutError) as exc:
            return AdapterObservation(
                status=ObservationStatus.UNAVAILABLE,
                provenance=provenance,
                message=f"RIPE Atlas unavailable: {exc}",
            )
        except (AttributeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return AdapterObservation(
                status=ObservationStatus.FAILED,
                provenance=provenance,
                message=f"malformed RIPE Atlas response: {exc}",
            )

    def measurement_metadata(self, measurement_id: str) -> dict[str, Any]:
        raw = self._get_json(f"{self.base_url}/measurements/{parse.quote(measurement_id)}/")
        return {
            "id": raw.get("id", measurement_id),
            "type": raw.get("type"),
            "description": raw.get("description"),
            "target": raw.get("target_ip") or raw.get("target"),
            "target_asn": raw.get("target_asn"),
            "is_oneoff": raw.get("is_oneoff"),
            "status": raw.get("status"),
            "creation_time": raw.get("creation_time"),
            "stop_time": raw.get("stop_time"),
        }

    def select_measurement(self, measurement_id: str) -> dict[str, Any]:
        metadata = self.measurement_metadata(measurement_id)
        measurement_type = metadata.get("type")
        common = {AdapterCapability.PROBE_METADATA, AdapterCapability.INVENTORY}
        if measurement_type == "ping":
            self.capabilities = frozenset(
                common
                | {
                    AdapterCapability.REACHABILITY,
                    AdapterCapability.LATENCY,
                    AdapterCapability.PACKET_LOSS,
                }
            )
        elif measurement_type == "traceroute":
            self.capabilities = frozenset(
                common
                | {
                    AdapterCapability.TOPOLOGY,
                    AdapterCapability.PATH_TRACE,
                    AdapterCapability.PATH_COMPARISON,
                }
            )
        else:
            raise ValueError(f"unsupported RIPE Atlas measurement type: {measurement_type}")
        return metadata

    def _results(self, measurement_id: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        query: dict[str, str] = {"format": "json"}
        probe_ids = arguments.get("probe_ids")
        if probe_ids:
            query["probe_ids"] = ",".join(str(item) for item in probe_ids)
        limit = int(arguments.get("limit", 500))
        raw = self._get_json(
            f"{self.base_url}/measurements/{parse.quote(measurement_id)}/latest/"
            f"?{parse.urlencode(query)}"
        )
        if not isinstance(raw, list):
            raise ValueError("results must be a list")
        return [item for item in raw[-limit:] if isinstance(item, dict)]

    @staticmethod
    def _observed(results: list[dict[str, Any]]) -> datetime | None:
        timestamps = [float(item["timestamp"]) for item in results if item.get("timestamp")]
        return datetime.fromtimestamp(max(timestamps), UTC) if timestamps else None

    def _normalize_ping(
        self, results: list[dict[str, Any]], target: object, operation: DiagnosticOperation
    ) -> tuple[dict[str, Any], datetime | None]:
        probes: list[dict[str, Any]] = []
        for item in results:
            sent = len(item.get("result", [])) or int(item.get("sent", 0))
            received = sum(
                1 for reply in item.get("result", []) if isinstance(reply, dict) and "rtt" in reply
            )
            if not item.get("result") and item.get("rcvd") is not None:
                received = int(item["rcvd"])
            loss = 100.0 if sent == 0 else round((sent - received) * 100 / sent, 2)
            rtts = [
                float(reply["rtt"])
                for reply in item.get("result", [])
                if isinstance(reply, dict) and "rtt" in reply
            ]
            probes.append(
                {
                    "probe_id": item.get("prb_id"),
                    "source_address": item.get("src_addr"),
                    "target": item.get("dst_addr") or target,
                    "sent": sent,
                    "received": received,
                    "packet_loss_percent": loss,
                    "reachable": received > 0,
                    "min_rtt_ms": min(rtts) if rtts else item.get("min"),
                    "avg_rtt_ms": round(sum(rtts) / len(rtts), 3) if rtts else item.get("avg"),
                    "max_rtt_ms": max(rtts) if rtts else item.get("max"),
                    "observed_at": datetime.fromtimestamp(float(item["timestamp"]), UTC).isoformat()
                    if item.get("timestamp")
                    else None,
                }
            )
        reachable = sum(bool(item["reachable"]) for item in probes)
        losses = [float(item["packet_loss_percent"]) for item in probes]
        latencies = [float(item["avg_rtt_ms"]) for item in probes if item["avg_rtt_ms"] is not None]
        summary = {
            "probe_count": len(probes),
            "reachable_probe_count": reachable,
            "unreachable_probe_count": len(probes) - reachable,
            "reachability_percent": round(reachable * 100 / len(probes), 2) if probes else 0,
            "average_packet_loss_percent": round(sum(losses) / len(losses), 2) if losses else None,
            "median_rtt_ms": sorted(latencies)[len(latencies) // 2] if latencies else None,
            "probes": probes,
        }
        if operation is DiagnosticOperation.PING:
            summary["reachable"] = reachable > 0
        return summary, self._observed(results)

    def _normalize_traceroute(
        self, results: list[dict[str, Any]], target: object
    ) -> tuple[dict[str, Any], datetime | None]:
        paths: list[dict[str, Any]] = []
        for item in results:
            hops: list[dict[str, Any]] = []
            for hop in item.get("result", []):
                replies = hop.get("result", []) if isinstance(hop, dict) else []
                addresses = [
                    reply.get("from")
                    for reply in replies
                    if isinstance(reply, dict) and reply.get("from")
                ]
                hops.append({"hop": hop.get("hop"), "addresses": list(dict.fromkeys(addresses))})
            paths.append(
                {
                    "probe_id": item.get("prb_id"),
                    "target": item.get("dst_addr") or target,
                    "hops": hops,
                    "observed_at": datetime.fromtimestamp(float(item["timestamp"]), UTC).isoformat()
                    if item.get("timestamp")
                    else None,
                }
            )
        self._last_paths = paths
        signatures: dict[str, list[object]] = {}
        for path in paths:
            signature = " > ".join(
                str(hop["addresses"][0]) if hop["addresses"] else "unknown" for hop in path["hops"]
            )
            signatures.setdefault(signature, []).append(path["probe_id"])
        return {
            "probe_count": len(paths),
            "paths": paths,
            "path_groups": [
                {"signature": signature, "probe_ids": ids, "probe_count": len(ids)}
                for signature, ids in signatures.items()
            ],
            "distinct_path_count": len(signatures),
        }, self._observed(results)

    def _probe_metadata(
        self,
        arguments: dict[str, Any],
        metadata: dict[str, Any],
        provenance: ObservationProvenance,
        now: datetime,
    ) -> AdapterObservation:
        probe_ids = arguments.get("probe_ids") or []
        probes = []
        for probe_id in probe_ids:
            raw = self._get_json(f"{self.base_url}/probes/{int(probe_id)}/")
            probes.append(
                {
                    "probe_id": raw.get("id", int(probe_id)),
                    "country_code": raw.get("country_code"),
                    "asn_v4": raw.get("asn_v4"),
                    "asn_v6": raw.get("asn_v6"),
                    "address_v4": raw.get("address_v4"),
                    "address_v6": raw.get("address_v6"),
                    "status_id": raw.get("status", {}).get("id")
                    if isinstance(raw.get("status"), dict)
                    else raw.get("status"),
                }
            )
        provenance.observed_at = now
        provenance.freshness = Freshness.FRESH
        provenance.measurement_type = str(metadata.get("type", "")) or None
        self.last_successful_observation = now
        return AdapterObservation(
            status=ObservationStatus.SUCCESS,
            data={"measurement_id": str(arguments["measurement_id"]), "probes": probes},
            provenance=provenance,
        )

    def inventory(self) -> Inventory:
        return Inventory()

    def topology(self) -> NetworkTopology:
        devices: list[NetworkDevice] = []
        links: list[NetworkLink] = []
        for path in self._last_paths:
            previous = f"probe-{path['probe_id']}"
            devices.append(NetworkDevice(id=previous, name=previous, kind="probe", interfaces=[]))
            for index, hop in enumerate(path["hops"], 1):
                address = hop["addresses"][0] if hop["addresses"] else "unknown"
                current = f"{path['probe_id']}-hop-{index}-{address}"
                devices.append(
                    NetworkDevice(id=current, name=str(address), kind="hop", interfaces=[])
                )
                links.append(
                    NetworkLink(device_a=previous, interface_a="", device_b=current, interface_b="")
                )
                previous = current
        unique = {item.id: item for item in devices}
        return NetworkTopology(devices=list(unique.values()), links=links)

    def _http_get_json(self, url: str) -> Any:
        req = request.Request(
            url, headers={"Accept": "application/json", "User-Agent": "Relay/0.1"}
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                return json.loads(response.read())
        except error.HTTPError as exc:
            if exc.code == 429:
                raise TimeoutError("RIPE Atlas rate limit exceeded") from exc
            raise
