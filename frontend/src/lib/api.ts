export function resolveApiBaseUrl(value?: string): string {
  const candidate = value?.trim() || "http://127.0.0.1:8000";
  const parsed = new URL(candidate);
  if (
    !["http:", "https:"].includes(parsed.protocol)
    || parsed.username
    || parsed.password
    || parsed.search
    || parsed.hash
  ) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL must be a public HTTP(S) base URL");
  }
  return candidate.replace(/\/$/, "");
}

export const API_BASE_URL = resolveApiBaseUrl(
  process.env.NEXT_PUBLIC_API_BASE_URL,
);

export type Health = {
  status: string;
  service: string;
  paper_trading: boolean;
};

export type AgentStatus = {
  enabled: boolean;
  mode: "OBSERVE" | "AUTONOMOUS_PAPER";
  cycle_seconds: number;
  max_candidates_per_cycle: number;
  paper: true;
  paper_execution_enabled: boolean;
  new_entries_enabled: boolean;
  running: boolean;
  last_cycle_status: string | null;
  last_cycle_started_at: string | null;
  last_cycle_finished_at: string | null;
};

export type Candidate = {
  id: number;
  symbol: string;
  side: string;
  strategy: string;
  entry_price: number;
  price_change_pct: number;
  volume_ratio: number;
  scout_score: number;
  source: string;
  status: string;
  created_at: string;
};

export type DecisionListItem = {
  id: number;
  candidate_id: number;
  symbol: string;
  analyst_confidence: number;
  critic_adjustment: number;
  adjusted_confidence: number;
  critic_verdict: "PASS" | "CHALLENGE";
  critic_provider: "nvidia" | "azure-fallback";
  degraded_mode: boolean;
  reward_risk_ratio: number;
  risk_score: number;
  decision: "ACCEPT" | "REJECT";
  reasons: string[];
  created_at: string;
  order_submitted: false;
};

export type DecisionDetail = {
  id: number;
  candidate_id: number;
  analyst: {
    provider: "azure";
    model: string;
    symbol: string;
    direction: "LONG";
    thesis: string;
    confidence: number;
    entry_price: number;
    stop_loss: number;
    target_price: number;
    horizon_minutes: number;
    invalidation: string;
    evidence: string[];
  };
  critic: {
    provider: "nvidia" | "azure-fallback";
    model: string;
    verdict: "PASS" | "CHALLENGE";
    confidence_adjustment: number;
    thesis_consistency: number;
    concerns: string[];
    degraded_mode: boolean;
  };
  consensus: {
    original_confidence: number;
    critic_adjustment: number;
    adjusted_confidence: number;
  };
  risk: {
    decision: "ACCEPT" | "REJECT";
    reward_risk_ratio: number;
    proposed_position_pct: number;
    risk_score: number;
    reasons: string[];
  };
  created_at: string;
  order_submitted: false;
};

export type Execution = {
  id: number;
  candidate_id: number;
  risk_decision_id: number;
  symbol: string;
  side: string;
  requested_notional: number;
  alpaca_order_id: string | null;
  status: string;
  filled_qty: number | null;
  filled_avg_price: number | null;
  submitted_at: string | null;
  created_at: string;
  paper: true;
};

export type TradeExit = {
  id: number;
  executed_trade_id: number;
  candidate_id: number;
  risk_decision_id: number;
  symbol: string;
  reason: "TAKE_PROFIT" | "STOP_LOSS" | "TIME_EXIT";
  trigger_price: number;
  target_price: number;
  stop_loss: number;
  horizon_minutes: number;
  requested_qty: number;
  alpaca_order_id: string | null;
  status: string;
  filled_qty: number | null;
  filled_avg_price: number | null;
  triggered_at: string;
  submitted_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
  paper: true;
};

export type ShadowTrade = {
  id: number;
  candidate_id: number;
  risk_decision_id: number;
  symbol: string;
  side: string;
  hypothetical_entry: number;
  hypothetical_notional: number;
  stop_loss: number;
  target_price: number;
  horizon_minutes: number;
  status: string;
  opened_at: string;
  evaluation_due_at: string;
  order_submitted: false;
};

export type Outcome = {
  id: number;
  source_type: "SHADOW" | "EXECUTED";
  source_id: number;
  candidate_id: number;
  risk_decision_id: number;
  symbol: string;
  decision: "ACCEPT" | "REJECT";
  entry_price: number;
  evaluation_price: number;
  quantity: number;
  notional: number;
  pnl_pct: number;
  pnl_amount: number;
  due_at: string;
  evaluated_at: string;
  price_source: string;
  created_at: string;
};

