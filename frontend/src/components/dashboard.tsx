"use client";

import {
  AlertCircle,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  History,
  RefreshCw,
  RotateCcw,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  API_BASE_URL,
  api,
  loadDashboardData,
  type Candidate,
  type Classification,
  type DashboardData,
  type DecisionDetail,
  type DecisionListItem,
  type Outcome,
  type RegretEvent,
} from "@/lib/api";
import {
  CLASSIFICATION_META,
  criticModeLabel,
  formatCurrency,
  formatPercent,
  formatSignedCurrency,
  formatSignedPercent,
  toUserMessage,
} from "@/lib/presentation";

type FeedFilter = "ALL" | "ACCEPT" | "REJECT" | "FAILURES";
type LoadState = "loading" | "ready" | "offline";

const FILTER_LABELS: Record<FeedFilter, string> = {
  ALL: "All",
  ACCEPT: "Accepted",
  REJECT: "Rejected",
  FAILURES: "Failures",
};

function timeLabel(value?: string): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function classificationTheme(classification: Classification) {
  return {
    MISSED_ALPHA: {
      accent: "text-amber-300",
      soft: "bg-amber-300/[0.06]",
      rule: "border-amber-300/35",
      line: "#f3ba63",
    },
    AVOIDED_LOSS: {
      accent: "text-blue-300",
      soft: "bg-blue-300/[0.06]",
      rule: "border-blue-300/35",
      line: "#76a9fa",
    },
    CORRECT_EXECUTION: {
      accent: "text-emerald-300",
      soft: "bg-emerald-300/[0.06]",
      rule: "border-emerald-300/35",
      line: "#6ee7b7",
    },
    BAD_EXECUTION: {
      accent: "text-red-300",
      soft: "bg-red-300/[0.06]",
      rule: "border-red-300/35",
      line: "#fca5a5",
    },
  }[classification];
}

function classificationValueLabel(event: RegretEvent): string {
  const value = formatSignedCurrency(event.decision_value);
  if (event.classification === "AVOIDED_LOSS") return `${value} protected`;
  if (event.classification === "CORRECT_EXECUTION") return `${value} created`;
  return `${value} decision value`;
}

function decisionTone(decision: "ACCEPT" | "REJECT"): string {
  return decision === "ACCEPT" ? "text-slate-200" : "text-slate-400";
}

function MetricDatum({
  label,
  value,
  note,
  tone = "neutral",
}: {
  label: string;
  value: string;
  note: string;
  tone?: "blue" | "amber" | "neutral";
}) {
  const valueTone =
    tone === "blue"
      ? "text-blue-300"
      : tone === "amber"
        ? "text-amber-300"
        : "text-slate-100";

  return (
    <div className="border-t border-white/[0.09] pt-3.5">
      <dt className="text-sm text-slate-400">{label}</dt>
      <dd className={`mt-2 font-mono text-2xl font-medium tabular-nums ${valueTone}`}>{value}</dd>
      <dd className="mt-1.5 text-xs leading-5 text-slate-600">{note}</dd>
    </div>
  );
}

function SkeletonDashboard() {
  return (
    <main className="mx-auto w-full max-w-[1520px] px-5 pb-16 pt-7 sm:px-8" aria-busy="true">
      <div className="skeleton h-12 w-full rounded-md" />
      <div className="mt-10 grid gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="skeleton h-52 rounded-md" />
        <div className="grid grid-cols-2 gap-6">
          {[0, 1, 2, 3].map((item) => (
            <div className="skeleton h-24 rounded-md" key={item} />
          ))}
        </div>
      </div>
      <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="skeleton h-[470px] rounded-md" />
        <div className="skeleton h-[470px] rounded-md" />
      </div>
      <span className="sr-only">Loading decision intelligence</span>
    </main>
  );
}

