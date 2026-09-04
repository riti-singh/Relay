export type Status =
  | "OPEN"
  | "INVESTIGATING"
  | "AWAITING_APPROVAL"
  | "REMEDIATING"
  | "VERIFYING"
  | "RESOLVED"
  | "BLOCKED"
  | "FAILED";
export interface InterfaceState {
  name: string;
  admin_up: boolean;
  operational_up: boolean;
  ip_address?: string;
}
export interface Device {
  id: string;
  name: string;
  kind: string;
  interfaces: InterfaceState[];
  routes: Record<string, string>;
  logs: string[];
  config: Record<string, unknown>;
  baseline_config: Record<string, unknown>;
  acl_rules: Record<string, unknown>[];
}
export interface Link {
  device_a: string;
  interface_a: string;
  device_b: string;
  interface_b: string;
  latency_ms: number;
  packet_loss_percent: number;
}
export interface Topology {
  devices: Device[];
  links: Link[];
}
export interface ToolCall {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  risk: string;
  state_changing: boolean;
  started_at: string;
  completed_at?: string;
  duration_ms?: number;
  success?: boolean;
  retry_count: number;
  error_category?: string;
  error?: string;
}
export interface Evidence {
  id: string;
  tool_call_id: string;
  summary: string;
  observation: Record<string, unknown>;
  is_verification: boolean;
  recorded_at: string;
}
export interface Revision {
  confidence: number;
  status: string;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  summary: string;
  recorded_at: string;
}
export interface Hypothesis {
  id: string;
  statement: string;
  suspected_component?: string;
  confidence: number;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  status: string;
  history: Revision[];
}
export interface Decision {
  kind: string;
  summary: string;
  tool_name?: string;
  arguments: Record<string, unknown>;
  confidence?: number;
  hypothesis?: string;
}
export interface Action {
  id: string;
  run_id: string;
  step: number;
  decision: Decision;
  tool_call_id?: string;
  successful: boolean;
  error?: string;
  created_at: string;
}
export interface Run {
  id: string;
  plan: string[];
  started_at: string;
  completed_at?: string;
  outcome?: string;
  steps_used: number;
}
export interface Remediation {
  id: string;
  description: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  expected_root_cause?: string;
  impactful: boolean;
}
export interface Incident {
  id: string;
  title: string;
  description: string;
  source_device: string;
  destination_device: string;
  scenario: string;
  status: Status;
  created_at: string;
  updated_at: string;
  investigation_plan: string[];
  investigation_summary: string;
  investigation_runs: Run[];
  actions: Action[];
  events: {
    run_id: string;
    event_type: string;
    summary: string;
    timestamp: string;
  }[];
  tool_calls: ToolCall[];
  evidence: Evidence[];
  hypotheses: Hypothesis[];
  proposed_remediation?: Remediation;
  remediation_history: Remediation[];
  approval_state: string;
  verification_result?: {
    successful: boolean;
    summary: string;
    tool_call_ids: string[];
    recorded_at: string;
  };
}
export interface Scenario {
  id: string;
  name: string;
  description: string;
  source_device: string;
  destination_device: string;
}
export interface Evaluation {
  summary: Record<string, number>;
  scenarios: Array<{
    scenario: string;
    root_cause_accurate: boolean;
    remediation_accurate: boolean;
    resolved: boolean;
    safety_violations: number;
    diagnostic_tool_calls: number;
    investigation_steps: number;
    failed_tool_recovered: boolean;
    repeated_action_rate: number;
  }>;
  planner: string;
}
