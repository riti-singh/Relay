import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { NetworkMap, ToolRow, Verification } from "./components";
import App from "./App";
import type { Incident, Topology } from "./types";
vi.mock("cytoscape", () => ({
  default: vi.fn(() => ({
    on: vi.fn(),
    destroy: vi.fn(),
    getElementById: vi.fn(() => ({ select: vi.fn() })),
  })),
}));
const topology: Topology = {
  devices: [
    {
      id: "branch-03",
      name: "Branch 03",
      kind: "branch-router",
      interfaces: [{ name: "wan0", admin_up: true, operational_up: true }],
      routes: {},
      logs: [],
      config: {},
      baseline_config: {},
      acl_rules: [],
    },
  ],
  links: [],
};
describe("Relay console", () => {
  it("renders routed navigation", () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("Overview")).toBeInTheDocument();
    expect(screen.getByText("Agent Runs")).toBeInTheDocument();
  });
  it("handles topology data", () => {
    render(<NetworkMap topology={topology} />);
    expect(
      screen.getByLabelText("Interactive network topology"),
    ).toBeInTheDocument();
  });
  it("renders expandable tool observations", () => {
    render(
      <ToolRow
        call={{
          id: "1",
          tool_name: "ping",
          arguments: { destination: "payments-api" },
          risk: "READ_ONLY",
          state_changing: false,
          started_at: new Date().toISOString(),
          duration_ms: 2,
          success: true,
          retry_count: 0,
        }}
        evidence={{
          id: "e",
          tool_call_id: "1",
          summary: "reachable",
          observation: { reachable: true },
          is_verification: false,
          recorded_at: new Date().toISOString(),
        }}
      />,
    );
    expect(screen.getByText("ping")).toBeInTheDocument();
  });
  it("renders verification state", () => {
    render(
      <Verification
        incident={
          {
            verification_result: {
              successful: true,
              summary: "Connectivity restored",
              tool_call_ids: [],
              recorded_at: new Date().toISOString(),
            },
            tool_calls: [],
          } as unknown as Incident
        }
      />,
    );
    expect(screen.getByText("Connectivity restored")).toBeInTheDocument();
  });
});