function OfflineState({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-xl items-center px-6 py-20">
      <section className="w-full border-y border-white/10 py-12 text-center">
        <AlertCircle className="mx-auto size-6 text-red-300" />
        <p className="mt-6 text-sm text-slate-500">Backend offline</p>
        <h1 className="mt-2 text-3xl font-medium tracking-tight text-white">Decision data is unavailable</h1>
        <p className="mt-4 text-sm leading-6 text-slate-400">
          Start the REGRET API at <span className="font-mono text-slate-300">{API_BASE_URL}</span>, then retry.
          No cached or synthetic trading data is being shown.
        </p>
        <button
          className="mx-auto mt-7 flex items-center gap-2 border-b border-slate-500 pb-1.5 text-sm text-slate-200 transition hover:border-white hover:text-white"
          onClick={onRetry}
          type="button"
        >
          <RefreshCw className="size-4" /> Retry connection
        </button>
      </section>
    </main>
  );
}

function FeedRow({
  decision,
  candidate,
  selected,
  onSelect,
}: {
  decision: DecisionListItem;
  candidate?: Candidate;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      aria-pressed={selected}
      className={`relative w-full border-b border-white/[0.06] py-3.5 pl-4 pr-2 text-left transition hover:bg-white/[0.02] ${
        selected ? "bg-white/[0.035] before:absolute before:inset-y-3 before:left-0 before:w-px before:bg-indigo-300" : ""
      }`}
      onClick={onSelect}
      type="button"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2.5">
            <span className="font-mono text-sm font-semibold text-slate-100">{decision.symbol}</span>
            <span className={`text-[10px] font-medium ${decisionTone(decision.decision)}`}>{decision.decision}</span>
          </div>
          <p className="mt-1 truncate text-[11px] text-slate-600">
            {candidate?.strategy ?? "Decision review"} · {timeLabel(decision.created_at)}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="font-mono text-sm tabular-nums text-slate-200">{formatPercent(decision.adjusted_confidence)}</p>
          <p className="mt-1 text-[10px] text-slate-600">Adj. confidence</p>
        </div>
      </div>
      <p className="mt-2 text-[11px] text-slate-600">
        R:R {decision.reward_risk_ratio.toFixed(2)} <span className="mx-1.5 text-slate-800">/</span> Risk {decision.risk_score.toFixed(1)}
        {decision.degraded_mode && <span className="ml-2 text-violet-300/70">Fallback critic</span>}
      </p>
    </button>
  );
}

function FailureRow({ candidate }: { candidate: Candidate }) {
  return (
    <div className="border-b border-white/[0.06] py-3.5 pl-4 pr-2">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-baseline gap-2.5">
            <span className="font-mono text-sm font-semibold text-slate-400">{candidate.symbol}</span>
            <span className="text-[10px] text-slate-500">{candidate.status}</span>
          </div>
          <p className="mt-1 text-[11px] text-slate-600">{candidate.strategy} · {timeLabel(candidate.created_at)}</p>
        </div>
        <AlertCircle className="mt-0.5 size-3.5 shrink-0 text-slate-600" />
      </div>
      <p className="mt-2 text-[11px] text-slate-700">Stopped safely before risk or execution.</p>
    </div>
  );
}

function ReplayChart({
  outcome,
  replayKey,
  classification,
}: {
  outcome: Outcome;
  replayKey: number;
  classification: Classification;
}) {
  const move = Math.max(-58, Math.min(58, outcome.pnl_pct * 420));
  const endY = 98 - move;
  const color = classificationTheme(classification).line;

  return (
    <div className="terminal-grid relative mt-5 border-y border-white/[0.07] py-2">
      <svg
        aria-label={`Price moved from ${outcome.entry_price} to ${outcome.evaluation_price}`}
        className="h-48 w-full sm:h-52"
        key={replayKey}
        role="img"
        viewBox="0 0 700 200"
      >
        <line stroke="rgba(148,163,184,.12)" strokeDasharray="3 9" x1="40" x2="660" y1="98" y2="98" />
        <line className="replay-line" stroke={color} strokeLinecap="round" strokeWidth="2.5" x1="92" x2="608" y1="98" y2={endY} />
        <circle fill="#090c11" r="7" stroke="#8a93a2" strokeWidth="2.5" cx="92" cy="98" />
        <circle className="replay-dot" fill="#090c11" r="8" stroke={color} strokeWidth="3.5" cx="608" cy={endY} />
        <text fill="#727b89" fontSize="11" x="66" y="132">Entry</text>
        <text fill="#f0f3f7" fontFamily="monospace" fontSize="16" fontWeight="600" x="52" y="154">{formatCurrency(outcome.entry_price)}</text>
        <text fill="#727b89" fontSize="11" textAnchor="end" x="640" y={endY < 70 ? endY + 34 : endY - 30}>Evaluated</text>
        <text fill={color} fontFamily="monospace" fontSize="16" fontWeight="600" textAnchor="end" x="645" y={endY < 70 ? endY + 56 : endY - 9}>{formatCurrency(outcome.evaluation_price)}</text>
      </svg>
      <p className="px-1 text-[10px] leading-4 text-slate-700">Two recorded prices · vertical movement capped for legibility</p>
    </div>
  );
}

