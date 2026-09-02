"use client";

import {
  Activity,
  AlertCircle,
  ArrowUpRight,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  Gauge,
  History,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  WalletCards,
  XCircle,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

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
  decisionValueMessage,
  formatCurrency,
  formatPercent,
  formatSignedCurrency,
  formatSignedPercent,
  toUserMessage,
} from "@/lib/presentation";

type FeedFilter = "ALL" | "ACCEPT" | "REJECT" | "FAILURES";
type LoadState = "loading" | "ready" | "offline";

function timeLabel(value?: string): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function classificationClasses(classification: Classification): string {
  return {
    MISSED_ALPHA: "border-amber-400/25 bg-amber-400/10 text-amber-200",
    AVOIDED_LOSS: "border-sky-400/25 bg-sky-400/10 text-sky-200",
    CORRECT_EXECUTION: "border-emerald-400/25 bg-emerald-400/10 text-emerald-200",
    BAD_EXECUTION: "border-rose-400/25 bg-rose-400/10 text-rose-200",
  }[classification];
}

function decisionClasses(decision: "ACCEPT" | "REJECT"): string {
  return decision === "ACCEPT"
    ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-200"
    : "border-slate-400/20 bg-slate-400/10 text-slate-300";
}

function MetricCard({
  label,
  value,
  note,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: string;
  note: string;
  icon: ReactNode;
  tone?: "positive" | "warning" | "neutral";
}) {
  const valueTone =
    tone === "positive"
      ? "text-emerald-300"
      : tone === "warning"
        ? "text-amber-200"
        : "text-slate-100";
  return (
    <article className="panel min-w-0 rounded-2xl p-4 sm:p-5">
      <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
        <span>{label}</span>
        <span className="text-slate-600">{icon}</span>
      </div>
      <p className={`mt-5 truncate font-mono text-2xl font-semibold tracking-tight ${valueTone}`}>
        {value}
      </p>
      <p className="mt-2 text-xs leading-5 text-slate-500">{note}</p>
    </article>
  );
}

function SkeletonDashboard() {
  return (
    <main className="mx-auto w-full max-w-[1600px] px-4 pb-12 pt-6 sm:px-6 lg:px-8" aria-busy="true">
      <div className="skeleton h-14 rounded-xl" />
      <div className="mt-7 grid grid-cols-2 gap-3 lg:grid-cols-5">
        {[0, 1, 2, 3, 4].map((item) => (
          <div className="skeleton h-36 rounded-2xl" key={item} />
        ))}
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-[0.72fr_1.28fr]">
        <div className="skeleton h-[590px] rounded-2xl" />
        <div className="skeleton h-[590px] rounded-2xl" />
      </div>
      <span className="sr-only">Loading decision intelligence</span>
    </main>
  );
}

function OfflineState({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-xl items-center px-6 py-20">
      <section className="panel w-full rounded-3xl p-8 text-center sm:p-12">
        <span className="mx-auto flex size-12 items-center justify-center rounded-2xl border border-rose-400/20 bg-rose-400/10 text-rose-300">
          <AlertCircle className="size-5" />
        </span>
        <p className="mt-6 text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">Backend offline</p>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight text-white">Decision data is unavailable</h1>
        <p className="mt-3 text-sm leading-6 text-slate-400">
          Start the REGRET API at <span className="font-mono text-slate-300">{API_BASE_URL}</span>, then retry.
          No cached or synthetic trading data is being shown.
        </p>
        <button
          className="mx-auto mt-7 flex items-center gap-2 rounded-xl border border-sky-400/25 bg-sky-400/10 px-4 py-2.5 text-sm font-medium text-sky-200 transition hover:bg-sky-400/15"
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
      className={`w-full border-b border-white/[0.055] px-4 py-4 text-left transition last:border-b-0 hover:bg-white/[0.025] sm:px-5 ${
        selected ? "bg-sky-400/[0.075] shadow-[inset_2px_0_0_#55a7ff]" : ""
      }`}
      onClick={onSelect}
      type="button"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <span className="font-mono text-sm font-semibold text-slate-100">{decision.symbol}</span>
            <span className={`rounded-md border px-1.5 py-0.5 text-[9px] font-bold tracking-[0.14em] ${decisionClasses(decision.decision)}`}>
              {decision.decision}
            </span>
          </div>
          <p className="mt-1.5 truncate text-xs text-slate-500">
            {candidate?.strategy ?? "Decision review"} · {timeLabel(decision.created_at)}
          </p>
        </div>
        <div className="text-right">
          <p className="font-mono text-sm text-slate-200">{formatPercent(decision.adjusted_confidence)}</p>
          <p className="mt-1 text-[10px] uppercase tracking-wider text-slate-600">confidence</p>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2 text-[11px] text-slate-500">
        <span>R:R {decision.reward_risk_ratio.toFixed(2)}</span>
        <span className="text-slate-700">•</span>
        <span>Risk {decision.risk_score.toFixed(1)}</span>
        {decision.degraded_mode && (
          <>
            <span className="text-slate-700">•</span>
            <span className="text-amber-300/80">Fallback critic</span>
          </>
        )}
      </div>
    </button>
  );
}

