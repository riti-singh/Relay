# Relay

> Relay is a live agent investigation platform: one agent runtime performs evidence-backed work against interchangeable network data sources.

Relay combines an incident-isolated deterministic network laboratory, read-only external telemetry, durable agent runs, a replayable event stream, and an interactive NOC console. Every structured plan, tool call, observation, hypothesis revision, approval, write, and recovery check is stored and visible; hidden model reasoning is not.

## Problem and product workflow

Network incidents are diagnosed through reachability tests, path inspection, configuration checks, and human handoffs. An opaque AI answer is not operationally useful. Relay makes the investigation legible and keeps changes behind an exact-action approval boundary.

```mermaid
flowchart LR
 A[Inject incident] --> B[Bounded investigation]
 B --> C[Diagnostic tools]
 C --> D[Evidence + hypotheses]
 D --> E[Root cause]
 E --> F{Human approval}
 F -->|Reject| C
 F -->|Approve exact action| G[Remediate]
 G --> H[Verify]
 H -->|Failed| C
 H -->|Passed| I[Resolved]
```

The console has real Overview, Incidents, Topology, Agent Runs, and Evaluations routes. The incident workspace combines the evidence-aware graph, chronological agent actions, expandable results, hypothesis history, approval controls, and verification state.

## Screenshots

These are captured from the running simulator-backed application.

| Guided Home | Active investigation |
| --- | --- |
| ![Relay guided Home](docs/screenshots/home.png) | ![Relay investigation](docs/screenshots/investigation.jpg) |

| Human approval | Evaluations |
| --- | --- |
| ![Exact-action approval](docs/screenshots/approval.jpg) | ![Evaluation dashboard](docs/screenshots/evaluations.jpg) |

## Architecture: one agent runtime, interchangeable sources

```mermaid
flowchart TB
 RUNTIME[AgentRuntime] --> REGISTRY[Capability-driven typed tool registry]
 REGISTRY --> ADAPTER[NetworkAdapter]
 ADAPTER --> LAB[LAB · SIMULATED]
 ADAPTER --> RIPE[RIPE Atlas · LIVE]
 ADAPTER --> HTTP[Fixture HTTP · DEMO]
 ADAPTER -. same contract .-> FUTURE[Prometheus / OTel / SNMP / cloud]
 RIPE --> INTERNET[Live public Internet]
 RUNTIME --> STATE[(Evidence · hypotheses · assessments · events · comments)]
```

- `src/relay/domain`: incident, topology, evidence, hypothesis, run, approval, and verification models.
- `src/relay/network`: deterministic topology and six injected failures.
- `src/relay/adapters`: provider-neutral adapter contract, simulator and HTTP implementations, capabilities, and optional source composition.
- `src/relay/tools`: validated tools with risk, retries, and approval enforcement.
- `src/relay/agent`: structured planner abstraction and bounded runtime.
- `src/relay/services`: orchestration, persistence, remediation, and verification.
- `frontend`: Vite, React, TypeScript, React Router, Cytoscape, and Vitest.

## Agent runtime and tools

The runtime receives only a bounded `InvestigationContext`, available tool schemas, prior evidence, hypotheses, and tool results. It has no RIPE Atlas, fixture, or scenario branches. The registry is constructed from adapter capabilities, so unsupported operations are absent rather than simulated. A durable run records every decision, typed call, observation, hypothesis revision, assessment, and operator comment.

Operational events are monotonically sequenced within the persisted incident aggregate. The stream includes run lifecycle, decisions, tool start/completion/failure, evidence, hypothesis revisions, remediation, approval, verification, cancellation, and completion. `GET /incidents/{incident_id}/runs/{run_id}/events` replays with `Last-Event-ID` or `after=<sequence>` and then follows new events over SSE. The payload contains structured operational facts—not hidden chain-of-thought or fake token streaming.

`POST /incidents/{incident_id}/runs/{run_id}/cancel` requests cooperative cancellation. Relay checks the request between agent steps, never interrupts an in-flight write, persists the cancellation, and keeps remediation idempotency and exact-action approval intact.

Deterministic mode needs no external service. AI Agent mode uses an OpenAI-compatible Responses API adapter when configured; credentials stay backend-only and the UI disables this mode when unavailable.

Writes cannot execute without approval. A remediation stores the exact tool and arguments. Approval records a SHA-256 fingerprint over the incident, remediation, tool, and canonical arguments; Relay recomputes it immediately before execution. The UI never sends arbitrary tool calls.

## LAB and OBSERVE modes

