from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import UUID

from relay.agent.planner import DeterministicPlanner
from relay.agent.runtime import AgentRuntime
from relay.network.simulator import SCENARIOS, NetworkSimulator
from relay.repositories.incidents import SQLiteIncidentRepository
from relay.services.incidents import IncidentService
from relay.tools.network_tools import build_registry


def service_for(database: str, scenario: str) -> IncidentService:
    simulator = NetworkSimulator(scenario)
    registry = build_registry(simulator)
    planner = DeterministicPlanner()
    return IncidentService(
        SQLiteIncidentRepository(database), registry, planner, AgentRuntime(registry, planner)
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="relay")
    parser.add_argument("--database", default="data/relay.db")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--scenario", choices=SCENARIOS, default="interface-disabled")
    for command in ("investigate", "show", "continue", "approve"):
        item = sub.add_parser(command)
        item.add_argument("incident_id", type=UUID)
        if command == "approve":
            item.add_argument("remediation_id", type=UUID)
            item.add_argument("--by", default="local-operator")
    args = parser.parse_args()
    database = str(Path(args.database))
    if args.command == "create":
        definition = SCENARIOS[args.scenario]
        service = service_for(database, args.scenario)
        incident = service.create(
            definition.description,
            definition.description,
            definition.source,
            definition.destination,
            args.scenario,
        )
    else:
        probe = SQLiteIncidentRepository(database)
        existing = probe.get(args.incident_id)
        if existing is None:
            parser.error(f"incident not found: {args.incident_id}")
        service = service_for(database, existing.scenario)
        if args.command == "investigate":
            incident = service.agent_run(args.incident_id)
        elif args.command == "continue":
            incident = service.agent_continue(args.incident_id)
        elif args.command == "approve":
            incident = service.approve_remediation(args.incident_id, args.remediation_id, args.by)
        else:
            incident = service.get(args.incident_id)
    print(json.dumps(incident.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
