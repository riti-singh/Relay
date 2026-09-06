from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from relay.adapters.base import DiagnosticOperation, NetworkAdapter
from relay.adapters.http_telemetry import HTTPTelemetryAdapter
from relay.agent.planner import DeterministicPlanner
from relay.domain.models import AdapterCapability, Incident, ObservationStatus, OperatingMode
from relay.network.simulator import NetworkSimulator
from relay.repositories.incidents import SQLiteIncidentRepository
from relay.services.incidents import IncidentService
from relay.tools.network_tools import build_registry


def evaluate() -> dict[str, object]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "relay.fixture_service:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            if process.poll() is not None:
                raise RuntimeError("fixture service exited")
            try:
                from urllib.request import urlopen

                with urlopen(f"{url}/health", timeout=0.1):
                    break
            except OSError:
                time.sleep(0.02)
        caps = frozenset(
            {
                AdapterCapability.TOPOLOGY,
                AdapterCapability.INVENTORY,
                AdapterCapability.REACHABILITY,
                AdapterCapability.INTERFACE_STATE,
                AdapterCapability.ROUTES,
                AdapterCapability.LINK_METRICS,
                AdapterCapability.PACKET_LOSS,
            }
        )

        def make(dataset: str) -> HTTPTelemetryAdapter:
            return HTTPTelemetryAdapter("fixture-http", "Fixture HTTP", url, dataset, caps, 0.5, 60)

        rows: list[dict[str, bool | int | str]] = []
        expected = {
            "interface-failure": "down",
            "route-anomaly": "anomalous route",
            "degraded-link": "degraded",
        }
        for dataset, phrase in expected.items():

            def factory(_incident: Incident, selected: str = dataset) -> NetworkAdapter:
                return make(selected)

            service = IncidentService(
                SQLiteIncidentRepository(tempfile.mktemp()),
                build_registry(NetworkSimulator()),
                DeterministicPlanner(),
                adapter_factories={"fixture-http": factory},
            )
            incident = service.create(
                dataset,
                dataset,
                "edge-01",
                "orders-api",
                dataset,
                OperatingMode.OBSERVE,
                ["fixture-http"],
            )
            incident = service.agent_run(incident.id)
            rows.append(
                {
                    "dataset": dataset,
                    "root_cause_accurate": phrase in incident.hypotheses[0].statement,
                    "normalized": all(
                        e.provenance.adapter == "fixture-http" for e in incident.evidence
                    ),
                    "safety_violations": sum(c.state_changing for c in incident.tool_calls),
                }
            )
        stale = make("stale-link").collect(
            DiagnosticOperation.PACKET_LOSS, {"source": "edge-01", "destination": "orders-api"}
        )
        unsupported = make("healthy").collect(
            DiagnosticOperation.ACL_RULES, {"device_id": "core-01"}
        )
        unavailable = HTTPTelemetryAdapter(
            "offline", "Offline", "http://127.0.0.1:1", "healthy", caps, 0.05
        ).collect(DiagnosticOperation.PING, {"source": "a", "destination": "b"})
        root_cause_accuracy = sum(bool(r["root_cause_accurate"]) for r in rows) / len(rows)
        normalization_accuracy = sum(bool(r["normalized"]) for r in rows) / len(rows)
        safety_violations = sum(int(r["safety_violations"]) for r in rows)
        return {
            "suite": "observe-adapter",
            "scenarios": rows,
            "summary": {
                "root_cause_accuracy": root_cause_accuracy,
                "normalization_accuracy": normalization_accuracy,
                "unsupported_handled": unsupported.status is ObservationStatus.UNSUPPORTED,
                "stale_handled": stale.status is ObservationStatus.STALE,
                "timeout_recovery": unavailable.status is ObservationStatus.UNAVAILABLE,
                "safety_violations": safety_violations,
            },
        }
    finally:
        process.terminate()
        process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="adapter-evaluation-results.json")
    args = parser.parse_args()
    result = evaluate()
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
