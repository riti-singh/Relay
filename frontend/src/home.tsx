import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, Fingerprint, Lock, Radio, Search, Zap } from "lucide-react";

const stages = [
  "Incident",
  "Investigation",
  "Diagnostic tools",
  "Evidence",
  "Hypothesis",
  "Root cause",
  "Human approval",
  "Remediation",
  "Verification",
];

const path = [
  { id: "branch-03", x: 40, y: 150, label: "branch-03" },
  { id: "edge-router-01", x: 190, y: 70, label: "edge-router-01" },
  { id: "core-router-02", x: 340, y: 150, label: "core-router-02" },
  { id: "dc-switch-01", x: 490, y: 70, label: "dc-switch-01" },
  { id: "payments-api", x: 640, y: 150, label: "payments-api" },
];

const toolCalls = [
  { tool: "ping", args: "branch-03 → payments-api", result: "100% loss" },
  { tool: "traceroute", args: "branch-03 → payments-api", result: "stops at edge-router-01" },
  { tool: "get_interfaces", args: "core-router-02", result: "eth1 admin_state=down" },
  { tool: "get_link_stats", args: "edge-router-01 ↔ core-router-02", result: "no traffic" },
];

const evidence = [
  { kind: "REACHABILITY", text: "branch-03 cannot reach payments-api", fresh: "2s" },
  { kind: "PATH", text: "Traffic terminates at edge-router-01", fresh: "4s" },
  { kind: "INTERFACE", text: "core-router-02/eth1 administratively down", fresh: "6s" },
  { kind: "CONFIG", text: "eth1 last changed 14 minutes ago", fresh: "6s" },
];

const chapters = [
  {
    kicker: "01 · THE FAILURE",
    title: "A branch goes dark. Nobody knows why yet.",
    body:
      "At 02:14, branch-03 stops reaching payments-api. The alert says a great deal about symptoms and nothing about causes. Relay opens an incident with only what an operator would see: a source, a destination, and a path that no longer carries traffic.",
    icon: Radio,
  },
  {
    kicker: "02 · THE INVESTIGATION",
    title: "Relay asks the network questions, one safe tool at a time.",
    body:
      "Every step is a typed, read-only diagnostic call: ping, traceroute, interface state, link statistics. Relay chooses the next question from what it has already learned, and never runs a tool it cannot validate. Nothing changes on the network while it looks.",
    icon: Search,
  },
  {
    kicker: "03 · THE EVIDENCE",
    title: "Observations become facts with provenance and freshness.",
    body:
      "Each tool result is recorded as evidence: where it came from, when it was gathered, and what it supports or contradicts. Hypotheses gain and lose confidence as the evidence accumulates, and the losing theories stay visible so you can see why they were rejected.",
    icon: Zap,
  },
  {
    kicker: "04 · THE APPROVAL GATE",
    title: "The fix is proposed. A human decides.",
    body:
      "Relay fingerprints the exact tool and arguments it intends to run. You approve that precise action or nothing at all. Change one argument and the approval is void. Autonomy ends where the network begins to change.",
    icon: Fingerprint,
  },
  {
    kicker: "05 · THE PROOF",
    title: "Recovery is verified, not assumed.",
    body:
      "After remediation, Relay reruns the connectivity checks that defined the incident. It resolves the case only when the path carries traffic again. Every call, observation, hypothesis, and approval remains replayable afterward.",
    icon: Check,
  },
];

function useReveal<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setShown(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && setShown(true)),
      { threshold: 0.35 },
    );
    io.observe(node);
    return () => io.disconnect();
  }, []);
  return { ref, shown };
}

