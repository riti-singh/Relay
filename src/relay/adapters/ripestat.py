from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
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

RESOURCE_ARGUMENTS = ("resource", "prefix", "destination", "device_id", "hostname")
DEFAULT_BASE_URL = "https://stat.ripe.net/data"
DEFAULT_ALLOWED_HOSTS = frozenset({"stat.ripe.net"})


class RIPEstatConfigurationError(ValueError):
    """The configured RIPEstat base URL is not an allowlisted public https host."""


def validate_base_url(base_url: str, allowed_hosts: Iterable[str] = DEFAULT_ALLOWED_HOSTS) -> str:
    """Return the normalized base URL, or raise if it could reach anything but public RIPEstat."""
    allowed = {host.strip().lower() for host in allowed_hosts if host.strip()}
    if not allowed:
        raise RIPEstatConfigurationError("RIPEstat allowed hosts list must not be empty")
    parts = parse.urlsplit(base_url.strip())
    if parts.scheme != "https":
        raise RIPEstatConfigurationError(
            f"RIPEstat base URL must use https, got {parts.scheme or 'no scheme'!r}: {base_url!r}"
        )
    if parts.username is not None or parts.password is not None:
        raise RIPEstatConfigurationError("RIPEstat base URL must not contain credentials")
    if parts.query or parts.fragment:
        raise RIPEstatConfigurationError("RIPEstat base URL must not contain a query or fragment")
    host = (parts.hostname or "").lower()
    if host not in allowed:
        raise RIPEstatConfigurationError(
            f"RIPEstat host {host or '<missing>'!r} is not allowlisted; "
            f"allowed hosts: {', '.join(sorted(allowed))}"
        )
    if parts.port not in (None, 443):
        raise RIPEstatConfigurationError(f"RIPEstat base URL must use port 443, got {parts.port}")
    return parse.urlunsplit(("https", host, parts.path.rstrip("/"), "", ""))