function FailureRow({ candidate }: { candidate: Candidate }) {
  return (
    <div className="border-b border-white/[0.055] px-4 py-4 last:border-b-0 sm:px-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="font-mono text-sm font-semibold text-slate-300">{candidate.symbol}</span>
            <span className="rounded-md border border-rose-400/20 bg-rose-400/[0.07] px-1.5 py-0.5 text-[9px] font-bold tracking-[0.12em] text-rose-200">
              {candidate.status}
            </span>
          </div>
          <p className="mt-1.5 text-xs text-slate-600">{candidate.strategy} · {timeLabel(candidate.created_at)}</p>
        </div>
        <AlertCircle className="mt-0.5 size-4 shrink-0 text-rose-300/60" />
      </div>
      <p className="mt-3 text-[11px] leading-5 text-slate-600">Pipeline stopped safely; no risk decision or order was created.</p>
    </div>
  );
}

function ReplayChart({ outcome, replayKey }: { outcome: Outcome; replayKey: number }) {
  const move = Math.max(-55, Math.min(55, outcome.pnl_pct * 400));
  const endY = 90 - move;
  const isUp = outcome.pnl_pct >= 0;
  const color = isUp ? "#59d69c" : "#fb7185";
  return (
    <div className="hairline-grid relative mt-5 overflow-hidden rounded-2xl border border-white/[0.07] bg-[#070b12] p-3 sm:p-5">
      <svg aria-label={`Price moved from ${outcome.entry_price} to ${outcome.evaluation_price}`} className="h-44 w-full" key={replayKey} role="img" viewBox="0 0 640 180">
        <line stroke="rgba(148,163,184,.12)" strokeDasharray="4 8" x1="50" x2="590" y1="90" y2="90" />
        <line className="replay-line" stroke={color} strokeLinecap="round" strokeWidth="3" x1="80" x2="560" y1="90" y2={endY} />
        <circle fill="#07101b" r="7" stroke="#a7b2c2" strokeWidth="3" cx="80" cy="90" />
        <circle className="replay-dot" fill="#07101b" r="8" stroke={color} strokeWidth="4" cx="560" cy={endY} />
        <text fill="#8793a5" fontSize="12" x="58" y="125">ENTRY</text>
        <text fill="#e8edf4" fontFamily="monospace" fontSize="14" x="44" y="145">{formatCurrency(outcome.entry_price)}</text>
        <text fill="#8793a5" fontSize="12" textAnchor="end" x="585" y={endY < 65 ? endY + 35 : endY - 25}>EVALUATED</text>
        <text fill={color} fontFamily="monospace" fontSize="14" fontWeight="700" textAnchor="end" x="590" y={endY < 65 ? endY + 55 : endY - 7}>{formatCurrency(outcome.evaluation_price)}</text>
      </svg>
      <div className="absolute right-4 top-4 rounded-lg border border-white/10 bg-black/40 px-2.5 py-1.5 font-mono text-xs" style={{ color }}>
        {formatSignedPercent(outcome.pnl_pct)}
      </div>
      <p className="px-1 text-[10px] leading-4 text-slate-600">Two observed points only. Vertical movement is capped for legibility; labels show exact prices.</p>
    </div>
  );
}

function Pipeline({ stage, finalDecision }: { stage: number; finalDecision: "ACCEPT" | "REJECT" }) {
  const steps = ["Candidate", "Analyst", "Critic", "Consensus", "Risk gate", finalDecision, "Outcome", "Regret", "Value"];
  return (
    <div className="grid grid-cols-3 gap-x-1.5 gap-y-3 sm:grid-cols-9" aria-label="Decision pipeline">
      {steps.map((step, index) => (
        <div className="min-w-0" key={step}>
          <div className={`h-1 rounded-full transition-all duration-500 ${index <= stage ? "bg-sky-400" : "bg-white/[0.08]"}`} />
          <p className={`mt-2 truncate text-[9px] font-semibold uppercase tracking-wider transition ${index <= stage ? "text-slate-300" : "text-slate-700"}`}>{step}</p>
        </div>
      ))}
    </div>
  );
}

