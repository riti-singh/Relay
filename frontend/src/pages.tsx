import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  ExternalLink,
  Info,
  Play,
  Plus,
  Radio,
  ShieldAlert,
  X,
} from "lucide-react";
import { api } from "./api";
import {
  Empty,
  ErrorState,
  fmtTime,
  Inspector,
  NetworkMap,
  pct,
  Status,
  ToolRow,
  Verification,
} from "./components";
import { useLoad } from "./hooks";
import type { Evidence, Incident, Scenario } from "./types";
const scenarioName = (s: string) =>
  ({
    "interface-disabled": "Interface Disabled",
    "incorrect-route": "Incorrect Static Route",
    "acl-block": "ACL Block",
    "dns-failure": "DNS Failure",
    "degraded-link": "Congested Link",
    "config-drift": "Configuration Drift",
  })[s] ?? s;
function Help({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <span className="help">
      <button aria-label={`What is ${term}?`} title={String(children)}><Info /></button>
      <span role="tooltip"><b>{term}</b>{children}</span>
    </span>
  );
}
export { Home } from "./home";
export function Overview() {
  const q = useLoad(() => api.dashboard(), []);
  if (q.error)
    return (
      <Page>
        <ErrorState message={q.error} retry={q.reload} />
      </Page>
    );
  if (!q.data)
    return (
      <Page>
        <div className="loading">Loading live operations data…</div>
      </Page>
    );
  const d = q.data as Record<string, any>;
  return (
    <Page
      eyebrow="LIVE OPERATIONS"
      title="Network health at a glance"
      description="A system-wide operational summary of active incidents, approvals, recovery, investigation efficiency, and deterministic quality metrics."
      action={
        <a className="primary" href="/incidents">
          <Plus /> Inject Incident
        </a>
      }
    >
      <div className="metric-grid">
        <Metric label="Open incidents" value={d.open_incidents} />
        <Metric
          label="Awaiting approval"
          value={d.awaiting_approval}
          alert={d.awaiting_approval > 0}
        />
        <Metric label="Resolved" value={d.resolved_incidents} />
        <Metric
          label="Mean investigation"
          value={`${Number(d.mean_investigation_steps).toFixed(1)} steps`}
        />
        <Metric
          label="Root-cause accuracy"
          value={pct(d.root_cause_accuracy)}
        />
        <Metric
          label="Resolution success"
          value={pct(d.resolution_success_rate)}
        />
        <Metric label="Safety violations" value={d.safety_violations} />
        <Metric
          label="Tools / run"
          value={Number(d.average_tool_calls).toFixed(1)}
        />
      </div>
      <div className="overview-grid">
        <section className="panel span2">
          <PanelTitle title="Recent incidents" meta="SIMULATED ENVIRONMENT" />
          {d.recent_incidents?.length ? (
            <IncidentTable incidents={d.recent_incidents} />
          ) : (
            <Empty
              title="No incident history"
              detail="Inject a deterministic scenario to begin."
            />
          )}
        </section>
      </div>
    </Page>
  );
}
function Metric({
  label,
  value,
  alert,
}: {
  label: string;
  value: string | number;
  alert?: boolean;
}) {
  return (
    <div className={`metric ${alert ? "metric-alert" : ""}`}>
      <span>{label} {metricHelp[label] && <Help term={label}>{metricHelp[label]}</Help>}</span>
      <strong>{value}</strong>
      <small>ACTUAL RELAY DATA</small>
    </div>
  );
}
const metricHelp: Record<string, string> = {
  "Open incidents": "Connectivity problems that have not yet been verified as resolved.",
  "Awaiting approval": "Investigations paused before an exact state-changing action.",
  "Root Cause Accuracy": "How often Relay correctly identifies the actual network failure.",
  "Remediation Accuracy": "How often Relay proposes the correct repair.",
  "Resolution Success": "How often remediation passes post-change verification.",
  "Safety Violation Rate": "Protected actions executed without valid exact-action approval. This should remain zero.",
  "Average Tool Calls": "Average diagnostic tool calls Relay needs per incident.",
  "Average Steps": "Average agent decisions before reaching a terminal or approval state.",
};
function Page({
  eyebrow,
  title,
  description,
  action,
  children,
}: {
  eyebrow?: string;
  title?: string;
  description?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="page">
      {title && (
        <div className="page-head">
          <div>
            <span>{eyebrow}</span>
            <h1>{title}</h1>
            {description && <p>{description}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
function PanelTitle({ title, meta }: { title: React.ReactNode; meta?: string }) {
  return (
    <div className="panel-title">
      <h2>{title}</h2>
      {meta && <span>{meta}</span>}
    </div>
  );
}
function IncidentTable({ incidents }: { incidents: Incident[] }) {
  const nav = useNavigate();
  return (
    <div className="table">
      <div className="tr th">
        <span>Incident</span>
        <span>Scenario</span>
        <span>Status</span>
        <span>Started</span>
        <span />
      </div>
      {incidents.map((i) => (
        <button
          className="tr"
          key={i.id}
          onClick={() => nav(`/incidents/${i.id}`)}
        >
          <span>
            <b>{i.title}</b>
            <small>
              {i.source_device} → {i.destination_device}
            </small>
          </span>
          <span>{scenarioName(i.scenario)}</span>
          <span>
            <Status value={i.status} />
          </span>
          <span>{fmtTime(i.created_at)}</span>
          <ArrowRight />
        </button>
      ))}
    </div>
  );
}
export function Incidents() {
  const q = useLoad(() => api.incidents(), []);
  const scenarios = useLoad(() => api.scenarios(), []);
  const observe = useLoad(() => api.observeDatasets(), []);
  const [mode, setMode] = useState<"LAB" | "OBSERVE">("LAB");
  const [creating, setCreating] = useState(false);
  const nav = useNavigate();
  async function inject(s: Scenario) {
    setCreating(true);
    try {
      const i = await api.create(s, mode);
      nav(`/incidents/${i.id}`);
    } finally {
      setCreating(false);
    }
  }
  return (
    <Page
      eyebrow="INCIDENT COMMAND"
      title="Incidents"
      description="Choose deterministic LAB telemetry or a read-only OBSERVE source. The same agent runtime and typed tools investigate both."
      action={<span className="quiet">{mode === "LAB" ? "Deterministic scenario laboratory" : "External telemetry · read-only"}</span>}
    >
      <section className="inject panel">
        <div>
          <span className="kicker">CREATE / INJECT</span>
          <h2>Choose a failure scenario</h2>
          <div className="mode-picker" aria-label="Operating mode">
            <button className={mode === "LAB" ? "active" : ""} onClick={() => setMode("LAB")}><b>LAB</b><span>Deterministic simulation. Guarded remediation is available.</span></button>
            <button className={mode === "OBSERVE" ? "active" : ""} onClick={() => setMode("OBSERVE")}><b>OBSERVE</b><span>External telemetry only. Relay cannot modify the network.</span></button>
          </div>
          <p>
            The root cause remains hidden. Relay receives only the incident
            symptoms.
          </p>
        </div>
        <div className="scenario-grid">
          {(mode === "LAB" ? scenarios.data : observe.data)?.map((s) => (
            <button key={s.id} disabled={creating} onClick={() => inject(s)}>
              <AlertTriangle />
              <b>{s.name}</b>
              <span>{s.description}</span>
              <small>INJECT INCIDENT →</small>
            </button>
          ))}
        </div>
      </section>
      <section className="panel">
        <PanelTitle
          title="Incident history"
          meta={`${q.data?.length ?? 0} RECORDS`}
        />
        {q.error ? (
          <ErrorState message={q.error} retry={q.reload} />
        ) : q.data?.length ? (
          <IncidentTable incidents={q.data} />
        ) : (
          <Empty
            title="No incidents yet"
            detail="Choose a scenario above to create the first investigation."
          />
        )}
      </section>
    </Page>
  );
}
export function TopologyPage() {
  const q = useLoad(() => api.topology(), []);
  const [selected, setSelected] = useState<string>();
  return (
    <Page eyebrow="NETWORK DIGITAL TWIN" title="Topology" description="Devices are nodes and network connections are edges. Relay highlights affected paths and suspected components as evidence narrows the diagnosis.">
      <div className="topology-page panel">
        {q.error ? (
          <ErrorState message={q.error} retry={q.reload} />
        ) : q.data ? (
          <>
            <NetworkMap
              topology={q.data}
              selected={selected}
              onSelect={setSelected}
            />
            <aside className="detail-rail">
              <PanelTitle title="Component inspector" />
              <Inspector topology={q.data} id={selected} />
            </aside>
          </>
        ) : (
          <div className="loading">Loading topology…</div>
        )}
      </div>
    </Page>
  );
}
export function IncidentPage() {
  const { id = "" } = useParams();
  const q = useLoad(() => api.incident(id), [id]);
  const tq = useLoad(() => api.topology(id), [id]);
  const caps = useLoad(() => api.capabilities(), []);
  const [selected, setSelected] = useState<string>();
  const [planner, setPlanner] = useState("deterministic");
  const [busy, setBusy] = useState(false);
  const [activeRun, setActiveRun] = useState<string>();
  useEffect(() => {
    if (!activeRun) return;
    const stream = api.events(id, activeRun);
    stream.onmessage = () => void q.reload();
    stream.onerror = () => { stream.close(); void q.reload(); };
    return () => stream.close();
  }, [activeRun, id, q.reload]);
  const incident = q.data;
  async function run() {
    setBusy(true);
    try {
      const started = await api.start(id, planner);
      setActiveRun(started.id);
      await q.reload();
    } finally {
      setBusy(false);
    }
  }
  async function cancel() {
    if (!activeRun) return;
    await api.cancel(id, activeRun);
    await q.reload();
  }
  async function approve() {
    if (!incident?.proposed_remediation) return;
    setBusy(true);
    try {
      q.setData(await api.approve(id, incident.proposed_remediation));
    } finally {
      setBusy(false);
    }
  }
  async function reject() {
    if (!incident?.proposed_remediation) return;
    q.setData(await api.reject(id, incident.proposed_remediation));
  }
  if (q.error)
    return (
      <Page>
        <ErrorState message={q.error} retry={q.reload} />
      </Page>
    );
  if (!incident)
    return (
      <Page>
        <div className="loading">Opening incident workspace…</div>
      </Page>
    );
  const current = incident.actions.at(-1);
  return (
    <Page>
      <div className="incident-head">
        <div>
          <div className="incident-tags">
            <Status value={incident.status} />
            <Status value={incident.operating_mode ?? "LAB"} />
            <span>{scenarioName(incident.scenario)}</span>
          </div>
          <h1>{incident.title}</h1>
          <p>{incident.description}</p>
          <small>
            {incident.source_device} <ArrowRight />{" "}
            {incident.destination_device} · started{" "}
            {fmtTime(incident.created_at)}
          </small>
        </div>
        <div className="run-control">
          {incident.operating_mode === "OBSERVE" && <div className="readonly-notice"><ShieldAlert /> OBSERVE is structurally read-only. No remediation tools are registered.</div>}
          <label>Investigation mode</label>
          <p className="control-help">Deterministic is reproducible; AI Agent chooses diagnostic steps dynamically. Both use the same validated tools and approval boundary.</p>
          <div className="segmented">
            <button
              className={planner === "deterministic" ? "active" : ""}
              onClick={() => setPlanner("deterministic")}
            >
              Deterministic
            </button>
            <button
              className={planner === "ai" ? "active" : ""}
              disabled={!caps.data?.ai_planner}
              title={
                !caps.data?.ai_planner
                  ? "Configure provider credentials on the backend"
                  : ""
              }
              onClick={() => setPlanner("ai")}
            >
              AI Agent
            </button>
          </div>
          {!caps.data?.ai_planner && (
            <small>
              AI provider not configured. Deterministic mode is available.
            </small>
          )}
          <button
            className="primary"
            disabled={
              busy ||
              !["OPEN", "INVESTIGATING", "BLOCKED", "FAILED"].includes(
                incident.status,
              )
            }
            onClick={run}
          >
            <Play />
            {incident.actions.length
              ? "Continue Investigation"
              : "Start Investigation"}
          </button>
          {activeRun && incident.status === "INVESTIGATING" && (
            <button className="cancel" onClick={cancel}>Cancel safely</button>
          )}
        </div>
      </div>
      {incident.status === "INVESTIGATING" && (
        <div className="runtime-bar">
          <span className="pulse" />
          <b>INVESTIGATING</b>
          <span>
            Step {current?.step ?? 0} /{" "}
            {caps.data?.max_investigation_steps ?? 20}
          </span>
          <span className="runtime-action">
            Current action:{" "}
            {current?.decision.summary ?? "Initializing bounded investigation"}
          </span>
        </div>
      )}
      <div className="progress-steps" aria-label="Investigation progress">
        {["Incident context", "Investigation", "Evidence", "Root cause", "Approval", "Remediation", "Verification"].map((step, index) => (
          <span className={progressIndex(incident.status) >= index ? "done" : ""} key={step}>{index + 1}<small>{step}</small></span>
        ))}
      </div>
      <div className="workspace">
        <section className="panel topology-work">
          <PanelTitle title="Incident path" meta="EVIDENCE-AWARE TOPOLOGY" />
          {tq.data && (
            <NetworkMap
              topology={tq.data}
              incident={incident}
              selected={selected}
              onSelect={setSelected}
            />
          )}{" "}
          {tq.data && selected && (
            <div className="floating-inspector">
              <button onClick={() => setSelected(undefined)}>×</button>
              <Inspector topology={tq.data} id={selected} />
            </div>
          )}
        </section>
        <section className="panel timeline">
          <PanelTitle
            title="Investigation timeline"
            meta={`${incident.actions.length} ACTIONS`}
          />
          <Timeline incident={incident} />
        </section>
        <section className="panel evidence-panel">
          <PanelTitle
            title={<>Evidence <Help term="Evidence">Facts collected from diagnostic tools. Relay uses them to support or contradict hypotheses.</Help></>}
            meta={`${incident.evidence.length} OBSERVATIONS`}
          />
          {incident.evidence.length ? incident.evidence.map((e) => (
            <div className="evidence-row" key={e.id}>
              <button onClick={() => setSelected(component(e))}>
                <span>{fmtTime(e.recorded_at)}</span>
                <b>{e.summary}</b>
                <small>
                  {Object.entries(e.observation)
                    .slice(0, 2)
                    .map(([k, v]) => `${k}: ${String(v)}`)
                    .join(" · ")}
                </small>
              </button>
              {e.provenance && <Provenance evidence={e} />}
            </div>
          )) : <Empty title="No evidence yet" detail="Evidence appears here as diagnostic tools complete." />}
        </section>
        <section className="panel hypotheses">
          <PanelTitle title={<>Hypotheses <Help term="Confidence">Possible explanations for the failure. Confidence changes as evidence arrives; it is not a guarantee.</Help></>} meta="EVIDENCE-BACKED CONFIDENCE" />
          {incident.hypotheses.length ? (
            incident.hypotheses.map((h) => (
              <div
                className={`hypothesis ${h.status.toLowerCase()}`}
                key={h.id}
              >
                <strong>{Math.round(h.confidence * 100)}%</strong>
                <div>
                  <b>{h.statement}</b>
                  <Status value={h.status} />
                  <small>
                    {h.supporting_evidence_ids.length} supporting ·{" "}
                    {h.contradicting_evidence_ids.length} contradicting
                  </small>
                  {h.history.map((r, i) => (
                    <span key={i}>
                      {Math.round(r.confidence * 100)}% · {r.summary}
                    </span>
                  ))}
                </div>
              </div>
            ))
          ) : (
            <Empty
              title="No hypothesis yet"
              detail="Relay will form and revise hypotheses as evidence arrives."
            />
          )}
        </section>
      </div>
      {incident.proposed_remediation && (
        <Approval
          incident={incident}
          approve={approve}
          reject={reject}
          busy={busy}
        />
      )}
      <Verification incident={incident} />
    </Page>
  );
}
const metaString = (m: Record<string, unknown>, key: string) =>
  typeof m[key] === "string" ? (m[key] as string) : undefined;
const metaNumber = (m: Record<string, unknown>, key: string) =>
  typeof m[key] === "number" ? (m[key] as number) : undefined;
function SourceLink({ href, children }: { href?: string; children: React.ReactNode }) {
  if (!href) return null;
  return (
    <a className="source-link" href={href} target="_blank" rel="noopener noreferrer">
      {children} <ExternalLink />
    </a>
  );
}
function Provenance({ evidence }: { evidence: Evidence }) {
  const p = evidence.provenance!;
  const m = p.source_metadata ?? {};
  const measurementUrl = metaString(m, "measurement_url");
  const probesTotal = metaNumber(m, "probes_total");
  const probesAffected = metaNumber(m, "probes_affected");
  const ripestat: Array<[string, string | undefined]> = [
    ["Routing status", metaString(m, "routing_status_url")],
    ["Prefix overview", metaString(m, "prefix_overview_url")],
    ["BGP updates", metaString(m, "bgp_updates_url")],
  ];
  const hasRipestat = ripestat.some(([, href]) => href);
  return (
    <div className={`provenance ${p.freshness.toLowerCase()}`} aria-label="Evidence provenance">
      <span className="provenance-tags">
        <Status value={p.freshness} />
        {evidence.status && <Status value={evidence.status} />}
        <span>{p.source_type}</span>
        <span>{p.adapter}</span>
        {p.resource_id && <span>{p.resource_id}</span>}
        <span>{p.observed_at ? `observed ${fmtTime(p.observed_at)}` : "not observed"}</span>
      </span>
      {(measurementUrl || probesTotal !== undefined || hasRipestat) && (
        <span className="provenance-links">
          {measurementUrl && (
            <SourceLink href={measurementUrl}>
              RIPE Atlas measurement{m.measurement_id !== undefined ? ` ${String(m.measurement_id)}` : ""}
            </SourceLink>
          )}
          {probesTotal !== undefined && (
            <span>{probesAffected ?? 0} / {probesTotal} probes affected</span>
          )}
          {hasRipestat && <span>verify in RIPEstat:</span>}
          {ripestat.map(([label, href]) => (
            <SourceLink key={label} href={href}>{label}</SourceLink>
          ))}
        </span>
      )}
    </div>
  );
}
const progressIndex = (status: string) => ({ OPEN: 0, INVESTIGATING: 2, BLOCKED: 2, FAILED: 2, AWAITING_APPROVAL: 4, REMEDIATING: 5, VERIFYING: 6, RESOLVED: 6 } as Record<string, number>)[status] ?? 0;
const component = (e: Evidence) =>
  String(
    e.observation.device_id ??
      e.observation.failure_after ??
      e.observation.device_a ??
      "",
  );
function Timeline({ incident }: { incident: Incident }) {
  const calls = new Map(incident.tool_calls.map((c) => [c.id, c]));
  const evidence = new Map(incident.evidence.map((e) => [e.tool_call_id, e]));
  if (!incident.actions.length)
    return (
      <Empty
        title="Investigation not started"
        detail="Select a planner and start Relay to watch its decisions arrive."
      />
    );
  return (
    <div className="timeline-list">
      {incident.actions.map((a) => (
        <div className="timeline-item" key={a.id}>
          <time>{fmtTime(a.created_at)}</time>
          <div className="timeline-line">
            <i />
          </div>
          <div className="timeline-content">
            <span className="timeline-kind">
              {a.decision.kind.replaceAll("_", " ")}
            </span>
            <p>{a.decision.summary}</p>
            {a.tool_call_id && calls.get(a.tool_call_id) && (
              <ToolRow
                call={calls.get(a.tool_call_id)!}
                evidence={evidence.get(a.tool_call_id)}
              />
            )}{" "}
            {a.error && <div className="action-error">{a.error}</div>}
          </div>
        </div>
      ))}
    </div>
  );
}
function Approval({
  incident,
  approve,
  reject,
  busy,
}: {
  incident: Incident;
  approve: () => void;
  reject: () => void;
  busy: boolean;
}) {
  const r = incident.proposed_remediation!;
  const related = incident.hypotheses.find((h) => h.status === "CONFIRMED");
  return (
    <section className="approval">
      <div className="approval-banner">
        <ShieldAlert />
        <div>
          <span>AWAITING HUMAN APPROVAL</span>
          <h2>{r.description}</h2>
          <p>Relay investigated autonomously, but it cannot change the network without your approval.</p>
        </div>
      </div>
      <div className="approval-body">
        <div>
          <label>Exact action</label>
          <pre>
            {r.tool_name}(
            {Object.entries(r.arguments)
              .map(([k, v]) => `\n  ${k}=${JSON.stringify(v)}`)
              .join(",")}
            \n)
          </pre>
          <small>Affects {String(r.arguments.device_id ?? r.arguments.link_id ?? r.arguments.hostname ?? "the incident network resource")}.</small>
        </div>
        <div>
          <label>Why Relay recommends it</label>
          <p>{related?.statement}</p>
          <small>
            Supported by {related?.supporting_evidence_ids.length ?? 0} stored
            evidence items.
          </small>
        </div>
        <div>
          <label>Risk classification</label>
          <Status value="LOW_RISK_WRITE" />
          <p>Execution remains blocked until this exact action is approved.</p>
          <small>The approval fingerprint binds this incident, remediation, tool, and canonical arguments. Modified arguments invalidate approval.</small>
        </div>
        <div><label>What happens next</label><p>Relay executes the write once, then runs connectivity checks. It marks the incident resolved only if verification proves recovery.</p></div>
      </div>
      <div className="approval-actions">
        <button className="primary approve" disabled={busy} onClick={approve}>
          <Check />
          Approve Remediation
        </button>
        <button onClick={reject}>
          <X />
          Reject
        </button>
        <button onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>
          Continue Investigation
        </button>
      </div>
    </section>
  );
}
export function Runs() {
  const q = useLoad(() => api.runs(), []);
  return (
    <Page eyebrow="AUDIT LOG" title="Agent runs" description="A run is one bounded, durable investigation execution. Its status, decisions, tool calls, and events can be replayed after completion.">
      <section className="panel">
        <PanelTitle
          title="Investigation runs"
          meta={`${q.data?.length ?? 0} RUNS`}
        />
        {q.error ? (
          <ErrorState message={q.error} retry={q.reload} />
        ) : q.data?.length ? (
          <div className="run-table">
            <div className="run-row head">
              <span>Run / incident</span>
              <span>Scenario</span>
              <span>Planner</span>
              <span>Steps</span>
              <span>Tools</span>
              <span>Status</span>
            </div>
            {q.data.map((r: any) => (
              <details className="run-replay" key={r.id}><summary className="run-row">
                <span>
                  <b>{String(r.id).slice(0, 8)}</b>
                  <small>{r.incident_title}</small>
                </span>
                <span>{scenarioName(r.scenario)}</span>
                <span>{r.planner}</span>
                <span>{r.current_step ?? r.steps_used} / {r.max_steps ?? "—"}</span>
                <span>{r.tool_call_count ?? 0}</span>
                <span>
                  <Status value={r.status} />
                </span>
              </summary><div className="event-replay"><p><b>Latest activity:</b> {r.latest_event?.payload?.summary ?? "Queued"}</p>{r.events?.map((e: any) => <div key={e.event_id}><time>{fmtTime(e.timestamp)}</time><Status value={e.type} /><span>{e.payload?.summary}</span></div>)}<a href={`/incidents/${r.incident_id}`}>Open incident workspace <ArrowRight /></a></div></details>
            ))}
          </div>
        ) : (
          <Empty
            title="No agent runs"
            detail="Start an incident investigation to create an auditable run."
          />
        )}
      </section>
    </Page>
  );
}
export function Integrations() {
  const q = useLoad(() => api.integrations(), []);
  return (
    <Page eyebrow="TELEMETRY" title="Integrations / Data Sources" description="Relay queries bounded, typed telemetry capabilities. Credentials and arbitrary command execution are never exposed to the console.">
      <div className="integration-grid">
        {q.data?.map((source) => (
          <section className="panel integration-card" key={source.id}>
            <div><Radio /><h2>{source.name}</h2><Status value={source.status} /></div>
            <p>{source.type} · <b>{source.read_only ? "READ ONLY" : "LAB WRITES HUMAN-GATED"}</b></p>
            <small>Capabilities</small>
            <div className="capabilities-list">{source.capabilities.map((capability) => <span key={capability}>{capability.replaceAll("_", " ")}</span>)}</div>
            <p>Last successful observation: {source.last_successful_observation ? fmtTime(source.last_successful_observation) : "Not yet queried"}</p>
          </section>
        ))}
        {q.error && <ErrorState message={q.error} retry={q.reload} />}
      </div>
    </Page>
  );
}

export function Evaluations() {
  const q = useLoad(() => api.evaluations(), []);
  if (q.error)
    return (
      <Page>
        <ErrorState message={q.error} retry={q.reload} />
      </Page>
    );
  if (!q.data)
    return (
      <Page>
        <div className="loading">Loading evaluation results…</div>
      </Page>
    );
  const s = q.data.summary;
  return (
    <Page eyebrow="DETERMINISTIC EVALUATION" title="Agent performance" description="The same six known failures are replayed without a live LLM so accuracy, efficiency, recovery, and safety remain reproducible.">
      <div className="metric-grid eval">
        <Metric
          label="Root Cause Accuracy"
          value={pct(s.root_cause_accuracy)}
        />
        <Metric
          label="Remediation Accuracy"
          value={pct(s.remediation_accuracy)}
        />
        <Metric
          label="Resolution Success"
          value={pct(s.resolution_success_rate)}
        />
        <Metric
          label="Safety Violation Rate"
          value={pct(s.safety_violation_rate)}
        />
        <Metric label="Average Tool Calls" value={s.average_tool_calls} />
        <Metric label="Average Steps" value={s.average_investigation_steps} />
      </div>
      <section className="panel">
        <PanelTitle
          title="Results by scenario"
          meta={`PLANNER · ${q.data.planner.toUpperCase()}`}
        />
        <div className="eval-table">
          <div className="eval-row head">
            <span>Scenario</span>
            <span>Diagnosis</span>
            <span>Remediation</span>
            <span>Resolved</span>
            <span>Tools</span>
            <span>Steps</span>
          </div>
          {q.data.scenarios.map((r) => (
            <div className="eval-row" key={r.scenario}>
              <b>{scenarioName(r.scenario)}</b>
              <span className={r.root_cause_accurate ? "good" : "bad"}>
                {r.root_cause_accurate ? "✓" : "×"}
              </span>
              <span className={r.remediation_accurate ? "good" : "bad"}>
                {r.remediation_accurate ? "✓" : "×"}
              </span>
              <span className={r.resolved ? "good" : "bad"}>
                {r.resolved ? "✓" : "×"}
              </span>
              <span>
                <i
                  className="bar"
                  style={{ width: `${r.diagnostic_tool_calls * 7}px` }}
                />
                {r.diagnostic_tool_calls}
              </span>
              <span>{r.investigation_steps}</span>
            </div>
          ))}
        </div>
      </section>
    </Page>
  );
}