class RIPEstatAdapter(NetworkAdapter):
    """Keyless read-only RIPEstat lookup: is a prefix globally visible in BGP and who originates it.

    Only public RIPEstat data calls are used, so the adapter can never mutate anything.
    """

    source_type = "ripestat"
    read_only = True
    capabilities = frozenset({AdapterCapability.ROUTES, AdapterCapability.BGP_VISIBILITY})

    def __init__(
        self,
        adapter_id: str = "ripestat",
        display_name: str = "RIPEstat BGP visibility",
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 5,
        freshness_seconds: int = 43200,
        recent_changes_hours: int = 2,
        source_app: str = "relay-noc",
        allowed_hosts: Iterable[str] = DEFAULT_ALLOWED_HOSTS,
    ) -> None:
        self.adapter_id, self.display_name = adapter_id, display_name
        self.allowed_hosts = frozenset(host.strip().lower() for host in allowed_hosts)
        self.base_url = validate_base_url(base_url, self.allowed_hosts)
        self.timeout_seconds, self.freshness_seconds = timeout_seconds, freshness_seconds
        self.recent_changes_hours, self.source_app = recent_changes_hours, source_app
        self.last_successful_observation: datetime | None = None

    def collect(
        self, operation: DiagnosticOperation, arguments: dict[str, Any]
    ) -> AdapterObservation:
        capability = OPERATION_CAPABILITY[operation]
        now = datetime.now(UTC)
        resource = self._resource(arguments)
        provenance = ObservationProvenance(
            source_type=self.source_type,
            adapter=self.adapter_id,
            resource_id=resource,
            collected_at=now,
            freshness=Freshness.UNAVAILABLE,
            query_identity=operation.value,
        )
        if capability not in self.capabilities:
            return AdapterObservation(
                status=ObservationStatus.UNSUPPORTED,
                provenance=provenance,
                message=(
                    f"{self.display_name} does not expose "
                    f"{capability.value.lower().replace('_', ' ')}"
                ),
            )
        if not resource:
            return AdapterObservation(
                status=ObservationStatus.FAILED,
                provenance=provenance,
                message="RIPEstat lookups require an IP or prefix resource",
            )
        status_url = self._url("routing-status", resource)
        overview_url = self._url("prefix-overview", resource)
        changes_url = self._url(
            "bgp-updates",
            resource,
            starttime=(now - timedelta(hours=self.recent_changes_hours)).strftime(
                "%Y-%m-%dT%H:%M:%S"
            ),
        )
        provenance.source_metadata = {
            "routing_status_url": status_url,
            "prefix_overview_url": overview_url,
            "bgp_updates_url": changes_url,
        }
        try:
            status_body = self._get(status_url)
            overview_body = self._get(overview_url)
            changes_body = self._get(changes_url)
            observed_at = self._observed_at(status_body)
            data = self._normalize(status_body["data"], overview_body["data"], changes_body["data"])
            provenance.observed_at = observed_at
            provenance.measurement = "ris-bgp"
            provenance.source_metadata["queried_at"] = status_body.get("time")
            is_stale = now - observed_at > timedelta(seconds=self.freshness_seconds)
            provenance.freshness = Freshness.STALE if is_stale else Freshness.FRESH
            self.last_successful_observation = now
            return AdapterObservation(
                status=ObservationStatus.STALE if is_stale else ObservationStatus.SUCCESS,
                data=data,
                provenance=provenance,
                message="RIPEstat data is older than the configured freshness threshold"
                if is_stale
                else None,
            )
        except error.HTTPError as exc:
            if 400 <= exc.code < 500:
                return AdapterObservation(
                    status=ObservationStatus.FAILED,
                    provenance=provenance,
                    message=f"RIPEstat rejected the query for {resource!r}: HTTP {exc.code}",
                )
            return AdapterObservation(
                status=ObservationStatus.UNAVAILABLE,
                provenance=provenance,
                message=f"RIPEstat unavailable: {exc}",
            )
        except (error.URLError, TimeoutError) as exc:
            return AdapterObservation(
                status=ObservationStatus.UNAVAILABLE,
                provenance=provenance,
                message=f"RIPEstat unavailable: {exc}",
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError, ValidationError) as exc:
            return AdapterObservation(
                status=ObservationStatus.FAILED,
                provenance=provenance,
                message=f"malformed RIPEstat response: {exc}",
            )

    def inventory(self) -> Inventory:
        return Inventory()

    def topology(self) -> NetworkTopology:
        return NetworkTopology(devices=[], links=[])

    def _url(self, data_call: str, resource: str, **params: str) -> str:
        query = parse.urlencode({"resource": resource, "sourceapp": self.source_app, **params})
        return f"{self.base_url}/{parse.quote(data_call, safe='')}/data.json?{query}"

    def _get(self, url: str) -> dict[str, Any]:
        if not url.startswith(f"{self.base_url}/"):
            raise RIPEstatConfigurationError(f"refusing request outside RIPEstat base: {url!r}")
        with request.urlopen(url, timeout=self.timeout_seconds) as response:
            body = json.loads(response.read())
        if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            raise ValueError("RIPEstat body must contain a data object")
        if body.get("status") not in (None, "ok"):
            raise ValueError(f"RIPEstat status {body.get('status')}: {body.get('messages')}")
        return body

    @staticmethod
    def _observed_at(body: dict[str, Any]) -> datetime:
        """RIS routing-status reflects a periodic dump; `query_time` is that dump's time."""
        raw = body.get("data", {}).get("query_time") or body["time"]
        observed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return observed if observed.tzinfo else observed.replace(tzinfo=UTC)

    @staticmethod
    def _normalize(
        status: dict[str, Any], overview: dict[str, Any], changes: dict[str, Any]
    ) -> dict[str, Any]:
        visibility = status.get("visibility") or {}
        peers_seeing = total_peers = 0
        for family in visibility.values():
            if isinstance(family, dict):
                peers_seeing += int(family.get("ris_peers_seeing") or 0)
                total_peers += int(family.get("total_ris_peers") or 0)
        origins: list[dict[str, Any]] = []
        seen: set[int] = set()
        for item in status.get("origins") or []:
            asn = int(item["origin"])
            if asn not in seen:
                seen.add(asn)
                origins.append({"asn": asn, "holder": None})
        for item in overview.get("asns") or []:
            asn = int(item["asn"])
            holder = item.get("holder")
            match = next((entry for entry in origins if entry["asn"] == asn), None)
            if match is None:
                origins.append({"asn": asn, "holder": holder})
                seen.add(asn)
            else:
                match["holder"] = holder
        updates = changes.get("updates") or []
        recent_changes = [
            {
                "timestamp": update.get("timestamp"),
                "type": update.get("type"),
                "target_prefix": (update.get("attrs") or {}).get("target_prefix"),
                "source_id": (update.get("attrs") or {}).get("source_id"),
                "path": (update.get("attrs") or {}).get("path"),
            }
            for update in updates[-20:]
        ]
        announcements = sum(1 for update in updates if update.get("type") == "A")
        withdrawals = sum(1 for update in updates if update.get("type") == "W")
        announced = bool(status.get("announced", overview.get("announced", False)))
        return {
            "resource": status.get("resource") or overview.get("resource"),
            "prefix": overview.get("resource") or status.get("resource"),
            "announced": announced,
            "globally_visible": announced and peers_seeing > 0,
            "origin_asns": [entry["asn"] for entry in origins],
            "origins": origins,
            "visibility": {
                "ris_peers_seeing": peers_seeing,
                "total_ris_peers": total_peers,
                "ratio": round(peers_seeing / total_peers, 3) if total_peers else 0.0,
                "by_family": visibility,
            },
            "first_seen": (status.get("first_seen") or {}).get("time"),
            "last_seen": (status.get("last_seen") or {}).get("time"),
            "less_specifics": status.get("less_specifics") or [],
            "more_specifics": status.get("more_specifics") or [],
            "recent_changes": {
                "window_start": changes.get("query_starttime"),
                "window_end": changes.get("query_endtime"),
                "announcements": announcements,
                "withdrawals": withdrawals,
                "updates": recent_changes,
            },
        }

    @staticmethod
    def _resource(arguments: dict[str, Any]) -> str | None:
        for key in RESOURCE_ARGUMENTS:
            value = arguments.get(key)
            if value:
                return str(value)
        return None