function Inspector({
  decision,
  detail,
  detailError,
  outcome,
  event,
  loading,
}: {
  decision?: DecisionListItem;
  detail: DecisionDetail | null;
  detailError: string | null;
  outcome?: Outcome;
  event?: RegretEvent;
  loading: boolean;
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
      <section className="panel flex min-h-[520px] items-center justify-center rounded-2xl p-8 text-center">
        <div>
          <History className="mx-auto size-7 text-slate-700" />
          <p className="mt-4 text-sm text-slate-400">No decisions are available to inspect yet.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="panel min-w-0 rounded-2xl">
      <div className="border-b border-white/[0.07] p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Decision inspector</p>
            <div className="mt-2 flex items-center gap-3">
              <h2 className="font-mono text-2xl font-semibold text-white">{decision.symbol}</h2>
              <span className={`rounded-lg border px-2 py-1 text-[10px] font-bold tracking-[0.14em] ${decisionClasses(decision.decision)}`}>{decision.decision}</span>
            </div>
          </div>
          <div className="text-right">
            <p className="font-mono text-xl text-white">{formatPercent(decision.adjusted_confidence)}</p>
            <p className="mt-1 text-[10px] uppercase tracking-widest text-slate-600">adjusted confidence</p>
          </div>
        </div>
        <div className="mt-6"><Pipeline finalDecision={decision.decision} stage={stage} /></div>
      </div>

      {loading ? (
        <div className="grid gap-3 p-5 sm:grid-cols-2 sm:p-6">
          <div className="skeleton h-44 rounded-2xl" />
          <div className="skeleton h-44 rounded-2xl" />
        </div>
      ) : detailError ? (
        <div className="m-5 rounded-xl border border-amber-400/20 bg-amber-400/[0.07] p-4 text-sm text-amber-100 sm:m-6">
          Detailed agent reasoning is unavailable. {detailError}
        </div>
      ) : detail ? (
        <div className="grid gap-3 p-5 sm:grid-cols-2 sm:p-6">
          <article className="rounded-2xl border border-white/[0.07] bg-black/15 p-4">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-sky-300"><BrainCircuit className="size-3.5" /> Analyst</span>
              <span className="text-[10px] text-slate-600">{detail.analyst.provider} · {detail.analyst.model}</span>
            </div>
            <p className="mt-4 text-sm leading-6 text-slate-300">{detail.analyst.thesis}</p>
            <div className="mt-4 grid grid-cols-4 gap-2 border-y border-white/[0.06] py-3">
              {[
                ["Confidence", formatPercent(detail.analyst.confidence)],
                ["Entry", formatCurrency(detail.analyst.entry_price)],
                ["Stop", formatCurrency(detail.analyst.stop_loss)],
                ["Target", formatCurrency(detail.analyst.target_price)],
              ].map(([label, value]) => <div className="min-w-0" key={label}><p className="text-[9px] uppercase tracking-wider text-slate-700">{label}</p><p className="mt-1 truncate font-mono text-[11px] text-slate-300">{value}</p></div>)}
            </div>
            <p className="mt-4 text-[10px] uppercase tracking-wider text-slate-600">Invalidation</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">{detail.analyst.invalidation}</p>
            <p className="mt-4 text-[10px] uppercase tracking-wider text-slate-600">Persisted evidence</p>
            <ul className="mt-1.5 space-y-1.5 text-xs leading-5 text-slate-500">{detail.analyst.evidence.slice(0, 3).map((item) => <li key={item}>— {item}</li>)}</ul>
          </article>
          <article className="rounded-2xl border border-white/[0.07] bg-black/15 p-4">
            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-violet-300"><Bot className="size-3.5" /> {criticModeLabel(detail.critic.provider)}</span>
              <span className="text-right text-[10px] text-slate-600">{detail.critic.provider} · {detail.critic.model}</span>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2 border-b border-white/[0.06] pb-3">
              <div><p className="text-[9px] uppercase tracking-wider text-slate-700">Verdict</p><p className="mt-1 flex items-center gap-1.5 text-xs text-slate-300">{detail.critic.verdict === "PASS" ? <CheckCircle2 className="size-3.5 text-emerald-300" /> : <XCircle className="size-3.5 text-amber-300" />}{detail.critic.verdict}</p></div>
              <div><p className="text-[9px] uppercase tracking-wider text-slate-700">Adjustment</p><p className="mt-1 font-mono text-xs text-slate-300">{formatSignedPercent(detail.critic.confidence_adjustment)}</p></div>
              <div><p className="text-[9px] uppercase tracking-wider text-slate-700">Consistency</p><p className="mt-1 font-mono text-xs text-slate-300">{formatPercent(detail.critic.thesis_consistency)}</p></div>
            </div>
            <p className="mt-4 text-[10px] uppercase tracking-wider text-slate-600">Concerns</p>
            <ul className="mt-3 space-y-2 text-xs leading-5 text-slate-500">
              {detail.critic.concerns.slice(0, 3).map((concern) => <li key={concern}>— {concern}</li>)}
            </ul>
          </article>
          <article className="grid gap-4 rounded-2xl border border-white/[0.07] bg-black/15 p-4 sm:col-span-2 sm:grid-cols-[0.8fr_1.2fr]">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-indigo-300">Consensus</p>
              <div className="mt-4 grid grid-cols-3 gap-2">
                {[
                  ["Original", formatPercent(detail.consensus.original_confidence)],
                  ["Adjustment", formatSignedPercent(detail.consensus.critic_adjustment)],
                  ["Adjusted", formatPercent(detail.consensus.adjusted_confidence)],
                ].map(([label, value]) => <div key={label}><p className="text-[9px] uppercase tracking-wider text-slate-700">{label}</p><p className="mt-1.5 font-mono text-xs text-slate-300">{value}</p></div>)}
              </div>
            </div>
            <div className="border-t border-white/[0.06] pt-4 sm:border-l sm:border-t-0 sm:pl-4 sm:pt-0">
              <div className="flex items-center justify-between gap-3"><p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-300">Risk gate</p><span className={`rounded-md border px-2 py-0.5 text-[9px] font-bold tracking-wider ${decisionClasses(detail.risk.decision)}`}>{detail.risk.decision}</span></div>
              <div className="mt-3 flex gap-5 font-mono text-xs text-slate-400"><span>R:R {detail.risk.reward_risk_ratio.toFixed(2)}</span><span>Risk {detail.risk.risk_score.toFixed(1)}</span></div>
              <ul className="mt-2 space-y-1 text-xs leading-5 text-slate-500">{detail.risk.reasons.map((reason) => <li key={reason}>— {reason}</li>)}</ul>
            </div>
          </article>
        </div>
      ) : null}

      <div className="border-t border-white/[0.07] p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Counterfactual replay</p>
            <h3 className="mt-2 text-lg font-semibold text-slate-100">What happened after the decision?</h3>
          </div>
          {outcome && (
            <button className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.035] px-3 py-2 text-xs font-medium text-slate-300 transition hover:bg-white/[0.07]" onClick={replay} type="button">
              <RotateCcw className="size-3.5" /> Replay Decision
            </button>
          )}
        </div>

        {outcome && event ? (
          <>
            <p className="mt-5 rounded-xl border border-white/[0.07] bg-white/[0.025] px-4 py-3 text-sm text-slate-300">
              REGRET {decision.decision === "REJECT" ? "rejected" : "accepted"} this trade. The recorded outcome below measures the decision after its evaluation horizon.
            </p>
            <ReplayChart outcome={outcome} replayKey={replayKey} />
            <div className="mt-3 grid grid-cols-3 gap-2">
              <div className="rounded-xl border border-white/[0.06] bg-black/15 p-3"><p className="text-[9px] uppercase tracking-wider text-slate-700">Entry price</p><p className="mt-1.5 font-mono text-xs text-slate-300">{formatCurrency(outcome.entry_price)}</p></div>
              <div className="rounded-xl border border-white/[0.06] bg-black/15 p-3"><p className="text-[9px] uppercase tracking-wider text-slate-700">Evaluation price</p><p className="mt-1.5 font-mono text-xs text-slate-300">{formatCurrency(outcome.evaluation_price)}</p></div>
              <div className="rounded-xl border border-white/[0.06] bg-black/15 p-3"><p className="text-[9px] uppercase tracking-wider text-slate-700">Hypothetical P&amp;L</p><p className={`mt-1.5 font-mono text-xs ${outcome.pnl_amount >= 0 ? "text-emerald-300" : "text-rose-300"}`}>{formatSignedCurrency(outcome.pnl_amount)}</p></div>
            </div>
            <div className={`mt-4 grid gap-3 transition-opacity duration-500 sm:grid-cols-[1fr_auto] ${stage >= 4 ? "opacity-100" : "opacity-30"}`}>
              <div className={`rounded-xl border p-4 ${classificationClasses(event.classification)}`}>
                <div className="flex items-start gap-3">
                  {event.decision_value >= 0 ? <ShieldCheck className="mt-0.5 size-5 shrink-0" /> : <TrendingUp className="mt-0.5 size-5 shrink-0" />}
                  <div>
                    <p className="text-xs font-bold uppercase tracking-[0.15em]">{CLASSIFICATION_META[event.classification].label}</p>
                    <p className="mt-1.5 text-xs leading-5 opacity-75">{CLASSIFICATION_META[event.classification].description}</p>
                  </div>
                </div>
              </div>
              <div className="min-w-44 rounded-xl border border-white/[0.07] bg-black/20 p-4 sm:text-right">
                <p className="text-[10px] uppercase tracking-[0.16em] text-slate-600">Decision value</p>
                <p className={`mt-2 font-mono text-xl font-semibold ${event.decision_value >= 0 ? "text-emerald-300" : "text-rose-300"}`}>{formatSignedCurrency(event.decision_value)}</p>
                <p className="mt-1 text-[10px] text-slate-600">{decisionValueMessage(event.decision_value)}</p>
              </div>
            </div>
          </>
        ) : (
          <div className="mt-5 rounded-2xl border border-dashed border-white/10 bg-black/10 px-5 py-10 text-center">
            <Clock3 className="mx-auto size-5 text-slate-700" />
            <p className="mt-3 text-sm text-slate-400">No evaluated outcome for this decision yet.</p>
            <p className="mt-1 text-xs text-slate-600">Replay appears only after the configured evaluation horizon.</p>
          </div>
        )}
      </div>
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
  const selectedOutcome = data?.outcomes.find((outcome) => outcome.risk_decision_id === selectedId);
  const selectedEvent = data?.regretEvents.find((event) => event.risk_decision_id === selectedId);
  const detail = detailState?.id === selectedId ? detailState.data : null;
  const detailError = detailState?.id === selectedId ? detailState.error : null;
  const detailLoading = selectedId !== null && detailState?.id !== selectedId;

  if (loadState === "loading") return <SkeletonDashboard />;
  if (loadState === "offline" || !data) return <OfflineState onRetry={() => void load()} />;

  const evaluated = data.metrics.total_decisions_evaluated;
  const backendHealthy = data.health?.status === "ok";

  return (
    <main className="mx-auto w-full max-w-[1600px] px-4 pb-12 pt-5 sm:px-6 lg:px-8">
      <header className="flex flex-col gap-4 border-b border-white/[0.07] pb-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-xl border border-sky-400/20 bg-sky-400/10 text-sky-300"><Zap className="size-5" /></span>
          <div>
            <div className="flex items-center gap-2.5"><h1 className="text-lg font-semibold tracking-[0.08em] text-white">REGRET</h1><span className="rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 text-[9px] font-bold tracking-[0.14em] text-slate-500">PAPER MODE</span></div>
            <p className="mt-0.5 text-xs text-slate-500">Counterfactual Intelligence for Autonomous Trading</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <span className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${backendHealthy ? "border-emerald-400/15 bg-emerald-400/[0.06] text-emerald-300" : "border-amber-400/15 bg-amber-400/[0.06] text-amber-200"}`}>
            <span className={`size-1.5 rounded-full ${backendHealthy ? "bg-emerald-400" : "bg-amber-400"}`} /> {backendHealthy ? "API healthy" : "API degraded"}
          </span>
          <button className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.035] px-3 py-2 text-xs text-slate-300 transition hover:bg-white/[0.07] disabled:opacity-50" disabled={refreshing} onClick={() => void load(true)} type="button">
            <RefreshCw className={`size-3.5 ${refreshing ? "animate-spin" : ""}`} /> {refreshing ? "Refreshing" : "Refresh"}
          </button>
        </div>
      </header>

      {partialErrors.length > 0 && (
        <div className="mt-4 flex items-start gap-3 rounded-xl border border-amber-400/15 bg-amber-400/[0.055] px-4 py-3 text-xs leading-5 text-amber-100">
          <AlertCircle className="mt-0.5 size-4 shrink-0 text-amber-300" />
          <span>Partial data: {partialErrors.join(", ")} could not be loaded. Available panels remain live.</span>
        </div>
      )}

      <section className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <MetricCard icon={<Sparkles className="size-4" />} label="Decision value" note={decisionValueMessage(data.metrics.decision_value)} tone={data.metrics.decision_value >= 0 ? "positive" : "warning"} value={formatSignedCurrency(data.metrics.decision_value)} />
        <MetricCard icon={<ShieldCheck className="size-4" />} label="Avoided loss" note={`${data.metrics.classification_counts.AVOIDED_LOSS} protected decision`} tone="positive" value={formatCurrency(data.metrics.avoided_loss)} />
        <MetricCard icon={<ArrowUpRight className="size-4" />} label="Missed alpha" note={`${data.metrics.classification_counts.MISSED_ALPHA} rejected winner`} tone="warning" value={formatCurrency(data.metrics.missed_alpha)} />
        <MetricCard icon={<Gauge className="size-4" />} label="Evaluated" note={`${data.shadowTrades.length} shadow trades tracked`} value={evaluated.toLocaleString()} />
        <div className="col-span-2 lg:col-span-1"><MetricCard icon={<WalletCards className="size-4" />} label="Executions" note="Paper ledger only" value={data.executions.length.toLocaleString()} /></div>
      </section>

      {data.executions.length === 0 && (
        <div className="mt-3 flex items-center gap-3 rounded-xl border border-sky-400/15 bg-sky-400/[0.045] px-4 py-3 text-xs text-slate-400">
          <ShieldCheck className="size-4 shrink-0 text-sky-300" />
          <span><strong className="font-medium text-slate-200">No live paper executions have been naturally accepted yet.</strong> Zero orders are recorded, and this dashboard has no trade controls.</span>
        </div>
      )}

      <section className="mt-5 grid items-start gap-5 lg:grid-cols-[minmax(320px,0.72fr)_minmax(0,1.28fr)]">
        <aside className="panel overflow-hidden rounded-2xl lg:sticky lg:top-5">
          <div className="border-b border-white/[0.07] p-4 sm:p-5">
            <div className="flex items-center justify-between gap-3">
              <div><p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Decision feed</p><p className="mt-1 text-xs text-slate-600">{data.decisions.length} decisions · {failedCandidates.length} safe failures</p></div>
              <Activity className="size-4 text-slate-600" />
            </div>
            <div className="mt-4 grid grid-cols-4 rounded-lg border border-white/[0.07] bg-black/20 p-1">
              {(["ALL", "ACCEPT", "REJECT", "FAILURES"] as FeedFilter[]).map((item) => (
                <button className={`rounded-md px-2 py-1.5 text-[10px] font-semibold tracking-wider transition ${filter === item ? "bg-white/[0.09] text-slate-200" : "text-slate-600 hover:text-slate-400"}`} key={item} onClick={() => setFilter(item)} type="button">{item}</button>
              ))}
            </div>
          </div>
          <div className="max-h-[620px] overflow-y-auto">
            {filter !== "FAILURES" && decisions.map((decision) => (
              <FeedRow candidate={candidatesById.get(decision.candidate_id)} decision={decision} key={decision.id} onSelect={() => setSelectedId(decision.id)} selected={decision.id === selectedId} />
            ))}
            {(filter === "ALL" || filter === "FAILURES") && failedCandidates.map((candidate) => <FailureRow candidate={candidate} key={`failure-${candidate.id}`} />)}
            {((filter === "FAILURES" && failedCandidates.length === 0) || (filter !== "ALL" && filter !== "FAILURES" && decisions.length === 0)) && (
              <div className="px-5 py-12 text-center text-sm text-slate-600">No {filter.toLowerCase()} decisions.</div>
            )}
          </div>
        </aside>

        <Inspector decision={selectedDecision} detail={detail} detailError={detailError} event={selectedEvent} loading={detailLoading} outcome={selectedOutcome} />
      </section>

      <footer className="mt-8 flex flex-col gap-2 border-t border-white/[0.06] pt-5 text-[10px] uppercase tracking-[0.14em] text-slate-700 sm:flex-row sm:items-center sm:justify-between">
        <span>Read-only decision review · no execution actions</span>
        <span className="font-mono normal-case tracking-normal">{API_BASE_URL}</span>
      </footer>
    </main>
  );
}
