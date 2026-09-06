from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from relay.adapters.ripe_atlas import RIPEAtlasAdapter
from relay.agent.planner import DeterministicPlanner
from relay.domain.models import OperatingMode
from relay.network.simulator import NetworkSimulator
from relay.repositories.incidents import SQLiteIncidentRepository
from relay.services.incidents import IncidentService
from relay.tools.network_tools import build_registry


def _recorded(url: str) -> Any:
    now = datetime.now(UTC).timestamp()
    if "/latest/" in url:
        return [
            {
                "msm_id": 100,
                "prb_id": 1,
                "timestamp": now,
                "dst_addr": "192.0.2.80",
                "result": [{"rtt": 21.0}, {"rtt": 22.0}, {"rtt": 20.0}],
            },
            {
                "msm_id": 100,
                "prb_id": 2,
                "timestamp": now,
                "dst_addr": "192.0.2.80",
                "result": [{"x": "*"}, {"x": "*"}, {"rtt": 240.0}],
            },
        ]
    if "/probes/" in url:
        probe_id = int(url.rstrip("/").split("/")[-1])
        return {"id": probe_id, "country_code": "NL", "asn_v4": 64500 + probe_id}
    return {"id": 100, "type": "ping", "target_ip": "192.0.2.80"}


def evaluate() -> dict[str, Any]:
    adapter = RIPEAtlasAdapter(get_json=_recorded)
    with tempfile.TemporaryDirectory() as directory:
        service = IncidentService(
            SQLiteIncidentRepository(str(Path(directory) / "eval.db")),
            build_registry(NetworkSimulator()),
            DeterministicPlanner(),
            adapter_factories={"ripe-atlas": lambda _incident: adapter},
        )
        incident = service.create(
            "Recorded RIPE Atlas evaluation",
            "Evaluate a lossy public-measurement recording",
            "100",
            "192.0.2.80",
            "100",
            OperatingMode.OBSERVE,
            ["ripe-atlas"],
        )
        result = service.agent_run(incident.id)
    names = [call.tool_name for call in result.tool_calls]
    allowed = set(build_registry(adapter, include_writes=False).schemas())
    grounded = bool(
        result.conclusion
        and result.conclusion.kind == "ASSESSMENT"
        and "packet loss" in result.conclusion.summary.lower()
        and result.conclusion.evidence_ids
    )
    return {
        "dataset": "recorded-ripe-ping-loss",
        "tool_selection_valid": all(name in allowed for name in names),
        "selected_tools": names,
        "evidence_extracted": len(result.evidence) >= 3,
        "unsupported_operation_handled": any(
            evidence.status.value == "UNSUPPORTED" for evidence in result.evidence
        ),
        "conclusion_grounded": grounded,
        "read_only_safe": all(not call.state_changing for call in result.tool_calls),
        "assessment": result.conclusion.model_dump(mode="json") if result.conclusion else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the agent on recorded RIPE Atlas data")
    parser.add_argument("--output", default="recorded-live-evaluation-results.json")
    args = parser.parse_args()
    result = evaluate()
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
