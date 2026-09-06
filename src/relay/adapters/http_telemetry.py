from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar
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


class HTTPTelemetryAdapter(NetworkAdapter):
    """Read-only structured HTTP telemetry integration; no write or command endpoint exists."""

    source_type = "http-telemetry"
    read_only = True

    def __init__(
        self,
        adapter_id: str,
        display_name: str,
        base_url: str,
        dataset: str,
        capabilities: frozenset[AdapterCapability],
        timeout_seconds: float = 3,
        freshness_seconds: int = 60,
    ) -> None:
        self.adapter_id, self.display_name = adapter_id, display_name
        self.base_url, self.dataset = base_url.rstrip("/"), dataset
        self.capabilities = capabilities
        self.timeout_seconds, self.freshness_seconds = timeout_seconds, freshness_seconds
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
        if capability not in self.capabilities:
            return AdapterObservation(
                status=ObservationStatus.UNSUPPORTED,
                provenance=provenance,
                message=(
                    f"{self.display_name} does not expose "
                    f"{capability.value.lower().replace('_', ' ')}"
                ),
            )
        query = parse.urlencode({key: str(value) for key, value in arguments.items()})
        url = (
            f"{self.base_url}/v1/datasets/{parse.quote(self.dataset)}"
            f"/observations/{operation.value}"
        )
        if query:
            url += f"?{query}"
        try:
            with request.urlopen(url, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
            observed_at = datetime.fromisoformat(str(body["observed_at"]).replace("Z", "+00:00"))
            data = body["data"]
            if not isinstance(data, dict):
                raise ValueError("data must be an object")
            provenance.observed_at = observed_at
            provenance.source_metadata = {"dataset": self.dataset}
            is_stale = now - observed_at > timedelta(seconds=self.freshness_seconds)
            provenance.freshness = Freshness.STALE if is_stale else Freshness.FRESH
            self.last_successful_observation = now
            return AdapterObservation(
                status=ObservationStatus.STALE if is_stale else ObservationStatus.SUCCESS,
                data=data,
                provenance=provenance,
                message="Telemetry is older than the configured freshness threshold"
                if is_stale
                else None,
            )
        except (error.URLError, TimeoutError) as exc:
            return AdapterObservation(
                status=ObservationStatus.UNAVAILABLE,
                provenance=provenance,
                message=f"telemetry source unavailable: {exc}",
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError, ValidationError) as exc:
            return AdapterObservation(
                status=ObservationStatus.FAILED,
                provenance=provenance,
                message=f"malformed telemetry response: {exc}",
            )

    def inventory(self) -> Inventory:
        return self._typed_get("inventory", Inventory)

    def topology(self) -> NetworkTopology:
        return self._typed_get("topology", NetworkTopology)

    def _typed_get(self, resource: str, model: type[_ModelT]) -> _ModelT:
        url = f"{self.base_url}/v1/datasets/{parse.quote(self.dataset)}/{resource}"
        try:
            with request.urlopen(url, timeout=self.timeout_seconds) as response:
                return model.model_validate_json(response.read())
        except (error.URLError, TimeoutError, ValidationError, ValueError) as exc:
            raise RuntimeError(f"telemetry {resource} unavailable: {exc}") from exc

    @staticmethod
    def _resource(arguments: dict[str, Any]) -> str | None:
        if "device_id" in arguments:
            return str(arguments["device_id"])
        if "device_a" in arguments:
            return f"{arguments['device_a']}--{arguments['device_b']}"
        return str(arguments.get("destination") or arguments.get("hostname") or "") or None


_ModelT = TypeVar("_ModelT", Inventory, NetworkTopology)