`LAB` investigates an incident-isolated deterministic simulator. Its existing six scenarios, exact-action approval, guarded remediation, verification, and evaluation behavior are preserved.

`OBSERVE` investigates DEMO or LIVE telemetry through the same `AgentRuntime`, evidence model, hypotheses, and run lifecycle. Its registry contains no write tools. Approval and remediation endpoints independently reject OBSERVE incidents and append an `OBSERVE_WRITE_REJECTED` audit event. There is no shell, arbitrary-command, or hidden production-write path.

The operating mode and data-source IDs are persisted on the incident and every agent run, included in operational events, and displayed in the console.

## Adapter and capability model

`NetworkAdapter` is the provider boundary for identity, classification, read-only state, health, freshness policy, inventory/topology, capabilities, and diagnostic collection. Its finite operations include topology, reachability, latency, packet loss, path trace/comparison, interface state, routes, DNS, service connectivity, policy, link metrics, configuration, recent changes, and probe metadata.

| Source | Classification | Read only | Capabilities |
| --- | --- | --- | --- |
| Relay Lab | SIMULATED / LAB | No; writes require exact approval | topology, inventory, reachability, latency, loss, paths, interfaces, routes, DNS, service, policy, links, configuration, changes |
| RIPE Atlas | LIVE | Yes | reachability, latency, packet loss, path trace, path comparison, probe metadata, observed path topology |
| Fixture HTTP | DEMO | Yes | topology, inventory, reachability/path, interfaces, routes, link metrics, packet loss |

Adapters declare `AdapterCapability` values. Queries return `SUCCESS`, `UNSUPPORTED`, `UNAVAILABLE`, `STALE`, or `FAILED`; Relay records missing observations explicitly and never fabricates an answer. `CompositeNetworkAdapter` provides a small ordered multi-source boundary without introducing a distributed data platform.

## Inventory, provenance, and freshness

`GET /inventory?source_id=...` returns vendor-neutral devices, interfaces, services, and links with stable IDs, optional management metadata, labels, status, telemetry source, and last-observed time. `GET /integrations` lists connection state, read-only status, capabilities, and last observation.

Every evidence item records provider, adapter, resource and measurement IDs, probe ID where applicable, target, measurement type, source observation time, collection time, freshness, query identity, tool-call ID, run ID, and only source-supplied ASN/country metadata. Stale values remain visible but reduce assessment confidence. Unavailable means the source could not answer, not that the tested condition was false.

## Live RIPE Atlas workflow

1. Open **Investigations** and choose **RIPE Atlas — LIVE PUBLIC INTERNET**.
2. Enter a public ping or traceroute measurement ID. Relay loads current metadata from the official public REST API.
3. Start the investigation. The normal `AgentRuntime` selects only registered RIPE tools and persists real observations as evidence.
4. Review the activity stream and the evidence-backed **ASSESSMENT**. Relay does not claim observational telemetry is ground truth.
5. Add a comment, annotate evidence or a hypothesis through the API, or request a follow-up such as “Check whether affected probes share an ASN.”

RIPE Atlas failures, malformed responses, timeouts, and rate limiting are surfaced truthfully. Runtime never falls back to fixture data. The adapter is read-only and exposes no measurement-creation or mutation call.

## Network simulator

Relay models branch and core routers, a service, interfaces, routes, ACLs, configuration baselines, DNS, latency, and packet loss. Every incident receives its own simulator session, so reads and writes cannot leak across incidents. After service reconstruction, Relay rebuilds the scenario and replays only successfully completed, approved writes. The simulator implements the same adapter contract as external sources, while writes remain simulator-only.

## Guided onboarding and demo

The Home route explains the product, investigation modes, approval boundary, verification, and primary product areas. A dismissible first-run checklist is stored in the browser and can be rediscovered from Home. Concise page introductions, accessible info tooltips, staged incident progression, and action-oriented empty states keep the technical depth available without requiring the README.

1. Select **Start an investigation** on Home.
2. Inject one of the six simulated failures.
3. Choose **Deterministic** for reproducible execution or **AI Agent** when configured.
4. Watch durable events add decisions, tool calls, evidence, and hypotheses live.
5. Inspect the exact tool, affected resource, and arguments; approve the fingerprinted action.
6. Watch scenario-relevant verification prove recovery.
7. Replay the execution from **Agent Runs**.

## Example investigation

