---
name: relay-local-e2e
description: Run Relay NOC console integration and deterministic LAB workflow checks locally without provider credentials.
---

# Local Relay E2E

## Devin Secrets Needed
None for default deterministic LAB and integration listing. Do not configure or send provider/Atlas credentials unless explicitly requested.

## Startup
- Follow repository blueprint dependencies; if pnpm fails signature validation, run its documented Corepack initialization before retrying.
- From repo root: `.venv/bin/uvicorn relay.main:app --port 8000`.
- For healthy local HTTP source inventory: `.venv/bin/uvicorn relay.fixture_service:app --port 8001`.
- From frontend: `pnpm dev`.
- Open http://127.0.0.1:5173. No login is required in the default local app.
- Browser /api routes are Vite-proxied to unprefixed backend paths, e.g. frontend `/api/integrations` maps to backend `/integrations`.

## Useful flows and evidence
- Sidebar **Data Sources** opens the Integrations view; verify source name, type, capabilities, and write/read-only designation together.
- To demonstrate listing does not query external telemetry, optionally run API under `strace -f -e trace=connect -o /tmp/relay-network.trace ...`; start the local fixture to avoid its timeout masking listing performance. Inspect runtime connections, not just elapsed time.
- Sidebar **Incidents** → **LAB** → **Interface Disabled** injects a new incident. **Start Investigation** runs the deterministic planner.
- Expect **AWAITING APPROVAL**, populated evidence, and a proposed interface enable action. Scroll to the page bottom to capture the gate before clicking **Approve Remediation**.
- After approval verify both the top status and bottom recovery checks; reload to check persistence. Do not assume a resolved status means all approval UI controls have updated correctly.
- Keep LAB regression evidence separate from source registration evidence. The deterministic LAB fixture is the actual product simulator, not a mocked backend.