export type Classification =
  | "MISSED_ALPHA"
  | "AVOIDED_LOSS"
  | "CORRECT_EXECUTION"
  | "BAD_EXECUTION";

export type RegretEvent = {
  id: number;
  outcome_id: number;
  candidate_id: number;
  risk_decision_id: number;
  symbol: string;
  decision: "ACCEPT" | "REJECT";
  classification: Classification;
  pnl_pct: number;
  pnl_amount: number;
  decision_value: number;
  created_at: string;
};

export type RegretMetrics = {
  total_decisions_evaluated: number;
  decision_value: number;
  missed_alpha: number;
  avoided_loss: number;
  correct_execution_value: number;
  bad_execution_loss: number;
  classification_counts: Record<Classification, number>;
};

export type DashboardData = {
  health: Health | null;
  agentStatus: AgentStatus | null;
  candidates: Candidate[];
  decisions: DecisionListItem[];
  executions: Execution[];
  exits: TradeExit[];
  shadowTrades: ShadowTrade[];
  outcomes: Outcome[];
  regretEvents: RegretEvent[];
  metrics: RegretMetrics;
};

export type DashboardLoadResult = {
  data: DashboardData;
  errors: string[];
};

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });

  if (!response.ok) {
    throw new ApiError(`Backend request failed for ${path}`, response.status);
  }

  return (await response.json()) as T;
}

export const api = {
  getHealth: (signal?: AbortSignal) => request<Health>("/health", signal),
  getAgentStatus: (signal?: AbortSignal) =>
    request<AgentStatus>("/api/agent/status", signal),
  getCandidates: (signal?: AbortSignal) =>
    request<Candidate[]>("/api/candidates", signal),
  getDecisions: (signal?: AbortSignal) =>
    request<DecisionListItem[]>("/api/decisions", signal),
  getDecision: (id: number, signal?: AbortSignal) =>
    request<DecisionDetail>(`/api/decisions/${id}`, signal),
  getExecutions: (signal?: AbortSignal) =>
    request<Execution[]>("/api/executions", signal),
  getExits: (signal?: AbortSignal) =>
    request<TradeExit[]>("/api/exits", signal),
  getShadowTrades: (signal?: AbortSignal) =>
    request<ShadowTrade[]>("/api/shadow-trades", signal),
  getOutcomes: (signal?: AbortSignal) =>
    request<Outcome[]>("/api/outcomes", signal),
  getRegretEvents: (signal?: AbortSignal) =>
    request<RegretEvent[]>("/api/regret-events", signal),
  getMetrics: (signal?: AbortSignal) =>
    request<RegretMetrics>("/api/regret/metrics", signal),
};

const emptyMetrics: RegretMetrics = {
  total_decisions_evaluated: 0,
  decision_value: 0,
  missed_alpha: 0,
  avoided_loss: 0,
  correct_execution_value: 0,
  bad_execution_loss: 0,
  classification_counts: {
    MISSED_ALPHA: 0,
    AVOIDED_LOSS: 0,
    CORRECT_EXECUTION: 0,
    BAD_EXECUTION: 0,
  },
};

export async function loadDashboardData(
  signal?: AbortSignal,
): Promise<DashboardLoadResult> {
  const errors: string[] = [];
  async function safely<T>(
    label: string,
    promise: Promise<T>,
    fallback: T,
  ): Promise<T> {
    try {
      return await promise;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      errors.push(label);
      return fallback;
    }
  }

  const [
    health,
    agentStatus,
    candidates,
    decisions,
    executions,
    exits,
    shadowTrades,
    outcomes,
    regretEvents,
    metrics,
  ] = await Promise.all([
    safely("health", api.getHealth(signal), null),
    safely("agent status", api.getAgentStatus(signal), null),
    safely("candidates", api.getCandidates(signal), []),
    safely("decisions", api.getDecisions(signal), []),
    safely("executions", api.getExecutions(signal), []),
    safely("exits", api.getExits(signal), []),
    safely("shadow trades", api.getShadowTrades(signal), []),
    safely("outcomes", api.getOutcomes(signal), []),
    safely("regret events", api.getRegretEvents(signal), []),
    safely("regret metrics", api.getMetrics(signal), emptyMetrics),
  ]);

  return {
    data: {
      health,
      agentStatus,
      candidates,
      decisions,
      executions,
      exits,
      shadowTrades,
      outcomes,
      regretEvents,
      metrics,
    },
    errors,
  };
}