```text
Capture bounded topology
Test IP reachability                       packet loss: 100%
Locate path failure                       stopped after branch-03
Inspect source route                      next hop: core-router-02
Inspect branch uplink                     eth1 admin_up=false
Test application service                  unreachable
Test service DNS                          payments-api
Inspect traffic policy                    no active deny
Inspect link health                       nominal
Measure packet loss                       100%
Check configuration drift                 mismatch found
Evidence supports root-cause hypothesis   confidence: 98% (heuristic)
Propose evidence-backed remediation       set_interface_admin_state(...)
```

Relay pauses in `AWAITING_APPROVAL`. Once the exact action is approved, it enables the interface, verifies ping and traceroute, and only then marks the incident `RESOLVED`.

## Evaluation

`evaluation-results.json` is generated by the harness, not hand-authored. Current deterministic results across all six scenarios are 100% root-cause accuracy, 100% remediation accuracy, 100% resolution success, 0% safety violations, 11 average diagnostic calls, 13 average steps, and 100% failed-tool recovery.

## Run with Docker

```bash
docker compose up --build
```

- Console: <http://localhost:5173>
- API: <http://localhost:8000>
- OpenAPI: <http://localhost:8000/docs>

An empty database receives three real simulator-backed examples (open, awaiting approval, resolved). Set `RELAY_SEED_DEMO_DATA=false` to disable this.

## Local development and tests

Python 3.12 and Node 22 with pnpm are recommended.

```bash
make install             # backend dependencies
make run                 # backend hot reload
make frontend-install
make frontend-run        # frontend hot reload

make check               # backend lint, format, types, tests
make eval
make frontend-test
make frontend-build
cd frontend && pnpm lint
```

Provider settings are documented in `.env.example`. The integration suite exercises the real simulator → investigation → approval → remediation → verification path. Frontend tests cover route chrome, topology ingestion, incident creation, expandable tool presentation, verification, errors, and evaluations.

## Demo

1. Open **Home**, then select **Start an investigation** and inject **Interface Disabled**.
2. Choose **Deterministic** and start the investigation.
3. Expand tool calls and inspect evidence-linked topology and hypotheses.
4. Review and approve the exact remediation.
5. Watch recovery checks complete before `RESOLVED`.

### Local external-telemetry demo

Run `docker compose up --build`; this starts Relay plus a separate fixture telemetry HTTP service on port 8001.

1. Open **Incidents**, select **OBSERVE**, and choose a local structured HTTP dataset.
2. Choose **External interface failure**, **External route anomaly**, or **External degraded link**.
3. Start the investigation and watch the same runtime query external telemetry.
4. Inspect evidence provider, resource, source timestamp, and freshness.
5. Review the root-cause assessment and read-only explanation. Approval and remediation controls are unavailable.

The fixture service also has healthy and stale-link datasets. It speaks the external HTTP contract and does not read simulator state.

## Adding a telemetry adapter

Implement `NetworkAdapter` under `src/relay/adapters`, declare only the capabilities the provider truly supports, and normalize every result into `AdapterObservation` with provenance and a source timestamp. Implement vendor-neutral inventory and topology, register a factory by source ID, and build its registry with `include_writes=False`. `AgentRuntime` needs no provider-specific changes: it receives the same tool schemas and normalized evidence for every adapter.

Add contract, timeout, malformed-response, freshness, and safety cases to the separate adapter evaluation:

```bash
make eval          # six deterministic LAB scenarios
make adapter-eval  # read-only HTTP fixture telemetry
make recorded-live-eval # agent behavior on recorded RIPE responses; no Internet required
```

## Known limitations and roadmap

- Execution uses FastAPI in-process background tasks rather than an external worker queue; a process crash can leave a run marked `RUNNING` for operator inspection.
- SSE is backed by persisted aggregate events and local follow loops; horizontal fan-out would require a shared notification mechanism.
- Simulator reconstruction replays approved writes; it does not preserve transient counters or injected one-shot tool failures.
- The deterministic planner remains intentionally reproducible; a configured AI planner can choose among the same bounded schemas.
- Full workflow coverage is API integration plus component tests; Playwright is intentionally not added yet.
- Prometheus is intentionally deferred; the strengthened source contract is its extension point.
- OBSERVE deliberately cannot remediate. Completion is an assessment, not proof of root cause or recovery.
- Inventory is queried on demand and evidence is stored in incident aggregates; Relay is not a telemetry warehouse.
- Arbitrary shell execution is intentionally unsupported.

The next milestone should add authentication/RBAC, production provider query templates, worker leasing/recovery for orphaned runs, and a shared event notification layer before horizontal deployment.

## License

[MIT](LICENSE)
