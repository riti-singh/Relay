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
});