function ReplayPath({ stage, finalDecision }: { stage: number; finalDecision: "ACCEPT" | "REJECT" }) {
  const steps = ["Candidate", "Analyst", "Critic", "Consensus", "Risk", finalDecision, "Outcome", "Regret", "Value"];

  return (
    <div className="relative grid grid-cols-3 gap-y-4 border-t border-white/[0.07] px-5 py-4 sm:grid-cols-9 sm:px-7" aria-label="Decision replay progress">
      <div className="absolute left-7 right-7 top-[1.18rem] hidden border-t border-white/[0.07] sm:block" />
      {steps.map((step, index) => {
        const isCurrent = index === stage;
        const isPast = index < stage;
        return (
          <div className="relative min-w-0 text-center" key={`${step}-${index}`}>
            <span className={`relative z-10 mx-auto block size-2 rounded-full ${isCurrent ? "bg-white ring-4 ring-white/10" : isPast ? "bg-slate-600" : "border border-slate-700 bg-[#0a0d12]"}`} />
            <p className={`mt-2 truncate text-[10px] ${isCurrent ? "text-slate-100" : isPast ? "text-slate-500" : "text-slate-700"}`}>{step}</p>
          </div>
        );
      })}
    </div>
  );
}

function ReplaySurface({
  decision,
  outcome,
  event,
}: {
  decision?: DecisionListItem;
  outcome?: Outcome;
  event?: RegretEvent;
}) {
  const [replayKey, setReplayKey] = useState(0);
  const [stage, setStage] = useState(8);

  function replay() {
    setReplayKey((value) => value + 1);
    setStage(0);
    for (let nextStage = 1; nextStage <= 8; nextStage += 1) {
      window.setTimeout(() => setStage(nextStage), nextStage * 190);
    }
  }

  if (!decision) {
    return (
      <section className="flex min-h-[470px] items-center justify-center border-y border-white/[0.08] bg-[#0a0d12] px-8 text-center">
        <div>
          <History className="mx-auto size-6 text-slate-700" />
          <p className="mt-4 text-sm text-slate-500">No decision is available for replay.</p>
        </div>
      </section>
    );
  }

  const statement = decision.decision === "REJECT" ? "REGRET SAID NO." : "REGRET SAID YES.";
  const question = decision.decision === "REJECT" ? "What if REGRET had traded?" : "What happened after REGRET traded?";

  return (
    <section className="overflow-hidden border-y border-white/[0.08] bg-[#0a0d12]">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-white/[0.07] px-5 py-4 sm:px-7">
        <div className="flex items-baseline gap-3">
          <h2 className="text-base font-medium text-slate-100">Counterfactual replay</h2>
          <span className="font-mono text-xs text-slate-600">{decision.symbol} / {decision.decision}</span>
        </div>
        {outcome && event && (
          <button className="flex items-center gap-2 border-b border-slate-600 pb-1 text-xs text-slate-300 transition hover:border-white hover:text-white" onClick={replay} type="button">
            <RotateCcw className="size-3.5" /> Replay decision
          </button>
        )}
      </header>

      {outcome && event ? (
        <>
          <div className="grid lg:grid-cols-[minmax(0,1fr)_250px]">
            <div className="min-w-0 px-5 py-5 sm:px-7">
              <p className="font-mono text-xl font-semibold tracking-tight text-white sm:text-2xl">{statement}</p>
              <p className="mt-1 text-base text-slate-400">{question}</p>
              <ReplayChart classification={event.classification} outcome={outcome} replayKey={replayKey} />
              <dl className="mt-4 grid grid-cols-2 gap-x-5 gap-y-4 sm:grid-cols-4">
                <div><dt className="text-xs text-slate-600">Entry price</dt><dd className="mt-1 font-mono text-sm tabular-nums text-slate-200">{formatCurrency(outcome.entry_price)}</dd></div>
                <div><dt className="text-xs text-slate-600">Evaluation price</dt><dd className="mt-1 font-mono text-sm tabular-nums text-slate-200">{formatCurrency(outcome.evaluation_price)}</dd></div>
                <div><dt className="text-xs text-slate-600">Price move</dt><dd className="mt-1 font-mono text-sm tabular-nums text-slate-200">{formatSignedPercent(outcome.pnl_pct)}</dd></div>
                <div><dt className="text-xs text-slate-600">Hypothetical P&amp;L</dt><dd className="mt-1 font-mono text-sm tabular-nums text-slate-200">{formatSignedCurrency(outcome.pnl_amount)}</dd></div>
              </dl>
            </div>

            <aside className={`border-t px-5 py-6 lg:border-l lg:border-t-0 lg:px-6 ${classificationTheme(event.classification).soft} ${classificationTheme(event.classification).rule}`}>
              <p className={`text-xs font-semibold tracking-[0.12em] ${classificationTheme(event.classification).accent}`}>
                {CLASSIFICATION_META[event.classification].label.toUpperCase()}
              </p>
              <p className={`mt-3 font-mono text-3xl font-semibold leading-tight tabular-nums ${classificationTheme(event.classification).accent}`}>
                {classificationValueLabel(event)}
              </p>
              <p className="mt-4 text-sm leading-6 text-slate-400">{CLASSIFICATION_META[event.classification].description}</p>
              <div className="mt-7 border-t border-white/[0.08] pt-4">
                <p className="text-xs text-slate-600">Decision Value</p>
                <p className="mt-1.5 font-mono text-xl tabular-nums text-white">{formatSignedCurrency(event.decision_value)}</p>
              </div>
            </aside>
          </div>
          <ReplayPath finalDecision={decision.decision} stage={stage} />
        </>
      ) : (
        <div className="flex min-h-[390px] items-center justify-center px-8 text-center">
          <div>
            <Clock3 className="mx-auto size-5 text-slate-700" />
            <p className="mt-3 text-sm text-slate-400">No evaluated outcome for this decision yet.</p>
            <p className="mt-1 text-xs text-slate-600">Replay appears after the configured evaluation horizon.</p>
          </div>
        </div>
      )}
    </section>
  );
}

