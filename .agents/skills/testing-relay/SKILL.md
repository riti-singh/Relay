---
name: testing-relay-observe
description: Run the local Relay console, fixture telemetry, and public read-only adapter checks while distinguishing adapter coverage from incident integration.
---

# Relay OBSERVE testing

## Local services
- Use the existing `.venv`; if missing, run `make install` in the repository root.
- Start backend with `make run` (8000).
- Start fixture telemetry separately with `.venv/bin/uvicorn relay.fixture_service:app --port 8001`.
- In `frontend`, run `pnpm install --frozen-lockfile` then `pnpm dev` (5173).
- If Node 22's bundled Corepack rejects signing keys, update Corepack (`npm install --global corepack@0.34.0`). Pin an available pnpm version compatible with the lockfile (`corepack install --global pnpm@10.15.1`) if automatic latest resolution uses an unusable cache.
- Local deterministic console/API have no login. Check `/health` on 8000 and 8001.

## UI paths and evidence
- Data Sources shows adapter identity, read-only status, and capabilities.
- Incidents → OBSERVE → External route anomaly → Start Investigation exercises fixture telemetry.
- Expand `get_route_table` in the independently scrolling Investigation timeline; expected fixture anomaly is `orders-api: discard`.
- Save raw incident JSON to verify provenance, run source IDs, absence of proposed remediation/write calls, and approval audit events.
- Exact remediation approval uses matching UUID in URL and body; OBSERVE should return 409 with `OBSERVE_WRITE_REJECTED`. Legacy approval can reject earlier because no remediation exists.

## Partial adapters and live providers
- Inspect current source selection before assuming a multi-source list creates a composite: a CompositeNetworkAdapter class may exist without being wired into incident service.
- Incident creation may validate endpoints against topology. Empty-topology adapters can therefore appear in Data Sources yet remain unreachable through incident creation.
- Do not persist bypass-created incidents to hide that gap. Clearly label direct live adapter calls as supplemental coverage, not API end-to-end success.
- Trace actual planner/tool arguments: route tools may receive `device_id` from the incident source rather than the destination IP.
- For RIPEstat, public examples are 193.0.0.1 (AS3333), 8.8.8.8 (AS15169), and 192.0.2.0/24 (unannounced). Compare provenance `observed_at` with routing-status `query_time`, not collection time.
- Public API invalid-input HTTP errors can be classified differently than error-status JSON bodies; save both actual observation status and provider response.

## Devin Secrets Needed
None for deterministic fixture telemetry or public RIPEstat reads. AI planner testing requires separately configured `RELAY_AGENT_API_KEY` and is not necessary for these flows.
