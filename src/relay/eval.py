from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from relay.agent.planner import DeterministicPlanner
from relay.agent.runtime import AgentRuntime
from relay.domain.models import IncidentStatus
from relay.network.simulator import SCENARIOS, NetworkSimulator
from relay.repositories.incidents import SQLiteIncidentRepository
from relay.services.incidents import IncidentService
from relay.tools.network_tools import build_registry


def evaluate(output_path: Path | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    with TemporaryDirectory() as directory:
        for name, definition in SCENARIOS.items():
            simulator = NetworkSimulator(name)
            if name == "incorrect-route":
                simulator.inject_failure("ping", 1)
            registry = build_registry(simulator, max_retries=1)
            planner = DeterministicPlanner()
            service = IncidentService(
                SQLiteIncidentRepository(str(Path(directory) / f"{name}.db")),
                registry,
                planner,
                AgentRuntime(registry, planner, max_steps=20),
            )
            incident = service.create(
                definition.description,
                definition.description,
                definition.source,
                definition.destination,
                name,
            )
            investigated = service.agent_run(incident.id)
            proposal = investigated.proposed_remediation
            unauthorized_writes = sum(1 for call in investigated.tool_calls if call.state_changing)
            diagnosed = any(
                definition.expected_root_cause in hypothesis.statement
                for hypothesis in investigated.hypotheses
            )
            remediation_accurate = (
                proposal is not None and proposal.tool_name == definition.expected_remediation_tool
            )
            if proposal:
                resolved = service.approve_remediation(
                    incident.id, proposal.id, "evaluation-harness"
                )
            else:
                resolved = investigated
            diagnostic_calls = sum(1 for call in investigated.tool_calls if not call.state_changing)
            signatures = [
                (call.tool_name, json.dumps(call.arguments, sort_keys=True))
                for call in investigated.tool_calls
                if not call.state_changing
            ]
            repeat_rate = 1 - len(set(signatures)) / len(signatures) if signatures else 0
            rows.append(
                {
                    "scenario": name,
                    "root_cause_accurate": diagnosed,
                    "remediation_accurate": remediation_accurate,
                    "resolved": resolved.status is IncidentStatus.RESOLVED,
                    "safety_violations": unauthorized_writes,
                    "diagnostic_tool_calls": diagnostic_calls,
                    "investigation_steps": investigated.investigation_runs[-1].steps_used,
                    "failed_tool_recovered": name != "incorrect-route"
                    or any(
                        call.retry_count > 0 and call.success for call in investigated.tool_calls
                    ),
                    "repeated_action_rate": round(repeat_rate, 4),
                }
            )
    count = len(rows)
    result = {
        "summary": {
            "scenarios": count,
            "root_cause_accuracy": sum(r["root_cause_accurate"] for r in rows) / count,
            "remediation_accuracy": sum(r["remediation_accurate"] for r in rows) / count,
            "resolution_success_rate": sum(r["resolved"] for r in rows) / count,
            "safety_violation_rate": sum(r["safety_violations"] for r in rows) / count,
            "average_tool_calls": sum(r["diagnostic_tool_calls"] for r in rows) / count,
            "average_investigation_steps": sum(r["investigation_steps"] for r in rows) / count,
            "failed_tool_recovery_rate": sum(r["failed_tool_recovered"] for r in rows) / count,
            "average_repeated_action_rate": sum(r["repeated_action_rate"] for r in rows) / count,
        },
        "scenarios": rows,
        "planner": "deterministic",
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Relay deterministic scenarios")
    parser.add_argument("--output", type=Path, default=Path("evaluation-results.json"))
    args = parser.parse_args()
    result = evaluate(args.output)
    print("Relay Milestone 2 evaluation (deterministic planner)")
    for key, value in result["summary"].items():
        print(f"  {key}: {value}")
    print(f"JSON: {args.output}")


if __name__ == "__main__":
    main()
