# Relay — Agentic Network Incident Response

Relay is a backend foundation for investigating and safely remediating network incidents. It models an incident as a durable aggregate, exposes deterministic diagnostic tools, records structured evidence, and enforces a human approval boundary before any network mutation.

Milestone 1 deliberately uses a deterministic planner and simulator. It proves the workflow and domain boundaries without presenting scripted behavior as AI or requiring an external model.

## Architecture

```text
FastAPI routes
    │
IncidentService ── InvestigationPlanner (deterministic today)
    │                         │
SQLite repository       planned typed calls
    │                         │
incident aggregate      ToolRegistry ── NetworkSimulator
```

The code is organized by responsibility:

- `api`: transport schemas, routes, and dependency composition
- `domain`: typed incident, topology, evidence, hypothesis, remediation, and run models
- `services`: use cases and state transitions, independent of FastAPI
- `repositories`: parameterized SQLite persistence
- `network`: deterministic graph-based topology and connectivity behavior
- `tools`: typed inputs, registry, diagnostics, and guarded mutation
- `agent`: replaceable investigation-planner interface and current deterministic implementation

SQLite stores each incident aggregate as validated JSON alongside queryable identity, status, and timestamps. This keeps the first schema compact while persisting plans, runs, calls, evidence, hypotheses, remediation, approval, and verification as one consistent unit.

## Current capabilities

- Create, list, and inspect incidents.
- Inspect a five-device topology spanning two branches, two core routers, and a service node.
- Run typed `ping`, `traceroute`, topology, interface, route, log, and configuration tools.
- Record each call and successful observation as linked evidence.
- Diagnose the seeded `branch-03` failure, form a confidence-scored hypothesis, and propose remediation.
- Stop in `AWAITING_APPROVAL` without changing network state.
- After explicit approval, enable the failed interface and verify recovery with ping and traceroute.
- Persist the full incident and investigation history across application restarts.

## Seeded incident lifecycle

The simulator starts with `core-router-02/eth1` administratively disabled. That interface terminates the `branch-03` uplink, so `branch-03` cannot reach `payments-api`; `branch-01` remains a healthy control path.

The deterministic planner does not receive the root cause as an answer. It requests topology, ping, traceroute, source routes, suspect interface state, logs, and configuration through the same typed tool boundary available to future planners. The evidence supports a hypothesis that the disabled interface isolates the branch. Relay proposes enabling it, pauses, then executes and verifies only after approval.

State progression:

```text
OPEN → INVESTIGATING → AWAITING_APPROVAL → REMEDIATING → VERIFYING → RESOLVED
```

Invalid transitions are rejected explicitly.

## Safety model

Diagnostic tools are read-only. `set_interface_admin_state` is marked state-changing and the central registry refuses to execute it unless the caller supplies `ApprovalState.APPROVED`. The service sets that value only through the approval use case. Tests prove both that an unapproved call raises an approval error and that simulator state remains unchanged.

Only explicit operational artifacts are retained: plans, tool inputs/results, evidence, observations, hypotheses, confidence, decisions, and verification. Relay does not persist or expose hidden chain-of-thought.

## Running Relay

### Docker Compose (recommended)

```bash
docker compose up --build
```

The API is available at `http://localhost:8000`; interactive OpenAPI documentation is at `http://localhost:8000/docs`. The named `relay-data` volume preserves SQLite data when the container restarts. Simulator state is intentionally re-seeded on process startup for Milestone 1, so approved topology mutations do not survive a process restart; incident history does.

### Local Python 3.12+

```bash
make install
make run
```

Copy `.env.example` to `.env` to override the default database path if needed.

## Complete API workflow

Create the seeded scenario:

```bash
curl -sS -X POST http://localhost:8000/incidents \
  -H 'content-type: application/json' \
  -d '{
    "title": "Branch connectivity failure",
    "description": "Users at branch-03 cannot reach the payments API.",
    "source_device": "branch-03",
    "destination_device": "payments-api"
  }'
```

Copy the returned `id`, then inspect, investigate, review evidence, approve, and verify:

```bash
export INCIDENT_ID='<returned-id>'

curl -sS http://localhost:8000/incidents/$INCIDENT_ID
curl -sS -X POST http://localhost:8000/incidents/$INCIDENT_ID/investigate
curl -sS http://localhost:8000/incidents/$INCIDENT_ID/evidence
curl -sS -X POST http://localhost:8000/incidents/$INCIDENT_ID/approve-remediation
curl -sS http://localhost:8000/incidents/$INCIDENT_ID
```

Additional endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness check |
| GET | `/incidents` | List persisted incidents |
| GET | `/network/topology` | Inspect current simulator state |

Incident responses include current status, the explicit plan, investigation runs, tool calls, evidence, hypotheses, remediation proposal, approval state, and verification result.

## Tool system and simulator

Every tool owns a Pydantic input type and produces a common typed result. The registry handles lookup, validation, deterministic execution, error normalization, and the mutation approval guard. Invalid devices/interfaces and malformed inputs return useful failures instead of silently succeeding.

The simulator is a small graph. A link is traversable only when both attached interfaces are administratively and operationally up. Ping uses graph reachability and accumulated link latency; traceroute returns the deterministic path or the furthest reachable boundary. The model also provides routes, logs, and configuration used as corroborating evidence.

## Tests and quality checks

```bash
make test
make lint
make typecheck
# or all three
make check
```

The suite covers simulator topology and failures, ping/traceroute paths, typed registry behavior, invalid inputs, state transitions, the approval guard, seeded diagnosis, remediation, recovery verification, persistence after repository reopen, and the complete HTTP workflow.

Milestone 1 was verified locally with Python 3.12.14: 14 tests passed with 95% statement coverage, Ruff lint/format checks passed, strict mypy passed, and the live Uvicorn workflow reached `RESOLVED`. Docker Compose could not be executed on the development host because Docker was unavailable.

## Known limitations

- The planner handles the seeded scenario and is not a general reasoning system.
- Simulator mutations are in memory and reset on application restart.
- SQLite stores aggregates as JSON; future cross-incident analytics may warrant normalized event tables.
- Approval is an API action without identity, roles, audit signatures, or rejection flow yet.
- Execution is synchronous and single-process; there is no job queue or distributed locking.

## Roadmap

- LLM-backed planner behind the existing planner interface
- React/TypeScript frontend and topology visualization
- Streaming investigation timeline
- Additional deterministic and stochastic failure scenarios
- Evaluation harness for diagnosis and remediation outcomes
- Retries and tool-failure recovery
- Confidence calibration
- Multi-agent and specialist-agent experiments
- Production observability and tracing
- Authenticated, role-aware approvals and durable simulator/device adapters
