import type { Evaluation, Incident, Run, Scenario, Topology } from "./types";
const base = import.meta.env.VITE_API_URL ?? "/api";
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let message = `Relay API returned ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail ?? message;
    } catch {
      // Preserve the status fallback for non-JSON proxy errors.
    }
    throw new ApiError(message, response.status);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("Relay returned a malformed response", 502);
  }
}
export const api = {
  incidents: () => request<Incident[]>("/incidents"),
  incident: (id: string) => request<Incident>(`/incidents/${id}`),
  scenarios: () => request<Scenario[]>("/scenarios"),
  topology: (id?: string) =>
    request<Topology>(
      id ? `/network/topology/incident/${id}` : "/network/topology",
    ),
  capabilities: () =>
    request<{
      deterministic_planner: boolean;
      ai_planner: boolean;
      agent_provider?: string;
      max_investigation_steps: number;
    }>("/capabilities"),
  dashboard: () => request<Record<string, unknown>>("/dashboard/summary"),
  evaluations: () => request<Evaluation>("/evaluations/latest"),
  runs: () => request<Record<string, unknown>[]>("/agent-runs"),
  create: (scenario: Scenario) =>
    request<Incident>("/incidents", {
      method: "POST",
      body: JSON.stringify({
        title: scenario.name,
        description: scenario.description,
        source_device: scenario.source_device,
        destination_device: scenario.destination_device,
        scenario: scenario.id,
      }),
    }),
  start: (id: string, planner: string) =>
    request<Run>(`/incidents/${id}/agent/start`, {
      method: "POST",
      body: JSON.stringify({ planner }),
    }),
  cancel: (incidentId: string, runId: string) =>
    request<Run>(`/incidents/${incidentId}/runs/${runId}/cancel`, { method: "POST" }),
  events: (incidentId: string, runId: string, after = 0) =>
    new EventSource(`${base}/incidents/${incidentId}/runs/${runId}/events?after=${after}`),
  approve: (incidentId: string, r: Remediation) =>
    request<Incident>(`/incidents/${incidentId}/remediations/${r.id}/approve`, {
      method: "POST",
      body: JSON.stringify({
        approved_by: "relay-console",
        remediation_id: r.id,
      }),
    }),
  reject: (incidentId: string, r: Remediation) =>
    request<Incident>(`/incidents/${incidentId}/remediations/${r.id}/reject`, {
      method: "POST",
      body: JSON.stringify({
        rejected_by: "relay-console",
        reason: "Operator requested further investigation",
      }),
    }),
};
import type { Remediation } from "./types";
