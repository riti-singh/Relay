import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  Info,
  Play,
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
const workflow = ["Incident", "Investigation", "Diagnostic tools", "Evidence", "Hypothesis", "Root cause", "Human approval", "Remediation", "Verification"];
function Help({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <span className="help">
      <button aria-label={`What is ${term}?`} title={String(children)}><Info /></button>
      <span role="tooltip"><b>{term}</b>{children}</span>
    </span>
  );
}
export function Home() {
  const [showGuide, setShowGuide] = useState(() => globalThis.localStorage?.getItem("relay-onboarding-dismissed") !== "true");
  const dismiss = () => { globalThis.localStorage?.setItem("relay-onboarding-dismissed", "true"); setShowGuide(false); };
  return (
    <Page>
      <section className="hero">
        <span className="kicker">GUIDED NETWORK INCIDENT RESPONSE</span>
        <h1>Understand the failure. Approve the change. Verify recovery.</h1>
        <p>Relay investigates network incidents with diagnostic tools, turns observations into evidence-backed root causes, and keeps every network change behind human approval.</p>
        <div className="hero-actions"><a className="primary" href="/incidents">Start an investigation <ArrowRight /></a><a href="/incidents">Explore a sample incident</a></div>
      </section>
      <section className="workflow" aria-label="Relay investigation workflow">
        {workflow.map((step, index) => <div key={step}><span>{index + 1}</span><b>{step}</b>{index < workflow.length - 1 && <ArrowRight />}</div>)}
      </section>
      {showGuide ? <section className="onboarding panel"><div><span className="kicker">WELCOME TO RELAY</span><h2>Your first investigation</h2></div><ol><li>Choose a simulated network failure.</li><li>Start a deterministic or AI Agent investigation.</li><li>Watch Relay gather evidence and revise hypotheses.</li><li>Review the proposed fix and approve the exact action.</li><li>Watch Relay verify that connectivity recovered.</li></ol><button onClick={dismiss}>Dismiss guide</button></section> : <button className="rediscover" onClick={() => setShowGuide(true)}>Show first-run guide</button>}
      <div className="explain-grid">
        <section><h2>Two ways to investigate</h2><p><b>Deterministic mode</b> follows a reproducible decision policy—ideal for demos, tests, and comparing results. <b>AI Agent mode</b> chooses the next safe diagnostic action from the same typed tools. Neither mode can bypass tool validation.</p></section>
        <section><h2>Autonomous diagnosis, human-controlled change</h2><p>Relay can inspect the network on its own. Before a write, it pauses and fingerprints the exact tool and arguments. Any change invalidates that approval.</p></section>
        <section><h2>Recovery must be proven</h2><p>Remediation is not success by itself. Relay runs scenario-relevant connectivity checks and resolves the incident only when verification passes.</p></section>
        <section><h2>Built for evidence, not opaque answers</h2><p>Tool calls, observations, hypotheses, run events, approvals, and verification remain visible and replayable. Hidden model reasoning is never stored.</p></section>
      </div>
      <section className="product-areas panel"><h2>Explore Relay</h2><div><a href="/incidents"><b>Investigation workspace</b><span>Select a source and investigate</span></a><a href="/topology"><b>Network evidence</b><span>See simulated topology or observed paths</span></a><a href="/runs"><b>Run history</b><span>Replay durable executions</span></a><a href="/integrations"><b>Data sources</b><span>Inspect classifications and capabilities</span></a><a href="/evaluations"><b>Quality evaluation</b><span>Measure groundedness and safety</span></a></div></section>
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
  const [source, setSource] = useState<"LAB" | "RIPE_ATLAS" | "HTTP_FIXTURE">("LAB");
  const [measurementId, setMeasurementId] = useState("");
  const [sourceError, setSourceError] = useState("");
  const [creating, setCreating] = useState(false);
  const nav = useNavigate();
  async function inject(s: Scenario) {
    setCreating(true);
    try {
      const i = await api.create(s, source === "LAB" ? "LAB" : "OBSERVE");
      nav(`/incidents/${i.id}`);
    } finally {
      setCreating(false);
    }
  }
  async function createRipe() {
    setCreating(true);
    setSourceError("");
    try {
      const metadata = await api.ripeMeasurement(measurementId.trim());
      const i = await api.createRipe(measurementId.trim(), metadata);
      nav(`/incidents/${i.id}`);
    } catch (error) {
      setSourceError(error instanceof Error ? error.message : "RIPE Atlas query failed");
    } finally {
      setCreating(false);
    }
  }
  return (
    <Page
      eyebrow="NEW INVESTIGATION"
      title="Investigations"
      description="Choose a source. One agent runtime discovers and uses only that source's real diagnostic capabilities."
      action={<span className="quiet">{source.replaceAll("_", " ")}</span>}
    >
      <section className="inject panel">
        <div>
          <span className="kicker">DATA SOURCE</span>
          <h2>Select an investigation environment</h2>
          <div className="mode-picker" aria-label="Data source">
            <button className={source === "LAB" ? "active" : ""} onClick={() => setSource("LAB")}><b>Relay Lab</b><span>SIMULATION · deterministic scenarios with guarded remediation.</span></button>
            <button className={source === "RIPE_ATLAS" ? "active" : ""} onClick={() => setSource("RIPE_ATLAS")}><b>RIPE Atlas</b><span>LIVE PUBLIC INTERNET · read-only ping and traceroute telemetry.</span></button>
            <button className={source === "HTTP_FIXTURE" ? "active" : ""} onClick={() => setSource("HTTP_FIXTURE")}><b>Fixture HTTP</b><span>DEMO · structured recorded telemetry.</span></button>
          </div>
          <p>Capabilities, resource selection, provenance, and available tools follow this source.</p>
        </div>
        {source === "RIPE_ATLAS" ? (
          <div className="ripe-picker">
            <label htmlFor="measurement-id">Public measurement ID</label>
            <input id="measurement-id" value={measurementId} onChange={(event) => setMeasurementId(event.target.value)} placeholder="For example, a public ping or traceroute ID" />
            <button className="primary" disabled={creating || !measurementId.trim()} onClick={createRipe}>Load live metadata and create</button>
            {sourceError && <div className="action-error">{sourceError}</div>}
            <small>Relay calls the official RIPE Atlas API. Provider failures are shown; fixture fallback is never used.</small>
          </div>
        ) : <div className="scenario-grid">
          {(source === "LAB" ? scenarios.data : observe.data)?.map((s) => (
            <button key={s.id} disabled={creating} onClick={() => inject(s)}>
              <AlertTriangle />
              <b>{s.name}</b>
              <span>{s.description}</span>
              <small>INJECT INCIDENT →</small>
            </button>
          ))}
        </div>}
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
  const [comment, setComment] = useState("");
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
  async function submitComment(requestAgentStep: boolean) {
    if (!comment.trim()) return;
    setBusy(true);
    try {
      q.setData(await api.comment(id, comment.trim(), requestAgentStep));
      setComment("");
    } finally {
      setBusy(false);
    }
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
        {["Context", "Investigation", "Evidence", incident.operating_mode === "LAB" ? "Root cause" : "Assessment", "Action", "Verification"].map((step, index) => (
          <span className={progressIndex(incident.status) >= index ? "done" : ""} key={step}>{index + 1}<small>{step}</small></span>
        ))}
      </div>
      {incident.conclusion && <section className="panel conclusion"><span className="kicker">{incident.conclusion.kind.replace("_", " ")}</span><h2>{incident.conclusion.summary}</h2><p>Confidence {Math.round(incident.conclusion.confidence * 100)}% · grounded in {incident.conclusion.evidence_ids.length} evidence items</p></section>}
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
            title="Investigation activity"
            meta={`${incident.events.length} PERSISTED EVENTS`}
          />
          <Timeline incident={incident} />
          <div className="operator-input">
            <label htmlFor="operator-comment">Operator comment or investigation request</label>
            <textarea id="operator-comment" value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Check whether the affected probes share an ASN." />
            <div><button disabled={busy || !comment.trim()} onClick={() => submitComment(false)}>Add comment</button><button className="primary" disabled={busy || !comment.trim()} onClick={() => submitComment(true)}>Request another step</button></div>
          </div>
        </section>
        <section className="panel evidence-panel">
          <PanelTitle
            title={<>Evidence <Help term="Evidence">Facts collected from diagnostic tools. Relay uses them to support or contradict hypotheses.</Help></>}
            meta={`${incident.evidence.length} OBSERVATIONS`}
          />
          {incident.evidence.length ? incident.evidence.map((e) => (
            <button key={e.id} onClick={() => setSelected(component(e))}>
              <span>{fmtTime(e.recorded_at)}</span>
              <b>{e.summary}</b>
              <small>
                {Object.entries(e.observation)
                  .slice(0, 2)
                  .map(([k, v]) => `${k}: ${String(v)}`)
                  .join(" · ")}
              </small>
              {e.provenance && <span className={`provenance ${e.provenance.freshness.toLowerCase()}`}>
                {e.provenance.adapter} · {e.status} · {e.provenance.resource_id ?? "network"} · {e.provenance.observed_at ? `observed ${fmtTime(e.provenance.observed_at)}` : "not observed"}
              </span>}
            </button>
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
const progressIndex = (status: string) => ({ OPEN: 0, INVESTIGATING: 2, BLOCKED: 2, FAILED: 2, AWAITING_APPROVAL: 4, REMEDIATING: 5, VERIFYING: 6, RESOLVED: 6 } as Record<string, number>)[status] ?? 0;
const component = (e: Evidence) =>
  String(
    e.observation.device_id ??
      e.observation.failure_after ??
      e.observation.device_a ??
      "",
  );
function Timeline({ incident }: { incident: Incident }) {
  if (!incident.events.length)
    return (
      <Empty
        title="Investigation not started"
        detail="Select a planner and start Relay to watch its decisions arrive."
      />
    );
  return (
    <div className="timeline-list">
      {incident.events.map((event) => (
        <div className="timeline-item" key={event.event_id}>
          <time>{fmtTime(event.timestamp)}</time>
          <div className="timeline-line">
            <i />
          </div>
          <div className="timeline-content">
            <span className="timeline-kind">
              {event.type.replaceAll("_", " ")}
            </span>
            <p>{String(event.payload.summary ?? event.type)}</p>
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
            <p>{source.classification} · {source.adapter_type} · <b>{source.read_only ? "READ ONLY" : "LAB WRITES HUMAN-GATED"}</b></p>
            <small>Capabilities</small>
            <div className="capabilities-list">{source.capabilities.map((capability) => <span key={capability}>{capability.replaceAll("_", " ")}</span>)}</div>
            <p>Freshness: {source.freshness_policy.description}</p>
            <p>Last successful query: {source.last_successful_query ? fmtTime(source.last_successful_query) : "Not yet queried"}</p>
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
