import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  Play,
  Plus,
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
        <section className="panel health">
          <PanelTitle title="Network health" meta="5 DEVICES · 4 LINKS" />
          <div className="health-ring">
            <span>98</span>
            <small>HEALTH SCORE</small>
          </div>
          <div className="health-row">
            <span>
              <i className="good-dot" />
              Control plane
            </span>
            <b>HEALTHY</b>
          </div>
          <div className="health-row">
            <span>
              <i className="good-dot" />
              Simulator
            </span>
            <b>ONLINE</b>
          </div>
          <div className="health-row">
            <span>
              <i className="blue-dot" />
              Planner
            </span>
            <b>READY</b>
          </div>
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
      <span>{label}</span>
      <strong>{value}</strong>
      <small>ACTUAL RELAY DATA</small>
    </div>
  );
}
function Page({
  eyebrow,
  title,
  action,
  children,
}: {
  eyebrow?: string;
  title?: string;
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
          </div>
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
function PanelTitle({ title, meta }: { title: string; meta?: string }) {
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
  const [creating, setCreating] = useState(false);
  const nav = useNavigate();
  async function inject(s: Scenario) {
    setCreating(true);
    try {
      const i = await api.create(s);
      nav(`/incidents/${i.id}`);
    } finally {
      setCreating(false);
    }
  }
  return (
    <Page
      eyebrow="INCIDENT COMMAND"
      title="Incidents"
      action={<span className="quiet">Deterministic scenario laboratory</span>}
    >
      <section className="inject panel">
        <div>
          <span className="kicker">CREATE / INJECT</span>
          <h2>Choose a failure scenario</h2>
          <p>
            The root cause remains hidden. Relay receives only the incident
            symptoms.
          </p>
        </div>
        <div className="scenario-grid">
          {scenarios.data?.map((s) => (
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
    <Page eyebrow="NETWORK DIGITAL TWIN" title="Topology">
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
  useEffect(() => {
    if (!q.data || !["OPEN", "INVESTIGATING"].includes(q.data.status)) return;
    const t = setInterval(() => void q.reload(), 700);
    return () => clearInterval(t);
  }, [q.data?.status, q.reload]);
  const incident = q.data;
  async function run() {
    setBusy(true);
    try {
      await api.start(id, planner);
      await q.reload();
    } finally {
      setBusy(false);
    }
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
            <span>P2 · HIGH</span>
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
          <label>Investigation mode</label>
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
            title="Evidence"
            meta={`${incident.evidence.length} OBSERVATIONS`}
          />
          {incident.evidence.map((e) => (
            <button key={e.id} onClick={() => setSelected(component(e))}>
              <span>{fmtTime(e.recorded_at)}</span>
              <b>{e.summary}</b>
              <small>
                {Object.entries(e.observation)
                  .slice(0, 2)
                  .map(([k, v]) => `${k}: ${String(v)}`)
                  .join(" · ")}
              </small>
            </button>
          ))}
        </section>
        <section className="panel hypotheses">
          <PanelTitle title="Active hypotheses" meta="HEURISTIC CONFIDENCE" />
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
        </div>
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
    <Page eyebrow="AUDIT LOG" title="Agent runs">
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
              <span>Result</span>
            </div>
            {q.data.map((r: any) => (
              <a
                href={`/incidents/${r.incident_id}`}
                className="run-row"
                key={r.id}
              >
                <span>
                  <b>{String(r.id).slice(0, 8)}</b>
                  <small>{r.incident_title}</small>
                </span>
                <span>{scenarioName(r.scenario)}</span>
                <span>{r.planner}</span>
                <span>{r.steps_used}</span>
                <span>{r.tool_calls}</span>
                <span>
                  <Status value={r.status} />
                </span>
              </a>
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
    <Page eyebrow="DETERMINISTIC EVALUATION" title="Agent performance">
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