function AuditTrail({
  decision,
  candidate,
  detail,
  detailError,
  loading,
}: {
  decision?: DecisionListItem;
  candidate?: Candidate;
  detail: DecisionDetail | null;
  detailError: string | null;
  loading: boolean;
}) {
  if (!decision) return null;

  return (
    <section className="mt-14 border-t border-white/[0.1] pt-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-2xl font-medium tracking-tight text-white">Why did REGRET make this decision?</h2>
          <p className="mt-2 text-sm text-slate-500">Persisted structured evidence only — never hidden chain-of-thought.</p>
        </div>
        <div className="flex items-baseline gap-3 sm:text-right">
          <span className="font-mono text-xl text-slate-100">{decision.symbol}</span>
          <span className={`text-sm ${decisionTone(decision.decision)}`}>{decision.decision}</span>
        </div>
      </div>

      {loading ? (
        <div className="mt-8 grid gap-5 sm:grid-cols-5">
          {[0, 1, 2, 3, 4].map((item) => <div className="skeleton h-24 rounded-md" key={item} />)}
        </div>
      ) : detailError ? (
        <div className="mt-8 border-l border-amber-300/40 pl-4 text-sm text-amber-100">Detailed agent reasoning is unavailable. {detailError}</div>
      ) : detail ? (
        <>
          <ol className="mt-8 grid border-y border-white/[0.08] sm:grid-cols-5">
            {[
              ["01", "Scout", `${candidate?.strategy ?? "Signal"} · score ${candidate?.scout_score.toFixed(1) ?? "—"}`],
              ["02", "Azure Analyst", formatPercent(detail.analyst.confidence)],
              ["03", "Adversarial Critic", `${detail.critic.verdict} ${formatSignedPercent(detail.critic.confidence_adjustment)}`],
              ["04", "Consensus", formatPercent(detail.consensus.adjusted_confidence)],
              ["05", "Risk Gate", detail.risk.decision],
            ].map(([number, label, value], index) => (
              <li className={`min-w-0 py-4 sm:px-4 ${index > 0 ? "border-t border-white/[0.07] sm:border-l sm:border-t-0" : ""}`} key={number}>
                <p className="font-mono text-[10px] text-slate-700">{number}</p>
                <p className="mt-2 text-xs text-slate-500">{label}</p>
                <p className="mt-1.5 truncate font-mono text-sm text-slate-200">{value}</p>
              </li>
            ))}
          </ol>

          <div className="mt-10 grid gap-10 lg:grid-cols-2 lg:gap-0">
            <article className="lg:pr-10">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="flex items-center gap-2 text-base font-medium text-slate-100"><BrainCircuit className="size-4 text-slate-500" /> Analyst record</h3>
                <span className="text-xs text-slate-600">{detail.analyst.provider} · {detail.analyst.model}</span>
              </div>
              <p className="mt-5 text-sm leading-7 text-slate-300">{detail.analyst.thesis}</p>
              <dl className="mt-6 grid grid-cols-4 gap-3 border-y border-white/[0.07] py-4">
                {[
                  ["Confidence", formatPercent(detail.analyst.confidence)],
                  ["Entry", formatCurrency(detail.analyst.entry_price)],
                  ["Stop", formatCurrency(detail.analyst.stop_loss)],
                  ["Target", formatCurrency(detail.analyst.target_price)],
                ].map(([label, value]) => <div className="min-w-0" key={label}><dt className="text-[11px] text-slate-600">{label}</dt><dd className="mt-1.5 truncate font-mono text-xs text-slate-300">{value}</dd></div>)}
              </dl>
              <p className="mt-5 text-xs text-slate-600">Invalidation</p>
              <p className="mt-1.5 text-xs leading-6 text-slate-500">{detail.analyst.invalidation}</p>
              <p className="mt-5 text-xs text-slate-600">Evidence</p>
              <ul className="mt-2 space-y-2 border-l border-white/[0.09] pl-4 text-xs leading-6 text-slate-500">
                {detail.analyst.evidence.slice(0, 3).map((item) => <li key={item}>{item}</li>)}
              </ul>
            </article>

            <article className="border-t border-white/[0.08] pt-10 lg:border-l lg:border-t-0 lg:pl-10 lg:pt-0">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="flex items-center gap-2 text-base font-medium text-slate-100"><Bot className="size-4 text-slate-500" /> {criticModeLabel(detail.critic.provider)}</h3>
                <span className="text-xs text-slate-600">{detail.critic.provider} · {detail.critic.model}</span>
              </div>
              <dl className="mt-6 grid grid-cols-3 gap-3 border-y border-white/[0.07] py-4">
                <div><dt className="text-[11px] text-slate-600">Verdict</dt><dd className="mt-1.5 flex items-center gap-1.5 font-mono text-xs text-slate-300">{detail.critic.verdict === "PASS" ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}{detail.critic.verdict}</dd></div>
                <div><dt className="text-[11px] text-slate-600">Adjustment</dt><dd className="mt-1.5 font-mono text-xs text-slate-300">{formatSignedPercent(detail.critic.confidence_adjustment)}</dd></div>
                <div><dt className="text-[11px] text-slate-600">Consistency</dt><dd className="mt-1.5 font-mono text-xs text-slate-300">{formatPercent(detail.critic.thesis_consistency)}</dd></div>
              </dl>
              <p className="mt-5 text-xs text-slate-600">Concerns</p>
              <ul className="mt-2 space-y-3 border-l border-white/[0.09] pl-4 text-xs leading-6 text-slate-500">
                {detail.critic.concerns.slice(0, 3).map((concern) => <li key={concern}>{concern}</li>)}
              </ul>
              <div className="mt-6 border-t border-white/[0.07] pt-4">
                <div className="flex flex-wrap items-baseline justify-between gap-3">
                  <p className="text-xs text-slate-600">Risk gate</p>
                  <p className="font-mono text-sm text-slate-200">R:R {detail.risk.reward_risk_ratio.toFixed(2)} / Risk {detail.risk.risk_score.toFixed(1)} / {detail.risk.decision}</p>
                </div>
                <ul className="mt-2 text-xs leading-6 text-slate-500">{detail.risk.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
              </div>
            </article>
          </div>
        </>
      ) : null}
    </section>
  );
}

export function Dashboard() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [data, setData] = useState<DashboardData | null>(null);
  const [partialErrors, setPartialErrors] = useState<string[]>([]);
  const [filter, setFilter] = useState<FeedFilter>("ALL");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detailState, setDetailState] = useState<{
    id: number;
    data: DecisionDetail | null;
    error: string | null;
  } | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoadState("loading");
    try {
      const result = await loadDashboardData();
      const hasCoreData = result.data.health !== null || result.data.decisions.length > 0 || result.data.regretEvents.length > 0;
      if (!hasCoreData && result.errors.length > 0) {
        setLoadState("offline");
        return;
      }
      setData(result.data);
      setPartialErrors(result.errors);
      setSelectedId((current) => current ?? result.data.outcomes[0]?.risk_decision_id ?? result.data.decisions[0]?.id ?? null);
      setLoadState("ready");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) setLoadState("offline");
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (selectedId === null) return;
    const controller = new AbortController();
    api.getDecision(selectedId, controller.signal)
      .then((result) => setDetailState({ id: selectedId, data: result, error: null }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setDetailState({ id: selectedId, data: null, error: toUserMessage(error) });
        }
      });
    return () => controller.abort();
  }, [selectedId]);

  const candidatesById = useMemo(() => new Map(data?.candidates.map((candidate) => [candidate.id, candidate]) ?? []), [data]);
  const decisions = useMemo(() => {
    const list = data?.decisions ?? [];
    return list.filter((decision) => filter === "ALL" || decision.decision === filter);
  }, [data, filter]);
  const failedCandidates = useMemo(
    () => data?.candidates.filter((candidate) => ["ANALYSIS_FAILED", "CRITIC_FAILED", "RISK_FAILED"].includes(candidate.status)) ?? [],
    [data],
  );
  const selectedDecision = data?.decisions.find((decision) => decision.id === selectedId);
  const selectedCandidate = selectedDecision ? candidatesById.get(selectedDecision.candidate_id) : undefined;
  const selectedOutcome = data?.outcomes.find((outcome) => outcome.risk_decision_id === selectedId);
  const selectedEvent = data?.regretEvents.find((event) => event.risk_decision_id === selectedId);
  const detail = detailState?.id === selectedId ? detailState.data : null;
  const detailError = detailState?.id === selectedId ? detailState.error : null;
  const detailLoading = selectedId !== null && detailState?.id !== selectedId;

  if (loadState === "loading") return <SkeletonDashboard />;
  if (loadState === "offline" || !data) return <OfflineState onRetry={() => void load()} />;

  const backendHealthy = data.health?.status === "ok";
  const positiveDecisionValue = data.metrics.decision_value >= 0;

  return (
    <main className="mx-auto w-full max-w-[1520px] px-5 pb-16 pt-6 sm:px-8 lg:px-10">
      <header className="flex flex-col gap-4 border-b border-white/[0.08] pb-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-baseline gap-4">
          <h1 className="text-xl font-semibold tracking-[0.06em] text-white">REGRET</h1>
          <p className="hidden text-sm text-slate-500 sm:block">Counterfactual Decision Intelligence</p>
        </div>
        <div className="flex items-center gap-5 text-xs text-slate-500">
          <span className="border border-white/10 px-2 py-1 text-[10px] font-medium text-slate-400">PAPER MODE</span>
          <span className="flex items-center gap-2"><span className={`size-1.5 rounded-full ${backendHealthy ? "bg-emerald-400" : "bg-amber-300"}`} />{backendHealthy ? "API healthy" : "API degraded"}</span>
          <button className="flex items-center gap-2 text-slate-400 transition hover:text-white disabled:opacity-50" disabled={refreshing} onClick={() => void load(true)} type="button">
            <RefreshCw className={`size-3.5 ${refreshing ? "animate-spin" : ""}`} /> {refreshing ? "Refreshing" : "Refresh"}
          </button>
        </div>
      </header>

      {partialErrors.length > 0 && (
        <div className="mt-4 flex items-start gap-3 border-l border-amber-300/50 pl-4 text-xs leading-5 text-amber-100">
          <AlertCircle className="mt-0.5 size-4 shrink-0 text-amber-300" />
          <span>Partial data: {partialErrors.join(", ")} could not be loaded. Available sections remain live.</span>
        </div>
      )}

      <section className="grid gap-10 border-b border-white/[0.09] py-9 lg:grid-cols-[1.1fr_0.9fr] lg:items-end lg:py-10">
        <div>
          <p className="text-base text-slate-400">Decision Value</p>
          <p className="mt-4 font-mono text-[clamp(3.6rem,7vw,7rem)] font-medium leading-[0.82] tracking-[-0.075em] text-white tabular-nums">
            {formatSignedCurrency(data.metrics.decision_value)}
          </p>
          <p className="mt-6 max-w-xl text-base leading-7 text-slate-400">
            {positiveDecisionValue ? "Net value created or protected" : "Net value destroyed or missed"} by REGRET&apos;s decisions.
          </p>
        </div>
        <dl className="grid grid-cols-2 gap-x-7 gap-y-6">
          <MetricDatum label="Avoided Loss" note={`${data.metrics.classification_counts.AVOIDED_LOSS} protected decision`} tone="blue" value={formatCurrency(data.metrics.avoided_loss)} />
          <MetricDatum label="Missed Alpha" note={`${data.metrics.classification_counts.MISSED_ALPHA} rejected winner`} tone="amber" value={formatCurrency(data.metrics.missed_alpha)} />
          <MetricDatum label="Evaluated Decisions" note={`${data.shadowTrades.length} shadow trades tracked`} value={data.metrics.total_decisions_evaluated.toLocaleString()} />
          <MetricDatum label="Paper Executions" note={data.executions.length === 0 ? "No naturally accepted executions" : "Paper ledger only"} value={data.executions.length.toLocaleString()} />
        </dl>
      </section>

      <section className="mt-8 grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_360px]">
        <ReplaySurface decision={selectedDecision} event={selectedEvent} outcome={selectedOutcome} />

        <aside className="min-w-0 lg:border-l lg:border-white/[0.08] lg:pl-7">
          <div className="flex items-end justify-between gap-3">
            <div>
              <h2 className="text-base font-medium text-slate-100">Decision stream</h2>
              <p className="mt-1 text-xs text-slate-600">{data.decisions.length} decisions · {failedCandidates.length} safe failures</p>
            </div>
            <span className="text-[10px] text-slate-700">Newest first</span>
          </div>
          <div className="mt-4 grid grid-cols-4 border-y border-white/[0.07] py-1">
            {(["ALL", "ACCEPT", "REJECT", "FAILURES"] as FeedFilter[]).map((item) => (
              <button className={`py-2 text-[10px] transition ${filter === item ? "text-slate-200" : "text-slate-600 hover:text-slate-400"}`} key={item} onClick={() => setFilter(item)} type="button">{FILTER_LABELS[item]}</button>
            ))}
          </div>
          <div className="terminal-scroll max-h-[452px] overflow-y-auto pr-1">
            {filter !== "FAILURES" && decisions.map((decision) => (
              <FeedRow candidate={candidatesById.get(decision.candidate_id)} decision={decision} key={decision.id} onSelect={() => setSelectedId(decision.id)} selected={decision.id === selectedId} />
            ))}
            {(filter === "ALL" || filter === "FAILURES") && failedCandidates.map((candidate) => <FailureRow candidate={candidate} key={`failure-${candidate.id}`} />)}
            {((filter === "FAILURES" && failedCandidates.length === 0) || (filter !== "ALL" && filter !== "FAILURES" && decisions.length === 0)) && (
              <div className="py-12 text-center text-sm text-slate-600">No {FILTER_LABELS[filter].toLowerCase()} decisions.</div>
            )}
          </div>
        </aside>
      </section>

      <AuditTrail candidate={selectedCandidate} decision={selectedDecision} detail={detail} detailError={detailError} loading={detailLoading} />

      <footer className="mt-14 flex flex-col gap-2 border-t border-white/[0.07] pt-5 text-[11px] text-slate-700 sm:flex-row sm:items-center sm:justify-between">
        <span>Read-only decision review · no execution actions</span>
        <span className="font-mono">{API_BASE_URL}</span>
      </footer>
    </main>
  );
}