function Chapter({ index, kicker, title, body, icon: Icon, children }: (typeof chapters)[number] & { index: number; children: React.ReactNode }) {
  const { ref, shown } = useReveal<HTMLElement>();
  return (
    <section ref={ref} className={`chapter ${shown ? "in" : ""}`} data-chapter={index}>
      <div className="chapter-text">
        <span className="kicker">{kicker}</span>
        <h2><Icon /> {title}</h2>
        <p>{body}</p>
      </div>
      <div className="chapter-stage">{children}</div>
    </section>
  );
}

function PathScene({ broken, healed }: { broken: boolean; healed?: boolean }) {
  return (
    <svg className={`path-scene ${broken ? "broken" : ""} ${healed ? "healed" : ""}`} viewBox="0 0 680 220" aria-hidden>
      {path.slice(1).map((n, i) => {
        const p = path[i];
        const failing = i === 1;
        return (
          <line key={n.id} x1={p.x} y1={p.y} x2={n.x} y2={n.y} className={`link ${failing ? "link-fail" : ""}`} />
        );
      })}
      <circle className="packet" r="5">
        <animateMotion dur="4s" repeatCount="indefinite" path={`M${path.map((p) => `${p.x} ${p.y}`).join(" L")}`} />
      </circle>
      {path.map((n, i) => (
        <g key={n.id} className={`node ${i === 2 ? "node-suspect" : ""}`} transform={`translate(${n.x} ${n.y})`}>
          <circle r="17" />
          <text y="36" textAnchor="middle">{n.label}</text>
        </g>
      ))}
    </svg>
  );
}

function Terminal() {
  return (
    <div className="term">
      <div className="term-bar"><i /><i /><i /><span>deterministic planner · step 4 / 20</span></div>
      {toolCalls.map((c, i) => (
        <div className="term-line" style={{ animationDelay: `${i * 0.9}s` }} key={c.tool}>
          <span className="term-prompt">›</span>
          <code>{c.tool}</code>
          <span className="term-args">{c.args}</span>
          <span className="term-result" style={{ animationDelay: `${i * 0.9 + 0.5}s` }}>{c.result}</span>
        </div>
      ))}
    </div>
  );
}

function EvidenceStage() {
  return (
    <div className="evidence-stage">
      <div className="evidence-list">
        {evidence.map((e, i) => (
          <div className="ev" style={{ animationDelay: `${i * 0.5}s` }} key={e.kind}>
            <span>{e.kind}</span>
            <b>{e.text}</b>
            <small>{e.fresh} old</small>
          </div>
        ))}
      </div>
      <div className="hypotheses-stage">
        {[
          { h: "core-router-02/eth1 is administratively disabled", c: 0.98, win: true },
          { h: "Static route to payments-api is missing", c: 0.12 },
          { h: "DNS resolution failure at branch-03", c: 0.04 },
        ].map((x, i) => (
          <div className={`hyp ${x.win ? "hyp-win" : ""}`} key={x.h} style={{ animationDelay: `${1.6 + i * 0.3}s` }}>
            <div><b>{x.h}</b><span>{x.win ? "CONFIRMED" : "REJECTED"}</span></div>
            <i style={{ ["--c" as string]: x.c, animationDelay: `${2 + i * 0.3}s` }} />
          </div>
        ))}
      </div>
    </div>
  );
}

function ApprovalStage() {
  return (
    <div className="approval-stage">
      <div className="approval-card">
        <div className="approval-card-head"><Lock /> EXACT-ACTION APPROVAL REQUIRED</div>
        <pre>{`set_interface_admin_state
  device_id:      core-router-02
  interface_name: eth1
  admin_up:       true`}</pre>
        <div className="fingerprint"><Fingerprint /><span>sha256 · 9f2c…41ab</span></div>
        <div className="approval-card-actions"><span className="approve-pill">Approve exactly this</span><span>Reject</span></div>
      </div>
      <div className="approval-note">If any argument changes, the fingerprint changes and the approval no longer applies.</div>
    </div>
  );
}

