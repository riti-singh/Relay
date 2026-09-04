import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape from "cytoscape";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Router,
  Server,
  Waypoints,
} from "lucide-react";
import type { Evidence, Incident, Link, Topology, ToolCall } from "./types";
export const fmtTime = (v: string) =>
  new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(v));
export const pct = (v: number) => `${Math.round(v * 100)}%`;
export function Status({ value }: { value: string }) {
  return (
    <span className={`status s-${value.toLowerCase()}`}>
      <i />
      {value.replaceAll("_", " ")}
    </span>
  );
}
export function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty">
      <Waypoints />
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}
export function ErrorState({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="error-state">
      <AlertTriangle />
      <div>
        <strong>Relay is unavailable</strong>
        <p>{message}</p>
      </div>
      {retry && <button onClick={retry}>Retry</button>}
    </div>
  );
}
export function NetworkMap({
  topology,
  incident,
  selected,
  onSelect,
}: {
  topology: Topology;
  incident?: Incident;
  selected?: string;
  onSelect?: (id: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | undefined>(undefined);
  const suspects = useMemo(
    () =>
      new Set(
        incident?.hypotheses
          .filter((h) => h.status !== "REJECTED")
          .map((h) => h.suspected_component?.split(/[/ ]/)[0])
          .filter(Boolean) ?? [],
      ),
    [incident],
  );
  const affected = new Set([
    incident?.source_device,
    incident?.destination_device,
  ]);
  useEffect(() => {
    if (!ref.current) return;
    const elements = [
      ...topology.devices.map((d) => ({
        data: { id: d.id, label: d.name, kind: d.kind },
        classes: `${affected.has(d.id) ? "affected " : ""}${suspects.has(d.id) ? "suspect" : ""}`,
      })),
      ...topology.links.map((l, i) => ({
        data: {
          id: `link-${i}`,
          source: l.device_a,
          target: l.device_b,
          label: `${l.latency_ms}ms · ${l.packet_loss_percent}% loss`,
          link: l,
        },
        classes:
          l.packet_loss_percent > 5 || l.latency_ms > 100 ? "failing" : "",
      })),
    ];
    const cy = cytoscape({
      container: ref.current,
      elements,
      layout: { name: "breadthfirst", directed: true, spacingFactor: 1.35 },
      style: [
        {
          selector: "node",
          style: {
            "background-color": "#151d27",
            "border-color": "#526277",
            "border-width": 2,
            label: "data(label)",
            color: "#cbd5e1",
            "font-size": 12,
            "text-valign": "bottom",
            "text-margin-y": 8,
            width: 42,
            height: 42,
          },
        },
        {
          selector: 'node[kind="service"]',
          style: {
            shape: "round-rectangle",
            "background-color": "#102b2c",
            "border-color": "#2dd4bf",
          },
        },
        {
          selector: ".affected",
          style: { "border-color": "#38bdf8", "border-width": 3 },
        },
        {
          selector: ".suspect",
          style: {
            "border-color": "#fb923c",
            "background-color": "#3a2116",
            "border-width": 4,
          },
        },
        {
          selector: "edge",
          style: {
            width: 2,
            "line-color": "#405064",
            "target-arrow-color": "#405064",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(label)",
            color: "#72839a",
            "font-size": 9,
            "text-background-color": "#0b0f14",
            "text-background-opacity": 1,
            "text-background-padding": "3px",
          },
        },
        {
          selector: ".failing",
          style: {
            "line-color": "#ef4444",
            "target-arrow-color": "#ef4444",
            width: 4,
          },
        },
        {
          selector: ":selected",
          style: {
            "overlay-color": "#38bdf8",
            "overlay-opacity": 0.16,
            "overlay-padding": 10,
          },
        },
      ],
    });
    cy.on("tap", "node, edge", (e) => onSelect?.(e.target.id()));
    cyRef.current = cy;
    return () => cy.destroy();
  }, [topology, incident, onSelect]);
  useEffect(() => {
    if (selected) cyRef.current?.getElementById(selected).select();
  }, [selected]);
  return (
    <div
      ref={ref}
      className="topology-canvas"
      aria-label="Interactive network topology"
    />
  );
}
export function Inspector({
  topology,
  id,
}: {
  topology: Topology;
  id?: string;
}) {
  if (!id)
    return (
      <div className="inspect-placeholder">
        Select a device or link to inspect its live state.
      </div>
    );
  const d = topology.devices.find((x) => x.id === id);
  const i = id.startsWith("link-") ? Number(id.slice(5)) : NaN;
  const l = topology.links[i];
  if (d)
    return (
      <div className="inspector">
        <div className="device-title">
          {d.kind === "service" ? <Server /> : <Router />}
          <div>
            <strong>{d.name}</strong>
            <small>
              {d.kind} · {d.id}
            </small>
          </div>
        </div>
        <h4>Interfaces</h4>
        {d.interfaces.map((x) => (
          <div className="kv" key={x.name}>
            <span>{x.name}</span>
            <b className={x.operational_up ? "good" : "bad"}>
              {x.admin_up && x.operational_up ? "UP" : "DOWN"}
            </b>
          </div>
        ))}
        <h4>Routes</h4>
        {Object.entries(d.routes).map(([k, v]) => (
          <div className="kv" key={k}>
            <span>{k}</span>
            <code>{v}</code>
          </div>
        ))}
        <details>
          <summary>Configuration</summary>
          <pre>{JSON.stringify(d.config, null, 2)}</pre>
        </details>
      </div>
    );
  if (l) return <LinkInspector link={l} />;
  return <div className="inspect-placeholder">No component selected.</div>;
}
function LinkInspector({ link: l }: { link: Link }) {
  return (
    <div className="inspector">
      <strong>
        {l.device_a} ↔ {l.device_b}
      </strong>
      <small>
        {l.interface_a} / {l.interface_b}
      </small>
      <h4>Link health</h4>
      <div className="kv">
        <span>Latency</span>
        <b>{l.latency_ms} ms</b>
      </div>
      <div className="kv">
        <span>Packet loss</span>
        <b className={l.packet_loss_percent > 5 ? "bad" : "good"}>
          {l.packet_loss_percent}%
        </b>
      </div>
    </div>
  );
}
export function ToolRow({
  call,
  evidence,
}: {
  call: ToolCall;
  evidence?: Evidence;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`tool-row ${call.success === false ? "failed" : ""}`}>
      <button className="tool-summary" onClick={() => setOpen(!open)}>
        {open ? <ChevronDown /> : <ChevronRight />}
        <span className="timeline-kind">TOOL</span>
        <code>{call.tool_name}</code>
        <Status value={call.success === false ? "FAILED" : "SUCCESS"} />
        <small>{call.duration_ms?.toFixed(1) ?? "—"} ms</small>
      </button>
      {open && (
        <div className="tool-detail">
          <div>
            <label>Arguments</label>
            <pre>{JSON.stringify(call.arguments, null, 2)}</pre>
          </div>
          <div>
            <label>Observation</label>
            <pre>{JSON.stringify(evidence?.observation ?? {}, null, 2)}</pre>
          </div>
          {call.error && (
            <p className="bad">
              {call.error_category}: {call.error} · retry {call.retry_count}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
export function Verification({ incident }: { incident: Incident }) {
  if (!incident.verification_result) return null;
  const calls = incident.verification_result.tool_call_ids
    .map((id) => incident.tool_calls.find((c) => c.id === id))
    .filter(Boolean) as ToolCall[];
  return (
    <section
      className={`verification ${incident.verification_result.successful ? "passed" : "failed"}`}
    >
      <div className="section-title">
        {incident.verification_result.successful ? (
          <CheckCircle2 />
        ) : (
          <AlertTriangle />
        )}
        <div>
          <span>RECOVERY VERIFICATION</span>
          <h3>{incident.verification_result.summary}</h3>
        </div>
      </div>
      {calls.map((c) => (
        <div className="check" key={c.id}>
          {c.success ? "✓" : "×"} {c.tool_name.replaceAll("_", " ")}
        </div>
      ))}
    </section>
  );
}
