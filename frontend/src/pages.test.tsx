import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Evaluations, Home, IncidentPage, Incidents } from "./pages";
vi.mock("cytoscape", () => ({
  default: vi.fn(() => ({
    on: vi.fn(),
    destroy: vi.fn(),
    getElementById: vi.fn(() => ({ select: vi.fn() })),
  })),
}));
afterEach(() => vi.restoreAllMocks());
describe("data views", () => {
  it("explains Relay and provides dismissible first-run guidance", async () => {
    render(<MemoryRouter><Home /></MemoryRouter>);
    expect(screen.getByText("Understand the failure. Approve the change. Verify recovery.")).toBeInTheDocument();
    expect(screen.getByText("Your first investigation")).toBeInTheDocument();
    expect(screen.getByText("Start an investigation")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Dismiss guide"));
    expect(screen.getByText("Show first-run guide")).toBeInTheDocument();
  });
  it("creates an incident from a scenario", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.endsWith("/scenarios"))
          return new Response(
            JSON.stringify([
              {
                id: "interface-disabled",
                name: "Interface Disabled",
                description: "Branch is isolated",
                source_device: "branch-03",
                destination_device: "payments-api",
              },
            ]),
            { status: 200 },
          );
        if (url.endsWith("/incidents") && init?.method === "POST")
          return new Response(JSON.stringify({ id: "abc" }), { status: 200 });
        return new Response(JSON.stringify([]), { status: 200 });
      });
    render(
      <MemoryRouter>
        <Incidents />
      </MemoryRouter>,
    );
    await userEvent.click(await screen.findByText("Interface Disabled"));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/incidents"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
  it("renders actual evaluation results", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          summary: {
            root_cause_accuracy: 1,
            remediation_accuracy: 1,
            resolution_success_rate: 1,
            safety_violation_rate: 0,
            average_tool_calls: 11,
            average_investigation_steps: 13,
          },
          scenarios: [
            {
              scenario: "dns-failure",
              root_cause_accurate: true,
              remediation_accurate: true,
              resolved: true,
              safety_violations: 0,
              diagnostic_tool_calls: 11,
              investigation_steps: 13,
              failed_tool_recovered: true,
              repeated_action_rate: 0,
            },
          ],
          planner: "deterministic",
        }),
        { status: 200 },
      ),
    );
    render(
      <MemoryRouter>
        <Evaluations />
      </MemoryRouter>,
    );
    expect(await screen.findByText("DNS Failure")).toBeInTheDocument();
    expect(screen.getAllByText("100%")).toHaveLength(3);
  });
  it("renders hypotheses and approves only the proposed action", async () => {
    const now = new Date().toISOString();
    const incident = {
      id: "case-1",
      title: "Interface Disabled",
      description: "Branch isolated",
      source_device: "branch-03",
      destination_device: "payments-api",
      scenario: "interface-disabled",
      status: "AWAITING_APPROVAL",
      created_at: now,
      updated_at: now,
      investigation_plan: [],
      investigation_summary: "",
      investigation_runs: [],
      actions: [],
      events: [],
      tool_calls: [],
      evidence: [],
      hypotheses: [
        {
          id: "h1",
          statement: "core-router-02/eth1 is administratively disabled",
          suspected_component: "core-router-02/eth1",
          confidence: 0.98,
          supporting_evidence_ids: ["e1"],
          contradicting_evidence_ids: [],
          status: "CONFIRMED",
          history: [],
        },
      ],
      proposed_remediation: {
        id: "r1",
        description: "Enable branch uplink",
        tool_name: "set_interface_admin_state",
        arguments: {
          device_id: "core-router-02",
          interface_name: "eth1",
          admin_up: true,
        },
        impactful: true,
      },
      remediation_history: [],
      approval_state: "PENDING",
    };
    const topology = { devices: [], links: [] };
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.endsWith("/capabilities"))
          return new Response(
            JSON.stringify({
              deterministic_planner: true,
              ai_planner: false,
              max_investigation_steps: 20,
            }),
            { status: 200 },
          );
        if (url.includes("/network/topology"))
          return new Response(JSON.stringify(topology), { status: 200 });
        if (init?.method === "POST")
          return new Response(
            JSON.stringify({ ...incident, status: "RESOLVED" }),
            { status: 200 },
          );
        return new Response(JSON.stringify(incident), { status: 200 });
      });
    render(
      <MemoryRouter initialEntries={["/incidents/case-1"]}>
        <Routes>
          <Route path="/incidents/:id" element={<IncidentPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(
      await screen.findAllByText(
        "core-router-02/eth1 is administratively disabled",
      ),
    ).toHaveLength(2);
    expect(screen.getByText(/set_interface_admin_state/)).toBeInTheDocument();
    await userEvent.click(screen.getByText("Approve Remediation"));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/remediations/r1/approve"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
  it("renders evidence provenance with freshness badges and reproducible source links", async () => {
    const now = new Date().toISOString();
    const incident = {
      id: "case-2",
      title: "Prefix unreachable",
      description: "Public reachability degraded",
      source_device: "probes",
      destination_device: "193.0.14.129",
      scenario: "observe-ripe",
      operating_mode: "OBSERVE",
      status: "INVESTIGATING",
      created_at: now,
      updated_at: now,
      investigation_plan: [],
      investigation_summary: "",
      investigation_runs: [],
      actions: [],
      events: [],
      tool_calls: [],
      evidence: [
        {
          id: "e-atlas",
          tool_call_id: "t1",
          summary: "Ping loss observed from 7 of 10 probes",
          observation: { target: "193.0.14.129", loss_percent: 70 },
          is_verification: false,
          recorded_at: now,
          status: "SUCCESS",
          provenance: {
            source_type: "ripe_atlas",
            adapter: "ripe-atlas",
            resource_id: "193.0.14.129",
            observed_at: now,
            collected_at: now,
            freshness: "FRESH",
            measurement: "ping",
            source_metadata: {
              measurement_id: 1001,
              measurement_type: "ping",
              measurement_url: "https://atlas.ripe.net/measurements/1001/",
              probes_total: 10,
              probes_affected: 7,
            },
          },
        },
        {
          id: "e-stat",
          tool_call_id: "t2",
          summary: "Prefix visibility dropped in BGP",
          observation: { prefix: "193.0.0.0/21" },
          is_verification: false,
          recorded_at: now,
          status: "STALE",
          provenance: {
            source_type: "ripestat",
            adapter: "ripestat-composite",
            resource_id: "193.0.0.0/21",
            observed_at: now,
            collected_at: now,
            freshness: "STALE",
            source_metadata: {
              routing_status_url: "https://stat.ripe.net/data/routing-status/data.json?resource=193.0.0.0/21",
              prefix_overview_url: "https://stat.ripe.net/data/prefix-overview/data.json?resource=193.0.0.0/21",
              bgp_updates_url: "https://stat.ripe.net/data/bgp-updates/data.json?resource=193.0.0.0/21",
            },
          },
        },
      ],
      hypotheses: [],
      remediation_history: [],
      approval_state: "NONE",
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/capabilities"))
        return new Response(
          JSON.stringify({ deterministic_planner: true, ai_planner: false, max_investigation_steps: 20 }),
          { status: 200 },
        );
      if (url.includes("/network/topology"))
        return new Response(JSON.stringify({ devices: [], links: [] }), { status: 200 });
      return new Response(JSON.stringify(incident), { status: 200 });
    });
    render(
      <MemoryRouter initialEntries={["/incidents/case-2"]}>
        <Routes>
          <Route path="/incidents/:id" element={<IncidentPage />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByText("Ping loss observed from 7 of 10 probes");
    const atlas = screen.getByRole("link", { name: /RIPE Atlas measurement 1001/ });
    expect(atlas).toHaveAttribute("href", "https://atlas.ripe.net/measurements/1001/");
    expect(atlas).toHaveAttribute("target", "_blank");
    expect(screen.getByText("7 / 10 probes affected")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Routing status/ })).toHaveAttribute(
      "href",
      expect.stringContaining("stat.ripe.net/data/routing-status"),
    );
    expect(screen.getByRole("link", { name: /Prefix overview/ })).toHaveAttribute(
      "href",
      expect.stringContaining("stat.ripe.net"),
    );
    expect(screen.getByRole("link", { name: /BGP updates/ })).toHaveAttribute(
      "href",
      expect.stringContaining("stat.ripe.net"),
    );
    expect(screen.getByText("FRESH")).toHaveClass("status", "s-fresh");
    expect(screen.getAllByText("STALE").some((el) => el.classList.contains("s-stale"))).toBe(true);
    expect(screen.getByText("ripe_atlas")).toBeInTheDocument();
    expect(screen.getByText("ripestat")).toBeInTheDocument();
  });
});