function VerifyStage() {
  return (
    <div className="verify-stage">
      <PathScene broken={false} healed />
      <div className="verify-checks">
        {["ping branch-03 → payments-api", "traceroute completes end to end", "eth1 admin_state=up", "incident RESOLVED"].map((c, i) => (
          <div key={c} style={{ animationDelay: `${0.4 + i * 0.5}s` }}><Check /> {c}</div>
        ))}
      </div>
    </div>
  );
}

export function Home() {
  const [showGuide, setShowGuide] = useState(() => globalThis.localStorage?.getItem("relay-onboarding-dismissed") !== "true");
  const dismiss = () => { globalThis.localStorage?.setItem("relay-onboarding-dismissed", "true"); setShowGuide(false); };
  const [stage, setStage] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setStage((s) => (s + 1) % stages.length), 1800);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="page home">
      <section className="hero hero-story">
        <div>
          <span className="kicker"><i className="live-dot" />GUIDED NETWORK INCIDENT RESPONSE</span>
          <h1>Understand the failure. Approve the change. Verify recovery.</h1>
          <p>
            Relay is an incident responder for networks. When connectivity breaks, it investigates the way a careful engineer would: running read-only diagnostics, building an evidence trail, and narrowing to a root cause. Then it stops, shows you the exact change it wants to make, and waits. Nothing touches the network until you approve, and nothing is called fixed until Relay proves the path carries traffic again.
          </p>
          <div className="hero-actions"><a className="primary" href="/incidents">Start an investigation <ArrowRight /></a><a href="/incidents">Explore a sample incident</a></div>
        </div>
        <PathScene broken />
      </section>

      <section className="workflow workflow-live" aria-label="Relay investigation workflow">
        {stages.map((step, index) => (
          <div key={step} className={index === stage ? "active" : index < stage ? "past" : ""}>
            <span>{index + 1}</span><b>{step}</b>{index < stages.length - 1 && <ArrowRight />}
          </div>
        ))}
      </section>

      <div className="story">
        <Chapter index={0} {...chapters[0]}>
          <div className="alert-card">
            <span className="kicker">INCIDENT OPENED · 02:14:07</span>
            <b>branch-03 cannot reach payments-api</b>
            <small>Symptoms only. Root cause unknown. No changes made.</small>
            <div className="alert-pulse" />
          </div>
        </Chapter>
        <Chapter index={1} {...chapters[1]}><Terminal /></Chapter>
        <Chapter index={2} {...chapters[2]}><EvidenceStage /></Chapter>
        <Chapter index={3} {...chapters[3]}><ApprovalStage /></Chapter>
        <Chapter index={4} {...chapters[4]}><VerifyStage /></Chapter>
      </div>

      {showGuide ? (
        <section className="onboarding panel">
          <div><span className="kicker">WELCOME TO RELAY</span><h2>Your first investigation</h2></div>
          <ol>
            <li>Choose a simulated network failure.</li>
            <li>Start a deterministic or AI Agent investigation.</li>
            <li>Watch Relay gather evidence and revise hypotheses.</li>
            <li>Review the proposed fix and approve the exact action.</li>
            <li>Watch Relay verify that connectivity recovered.</li>
          </ol>
          <button onClick={dismiss}>Dismiss guide</button>
        </section>
      ) : (
        <button className="rediscover" onClick={() => setShowGuide(true)}>Show first-run guide</button>
      )}

      <section className="product-areas panel">
        <h2>Explore Relay</h2>
        <div>
          <a href="/overview"><b>Operations summary</b><span>System-wide operational health</span></a>
          <a href="/incidents"><b>Incident workspace</b><span>Inject failures and investigate</span></a>
          <a href="/topology"><b>Network map</b><span>See devices, links, and evidence</span></a>
          <a href="/runs"><b>Run history</b><span>Replay durable executions</span></a>
          <a href="/evaluations"><b>Quality evaluation</b><span>Measure accuracy and safety</span></a>
        </div>
      </section>
    </div>
  );
}
