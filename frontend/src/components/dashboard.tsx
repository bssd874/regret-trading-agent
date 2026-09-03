"use client";

import {
  AlertCircle,
  ArrowRight,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  RefreshCw,
  RotateCcw,
  UserRound,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CounterfactualGraph } from "@/components/counterfactual-graph";
import { useLanguage } from "@/i18n/language-provider";
import {
  agentStatusLabel,
  decisionStatusLabel,
  exitReasonLabel,
  type Language,
  type Translation,
} from "@/i18n/translations";
import {
  API_BASE_URL,
  api,
  loadDashboardData,
  type Candidate,
  type AgentStatus,
  type Classification,
  type DashboardData,
  type DecisionDetail,
  type DecisionListItem,
  type Execution,
  type Outcome,
  type RegretEvent,
  type TradeExit,
} from "@/lib/api";
import {
  formatCurrency,
  formatPercent,
  formatSignedCurrency,
  formatSignedPercent,
  toUserMessage,
} from "@/lib/presentation";
import {
  featuredReplayDecisionId,
  isMaterialDecisionValue,
  orderReplayDecisions,
  persistedReplayDecisionIds,
  signedDecisionValue,
  unsignedMagnitude,
} from "@/lib/regret-display";

type LoadState = "loading" | "ready" | "offline";
type DashboardSection = "overview" | "decisions" | "replay";

function sectionFromHash(hash: string): DashboardSection | null {
  const section = hash.replace(/^#/, "");
  return section === "overview" || section === "decisions" || section === "replay"
    ? section
    : null;
}

function useActiveDashboardSection() {
  const [activeSection, setActiveSection] = useState<DashboardSection>("overview");
  const workspaceSection = useRef<Exclude<DashboardSection, "overview">>("decisions");
  const navigationTarget = useRef<DashboardSection | null>(null);
  const navigationTimer = useRef<number | null>(null);

  const navigateTo = useCallback((section: DashboardSection) => {
    if (section !== "overview") workspaceSection.current = section;
    navigationTarget.current = section;
    setActiveSection(section);

    if (navigationTimer.current !== null) window.clearTimeout(navigationTimer.current);
    navigationTimer.current = window.setTimeout(() => {
      navigationTarget.current = null;
      navigationTimer.current = null;
    }, 800);
  }, []);

  useEffect(() => {
    let frame: number | null = null;

    const updateFromScroll = () => {
      if (frame !== null) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const hashSection = sectionFromHash(window.location.hash);
        if (hashSection === "decisions" || hashSection === "replay") {
          workspaceSection.current = hashSection;
        }

        const overview = document.getElementById("overview");
        const overviewIsPrimary = overview
          ? overview.getBoundingClientRect().bottom > Math.min(window.innerHeight * 0.28, 220)
          : true;
        const nextSection = navigationTarget.current
          ?? (overviewIsPrimary ? "overview" : workspaceSection.current);
        setActiveSection((current) => current === nextSection ? current : nextSection);
        frame = null;
      });
    };

    const updateFromHash = () => {
      const hashSection = sectionFromHash(window.location.hash);
      if (hashSection) {
        if (hashSection !== "overview") workspaceSection.current = hashSection;
        setActiveSection(hashSection);
      }
      updateFromScroll();
    };

    window.addEventListener("scroll", updateFromScroll, { passive: true });
    window.addEventListener("hashchange", updateFromHash);
    updateFromHash();

    return () => {
      window.removeEventListener("scroll", updateFromScroll);
      window.removeEventListener("hashchange", updateFromHash);
      if (frame !== null) window.cancelAnimationFrame(frame);
      if (navigationTimer.current !== null) window.clearTimeout(navigationTimer.current);
    };
  }, []);

  return { activeSection, navigateTo };
}

function classificationTone(classification: Classification): string {
  return {
    MISSED_ALPHA: "text-[#e9a19a]",
    AVOIDED_LOSS: "text-[#9bbcff]",
    CORRECT_EXECUTION: "text-emerald-300",
    BAD_EXECUTION: "text-red-300",
  }[classification];
}

function classificationMarker(classification: Classification): string {
  return {
    MISSED_ALPHA: "bg-[#e9a19a]",
    AVOIDED_LOSS: "bg-[#9bbcff]",
    CORRECT_EXECUTION: "bg-emerald-300",
    BAD_EXECUTION: "bg-red-300",
  }[classification];
}

function classificationLabel(
  classification: Classification,
  copy: Translation,
): string {
  return {
    MISSED_ALPHA: copy.replay.missedAlpha,
    AVOIDED_LOSS: copy.replay.avoidedLoss,
    CORRECT_EXECUTION: copy.replay.correctExecution,
    BAD_EXECUTION: copy.replay.badExecution,
  }[classification];
}

function classificationNarrative(
  event: RegretEvent,
  copy: Translation,
): string {
  const magnitude = formatCurrency(unsignedMagnitude(event.decision_value));
  return {
    MISSED_ALPHA: copy.replay.missedNarrative(magnitude),
    AVOIDED_LOSS: copy.replay.avoidedNarrative(magnitude),
    CORRECT_EXECUTION: copy.replay.correctNarrative(magnitude),
    BAD_EXECUTION: copy.replay.badNarrative(magnitude),
  }[event.classification];
}

function SkeletonDashboard() {
  return (
    <main className="mx-auto w-full max-w-[1600px] px-5 pb-16 sm:px-7" aria-busy="true">
      <div className="skeleton h-[100px] border-b border-white/10" />
      <div className="mt-12 grid gap-10 lg:grid-cols-[1fr_0.9fr]">
        <div className="skeleton h-56" />
        <div className="grid grid-cols-2 gap-7 sm:grid-cols-4">
          {[0, 1, 2, 3].map((item) => <div className="skeleton h-24" key={item} />)}
        </div>
      </div>
      <div className="mt-12 grid gap-10 lg:grid-cols-[minmax(300px,0.47fr)_minmax(0,1fr)]">
        <div className="skeleton h-[500px]" />
        <div className="skeleton h-[500px]" />
      </div>
      <span className="sr-only">Loading decision intelligence</span>
    </main>
  );
}

function LanguageControl() {
  const { language, setLanguage } = useLanguage();

  return (
    <div aria-label="Language" className="flex items-center gap-1.5 text-[11px] font-semibold" role="group">
      <button
        aria-pressed={language === "en"}
        className={language === "en" ? "text-white" : "text-slate-600 hover:text-slate-300"}
        onClick={() => setLanguage("en")}
        type="button"
      >
        EN
      </button>
      <span className="text-slate-700">|</span>
      <button
        aria-pressed={language === "id"}
        className={language === "id" ? "text-white" : "text-slate-600 hover:text-slate-300"}
        onClick={() => setLanguage("id")}
        type="button"
      >
        ID
      </button>
    </div>
  );
}

function DashboardHeader({
  backendHealthy,
  agentStatus,
  refreshing,
  onRefresh,
  copy,
}: {
  backendHealthy: boolean;
  agentStatus: AgentStatus | null;
  refreshing: boolean;
  onRefresh: () => void;
  copy: Translation;
}) {
  const { language } = useLanguage();
  const { activeSection, navigateTo } = useActiveDashboardSection();
  const navigation: Array<{ id: DashboardSection; label: string }> = [
    { id: "overview", label: copy.header.overview },
    { id: "decisions", label: copy.header.decisions },
    { id: "replay", label: copy.header.replay },
  ];

  return (
    <header className="flex min-h-[100px] flex-wrap items-center gap-x-8 gap-y-4 border-b border-[#3b4548] py-4">
      <div className="w-[265px] shrink-0">
        <h1 className="text-[29px] font-semibold leading-none tracking-[-0.04em] text-white">REGRET</h1>
        <p className="mt-1 text-[11px] font-semibold uppercase tracking-[0.02em] text-slate-300">{copy.header.subtitle}</p>
      </div>

      <nav className="order-3 flex h-full w-full min-w-0 items-center justify-between gap-3 text-[12px] font-semibold uppercase text-slate-300 sm:order-none sm:w-auto sm:flex-1 sm:justify-start sm:gap-10" aria-label="Dashboard sections">
        {navigation.map((item) => {
          const active = activeSection === item.id;
          return (
            <a
              aria-current={active ? "location" : undefined}
              className={`border-b py-[34px] transition ${active ? "border-cyan-300 text-cyan-300" : "border-transparent hover:text-white"}`}
              href={`#${item.id}`}
              key={item.id}
              onClick={() => navigateTo(item.id)}
            >
              {item.label}
            </a>
          );
        })}
      </nav>

      <div className="ml-auto flex h-12 items-center gap-6 border-l border-r border-[#3b4548] px-7 text-[12px] font-medium uppercase tracking-[0.12em] text-slate-300">
        <span className="flex flex-col gap-1 whitespace-nowrap">
          <span className="before:mr-1.5 before:text-slate-500 before:content-['•']">{copy.header.paperMode}</span>
          <span
            className={agentStatus?.enabled ? "text-cyan-300" : "text-slate-600"}
            data-agent-status={agentStatus?.mode ?? "OFFLINE"}
          >
            {agentStatusLabel(agentStatus, language)}
          </span>
        </span>
        <span className="flex items-center gap-1.5 whitespace-nowrap">
          <span className={`size-1.5 rounded-full ${backendHealthy ? "bg-emerald-300" : "bg-amber-300"}`} />
          {backendHealthy ? copy.header.apiHealthy : copy.header.apiDegraded}
        </span>
        <button aria-label={copy.header.refresh} className="text-slate-500 transition hover:text-cyan-300 disabled:opacity-50" disabled={refreshing} onClick={onRefresh} type="button">
          <RefreshCw className={`size-3.5 ${refreshing ? "animate-spin" : ""}`} />
        </button>
      </div>

      <LanguageControl />
      <span aria-hidden="true" className="flex size-10 items-center justify-center rounded-full bg-cyan-300 text-[#071012]"><UserRound className="size-4" /></span>
    </header>
  );
}

function OfflineState({ onRetry }: { onRetry: () => void }) {
  const { copy } = useLanguage();

  return (
    <main className="mx-auto flex min-h-screen max-w-xl items-center px-6 py-20">
      <section className="w-full border-y border-white/10 py-12 text-center">
        <AlertCircle className="mx-auto size-6 text-red-300" />
        <p className="mt-6 text-sm text-slate-500">{copy.states.backendOffline}</p>
        <h1 className="mt-2 text-3xl font-medium tracking-tight text-white">{copy.states.unavailable}</h1>
        <p className="mt-4 text-sm leading-6 text-slate-400">
          {copy.states.startApi(API_BASE_URL)} {copy.states.noSyntheticData}
        </p>
        <button className="mx-auto mt-7 flex items-center gap-2 border border-[#4a5558] px-5 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-slate-200 hover:border-cyan-300" onClick={onRetry} type="button">
          <RefreshCw className="size-4" /> {copy.states.retry}
        </button>
      </section>
    </main>
  );
}

function HeroMetric({
  value,
  label,
  note,
  tone,
}: {
  value: string;
  label: string;
  note: string;
  tone?: "blue" | "salmon";
}) {
  const toneClass = tone === "blue" ? "text-[#9bbcff]" : tone === "salmon" ? "text-[#e9a19a]" : "text-white";
  const markerClass = tone === "blue" ? "bg-[#9bbcff]" : tone === "salmon" ? "bg-[#e9a19a]" : "hidden";

  return (
    <div className="min-w-0">
      <p className={`editorial-number text-[20px] font-semibold tabular-nums ${toneClass}`}>{value}</p>
      <p className="mt-1 flex min-h-8 items-start gap-1.5 text-[11px] font-semibold leading-4 text-slate-300">
        <span className={`mt-1.5 size-1.5 shrink-0 ${markerClass}`} />{label}
      </p>
      <p className="mt-1 text-[12px] leading-5 text-slate-400">{note}</p>
    </div>
  );
}

function Hero({ data, copy }: { data: DashboardData; copy: Translation }) {
  const positive = data.metrics.decision_value >= 0;
  const protectedCount = data.metrics.classification_counts.AVOIDED_LOSS;
  const missedCount = data.metrics.classification_counts.MISSED_ALPHA;

  return (
    <section className="grid gap-12 border-b border-[#3b4548] py-10 lg:grid-cols-[1.05fr_0.95fr] lg:items-end lg:py-9" id="overview">
      <div>
        <p className="text-[12px] font-semibold uppercase tracking-[0.1em] text-slate-400">{copy.hero.decisionValue}</p>
        <p className="editorial-number mt-4 text-[46px] font-semibold leading-none tracking-[-0.035em] text-cyan-300 tabular-nums">
          {formatSignedCurrency(data.metrics.decision_value)}
        </p>
        <p className="mt-5 text-[18px] leading-7 text-slate-100">
          {positive ? copy.hero.positiveDescription : copy.hero.negativeDescription}
        </p>
        <p className="mt-2 max-w-[710px] text-[18px] leading-7 text-slate-400">{copy.hero.explanation}</p>
      </div>

      <div>
        <div className="grid grid-cols-2 gap-x-8 gap-y-8 sm:grid-cols-4">
          <HeroMetric label={copy.hero.avoidedLoss} note={`${protectedCount} ${protectedCount === 1 ? copy.hero.protectedDecision : copy.hero.protectedDecisions}`} tone="blue" value={formatCurrency(unsignedMagnitude(data.metrics.avoided_loss))} />
          <HeroMetric label={copy.hero.missedAlpha} note={`${missedCount} ${missedCount === 1 ? copy.hero.rejectedWinner : copy.hero.rejectedWinners}`} tone="salmon" value={formatCurrency(unsignedMagnitude(data.metrics.missed_alpha))} />
          <HeroMetric label={copy.hero.evaluated} note={`${data.shadowTrades.length} ${copy.hero.trackedShadows}`} value={data.metrics.total_decisions_evaluated.toLocaleString()} />
          <HeroMetric label={copy.hero.paperExecutions} note={data.executions.length === 0 ? copy.hero.noExecutions : copy.hero.paperLedger} value={data.executions.length.toLocaleString()} />
        </div>
        <dl className="mt-6 flex flex-wrap gap-x-8 gap-y-2 border-t border-[#3b4548] pt-4 text-[10px] uppercase tracking-[0.06em] text-slate-500">
          <div className="flex gap-2"><dt>{copy.hero.correctExecutionValue}</dt><dd className="font-mono text-emerald-300">{formatCurrency(unsignedMagnitude(data.metrics.correct_execution_value))}</dd></div>
          <div className="flex gap-2"><dt>{copy.hero.badExecutionLoss}</dt><dd className="font-mono text-red-300">{formatCurrency(unsignedMagnitude(data.metrics.bad_execution_loss))}</dd></div>
        </dl>
      </div>
    </section>
  );
}

function DecisionStream({
  decisions,
  failedCandidates,
  replayReadyIds,
  events,
  selectedId,
  onSelect,
  language,
  copy,
}: {
  decisions: DecisionListItem[];
  failedCandidates: Candidate[];
  replayReadyIds: ReadonlySet<number>;
  events: RegretEvent[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  language: Language;
  copy: Translation;
}) {
  const orderedDecisions = useMemo(
    () => orderReplayDecisions(decisions, events, selectedId),
    [decisions, events, selectedId],
  );
  const eventByDecisionId = useMemo(
    () => new Map(events.map((event) => [event.risk_decision_id, event])),
    [events],
  );

  return (
    <section className="min-w-0" id="decisions">
      <h2 className="text-[12px] font-semibold uppercase tracking-[0.1em] text-slate-300">{copy.stream.title}</h2>
      <div className="terminal-scroll mt-3 max-h-[520px] overflow-y-auto pr-2">
        {orderedDecisions.map((decision) => {
          const selected = decision.id === selectedId;
          const replayReady = replayReadyIds.has(decision.id);
          const event = eventByDecisionId.get(decision.id);
          const materialEvent = event && isMaterialDecisionValue(event.decision_value);
          return (
            <button
              aria-pressed={selected}
              className={`relative w-full border-t border-[#445053] px-3 py-5 text-left transition hover:bg-white/[0.03] ${selected ? "bg-[#292d2e] pl-4 before:absolute before:inset-y-0 before:left-0 before:w-[2px] before:bg-cyan-300" : ""}`}
              key={decision.id}
              onClick={() => onSelect(decision.id)}
              type="button"
            >
              <div className="flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                    <span className="text-[18px] text-slate-100">{decision.symbol}</span>
                    <span className="bg-[#202526] px-1.5 py-0.5 text-[9px] font-semibold text-slate-200">{decisionStatusLabel(decision.decision, language)}</span>
                    {replayReady && (
                      <span className="flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-[0.04em] text-cyan-300/70">
                        <span className="size-1 rounded-full bg-cyan-300/80" />
                        {copy.stream.replayReady}
                      </span>
                    )}
                    {event && (
                      <span className={`text-[9px] font-semibold uppercase tracking-[0.04em] ${materialEvent ? classificationTone(event.classification) : "text-slate-600"}`}>
                        {classificationLabel(event.classification, copy)}
                      </span>
                    )}
                  </div>
                  <p className="editorial-number mt-2 text-[15px] text-slate-300">
                    {copy.stream.confidence}: {formatPercent(decision.adjusted_confidence)}
                    <span className="mx-1.5 text-slate-600">|</span>
                    {copy.stream.risk}: {decision.risk_score.toFixed(1)}
                  </p>
                  {decision.degraded_mode && <p className="mt-1.5 text-[10px] text-violet-300/80">{copy.stream.fallbackCritic}</p>}
                </div>
                {selected && <ArrowRight className="size-4 shrink-0 text-cyan-300" />}
              </div>
            </button>
          );
        })}
        {failedCandidates.map((candidate) => (
          <div className="border-t border-[#445053] px-3 py-5" key={`failure-${candidate.id}`}>
            <div className="flex items-center gap-2.5">
              <span className="text-[18px] text-slate-400">{candidate.symbol}</span>
              <span className="bg-[#202526] px-1.5 py-0.5 text-[9px] font-semibold text-slate-300">{decisionStatusLabel(candidate.status, language)}</span>
            </div>
            <p className="mt-2 text-[11px] text-slate-600">{copy.stream.safeFailure}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function RealizedTradeReplay({
  execution,
  tradeExit,
  outcome,
  event,
  replayKey,
  onReplay,
  language,
  copy,
}: {
  execution: Execution;
  tradeExit: TradeExit;
  outcome: Outcome;
  event: RegretEvent;
  replayKey: number;
  onReplay: () => void;
  language: Language;
  copy: Translation;
}) {
  const entryPrice = execution.filled_avg_price as number;
  const entryQuantity = execution.filled_qty as number;
  const exitPrice = tradeExit.filled_avg_price as number;
  const material = isMaterialDecisionValue(event.decision_value);
  const valueTone = material ? classificationTone(event.classification) : "text-slate-400";
  const performanceTone = outcome.pnl_pct < 0 ? "text-red-300" : outcome.pnl_pct > 0 ? "text-emerald-300" : "text-slate-200";

  return (
    <section className="min-h-[500px] border border-[#465154] bg-[#1b1f20] px-8 py-9 lg:px-11 lg:py-10" id="replay">
      <h2 className="sr-only">{copy.replay.title}</h2>
      <div className="grid gap-6 sm:grid-cols-[minmax(0,1fr)_230px] sm:items-start">
        <div>
          <p className="text-[19px] text-slate-100">{copy.replay.saidYes}</p>
          <p className="mt-3 text-[18px] leading-7 text-slate-300">{copy.replay.acceptedIntro}</p>
        </div>
        <div className="sm:text-right">
          <p className={`editorial-number text-[27px] font-semibold tabular-nums ${valueTone}`}>{formatSignedCurrency(event.decision_value)}</p>
          <p className={`mt-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] sm:justify-end ${valueTone}`}>
            <span className={`size-1.5 ${material ? classificationMarker(event.classification) : "bg-slate-600"}`} />{classificationLabel(event.classification, copy)}
          </p>
          <p className="mt-2 text-[11px] text-slate-500">{copy.replay.decisionValue}</p>
        </div>
      </div>

      <div className="mt-8 grid border-y border-[#465154] py-6 lg:grid-cols-2">
        <dl className="grid grid-cols-2 gap-x-6 lg:pr-8">
          {[
            [copy.replay.buy, formatCurrency(entryPrice), "text-slate-100"],
            [copy.replay.filledQuantity, entryQuantity.toLocaleString("en-US", { maximumFractionDigits: 8 }), "text-slate-100"],
            [copy.replay.originalTarget, formatCurrency(tradeExit.target_price), "text-slate-100"],
            [copy.replay.originalStop, formatCurrency(tradeExit.stop_loss), "text-slate-100"],
            [copy.replay.originalHorizon, `${tradeExit.horizon_minutes} ${copy.replay.minutes}`, "text-slate-100"],
            [copy.replay.exitReason, exitReasonLabel(tradeExit.reason, language), "text-slate-100"],
            [copy.replay.sell, formatCurrency(exitPrice), "text-slate-100"],
            [copy.replay.realizedPerformance, formatSignedPercent(outcome.pnl_pct, 3), performanceTone],
            [copy.replay.realizedPnl, formatSignedCurrency(outcome.pnl_amount), performanceTone],
            [copy.replay.classification, classificationLabel(event.classification, copy), valueTone],
          ].map(([label, value, tone], index) => (
            <div className={`min-w-0 py-2.5 ${index > 1 ? "border-t border-[#465154]" : ""}`} key={label}>
              <dt className="text-[10px] font-semibold uppercase tracking-[0.04em] text-slate-400">{label}</dt>
              <dd className={`editorial-number mt-1 text-[16px] font-semibold tabular-nums ${tone}`}>{value}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-7 border-t border-[#465154] pt-4 lg:mt-0 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
          <CounterfactualGraph entryLabel={copy.replay.buy} entryPrice={entryPrice} evaluationLabel={copy.replay.sell} evaluationPrice={exitPrice} replayKey={replayKey} variant="realized" />
          <p className="text-right text-[10px] text-slate-600">{copy.replay.confirmedFills}</p>
        </div>
      </div>

      <div className="flex flex-col gap-6 pt-7 sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-[610px] text-[17px] leading-7 text-slate-200">{material ? classificationNarrative(event, copy) : copy.replay.neutralNarrative}</p>
        <button className="shrink-0 border border-[#536064] px-7 py-4 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-100 transition hover:border-cyan-300 hover:text-cyan-200" onClick={onReplay} type="button">
          <RotateCcw className="mr-2 inline size-3.5" />{copy.replay.replayDecision}
        </button>
      </div>
    </section>
  );
}

function ReplaySurface({
  decision,
  outcome,
  event,
  execution,
  tradeExit,
  replayKey,
  onReplay,
  language,
  copy,
}: {
  decision?: DecisionListItem;
  outcome?: Outcome;
  event?: RegretEvent;
  execution?: Execution;
  tradeExit?: TradeExit;
  replayKey: number;
  onReplay: () => void;
  language: Language;
  copy: Translation;
}) {
  if (!decision) {
    return (
      <section className="flex min-h-[500px] items-center justify-center border border-[#465154] bg-[#1b1f20] px-8 text-center" id="replay">
        <p className="text-sm text-slate-500">{copy.states.noDecision}</p>
      </section>
    );
  }

  const rejected = decision.decision === "REJECT";
  const completedTrade = !rejected
    && outcome
    && event
    && execution
    && tradeExit
    && execution.status.toLowerCase() === "filled"
    && tradeExit.status.toLowerCase() === "filled"
    && execution.filled_avg_price !== null
    && execution.filled_qty !== null
    && tradeExit.filled_avg_price !== null
    && tradeExit.filled_qty !== null;

  if (completedTrade) {
    return <RealizedTradeReplay copy={copy} event={event} execution={execution} language={language} onReplay={onReplay} outcome={outcome} replayKey={replayKey} tradeExit={tradeExit} />;
  }

  if (!rejected || !outcome || !event) {
    return (
      <section className="flex min-h-[500px] items-center justify-center border border-[#465154] bg-[#1b1f20] px-8 text-center" id="replay">
        <div>
          <Clock3 className="mx-auto size-5 text-slate-600" />
          <p className="mt-3 text-sm text-slate-300">{copy.replay.noOutcome}</p>
          <p className="mt-1 text-xs text-slate-500">{copy.replay.outcomePending}</p>
        </div>
      </section>
    );
  }

  const material = isMaterialDecisionValue(event.decision_value);
  const performanceTone = outcome.pnl_pct < 0 ? "text-[#e9a19a]" : outcome.pnl_pct > 0 ? "text-cyan-300" : "text-slate-200";
  const eventTone = material ? classificationTone(event.classification) : "text-slate-400";

  return (
    <section className="min-h-[500px] border border-[#465154] bg-[#1b1f20] px-8 py-9 lg:px-11 lg:py-10" id="replay">
      <h2 className="sr-only">{copy.replay.title}</h2>
      <div className="grid gap-6 sm:grid-cols-[minmax(0,1fr)_230px] sm:items-start">
        <div>
          <p className="text-[19px] text-slate-100">{copy.replay.saidNo}</p>
          <p className="mt-3 min-h-7 text-[18px] leading-7 text-slate-300">
            {copy.replay.rejectedQuestion(decision.symbol)}
          </p>
        </div>
        <div className="sm:text-right">
          <p className={`editorial-number text-[27px] font-semibold tabular-nums ${eventTone}`}>
            {formatCurrency(unsignedMagnitude(event.decision_value))}
          </p>
          <p className={`mt-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] sm:justify-end ${eventTone}`}>
            <span className={`size-1.5 ${material ? classificationMarker(event.classification) : "bg-slate-600"}`} />
            {classificationLabel(event.classification, copy)}
          </p>
          <p className="mt-2 text-[11px] text-slate-500">{copy.replay.decisionValue}: {formatSignedCurrency(signedDecisionValue(event.decision_value))}</p>
        </div>
      </div>

      <div className="mt-10 grid border-y border-[#465154] py-7 md:grid-cols-[0.95fr_1.05fr]">
        <dl className="md:pr-10">
          {[
            [copy.replay.entryScenario, formatCurrency(outcome.entry_price), "text-slate-100"],
            [copy.replay.evaluatedAt, formatCurrency(outcome.evaluation_price), "text-slate-100"],
            [copy.replay.hypotheticalPerformance, formatSignedPercent(outcome.pnl_pct), performanceTone],
          ].map(([label, value, tone], index) => (
            <div className={`flex items-center justify-between gap-5 py-3 ${index > 0 ? "border-t border-[#465154]" : ""}`} key={label}>
              <dt className="text-[11px] font-semibold uppercase tracking-[0.04em] text-slate-300">{label}</dt>
              <dd className={`editorial-number text-[18px] font-semibold tabular-nums ${tone}`}>{value}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-7 border-t border-[#465154] pt-4 md:mt-0 md:border-l md:border-t-0 md:pl-8 md:pt-0">
          <CounterfactualGraph
            entryLabel={copy.replay.entryPoint}
            entryPrice={outcome.entry_price}
            evaluationLabel={copy.replay.evaluationPoint}
            evaluationPrice={outcome.evaluation_price}
            replayKey={replayKey}
          />
          <p className="text-right text-[10px] text-slate-600">{copy.replay.factualPoints}</p>
        </div>
      </div>

      <div className="flex flex-col gap-6 pt-8 sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-[610px] text-[17px] leading-7 text-slate-200">{material ? classificationNarrative(event, copy) : copy.replay.neutralNarrative}</p>
        <button className="shrink-0 border border-[#536064] px-7 py-4 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-100 transition hover:border-cyan-300 hover:text-cyan-200" onClick={onReplay} type="button">
          <RotateCcw className="mr-2 inline size-3.5" />{copy.replay.replayDecision}
        </button>
      </div>
    </section>
  );
}

type AuditNode = {
  label: string;
  value: string;
  detail?: string;
  critic?: boolean;
  risk?: boolean;
};

function buildAuditTrailNodes(
  decision: DecisionListItem,
  detail: DecisionDetail,
  outcome: Outcome | undefined,
  event: RegretEvent | undefined,
  execution: Execution | undefined,
  tradeExit: TradeExit | undefined,
  language: Language,
  copy: Translation,
): AuditNode[] {
  const pipeline: AuditNode[] = [
    { label: copy.audit.marketScout, value: copy.audit.candidateDiscovered },
    { label: copy.audit.azureAnalyst, value: copy.audit.confidence(formatPercent(detail.analyst.confidence)) },
    {
      label: copy.audit.adversarialCritic,
      value: `${detail.critic.verdict === "CHALLENGE" ? copy.audit.challenge : copy.audit.pass} (${formatSignedPercent(detail.critic.confidence_adjustment)})`,
      detail: detail.critic.degraded_mode ? "Fallback Critic" : detail.critic.provider,
      critic: true,
    },
    { label: copy.audit.consensus, value: copy.audit.adjustedConfidence(formatPercent(detail.consensus.adjusted_confidence)) },
  ];
  const riskDetail = detail.risk.reasons.join(" · ") || undefined;

  if (decision.decision === "REJECT") {
    return [
      ...pipeline,
      { label: copy.audit.riskGate, value: copy.audit.noTrade, detail: riskDetail, risk: true },
      { label: copy.audit.noTrade, value: copy.stream.noTrade },
      { label: copy.audit.shadowOutcome, value: outcome ? formatSignedPercent(outcome.pnl_pct, 3) : "—" },
      { label: copy.audit.regretClassification, value: event ? classificationLabel(event.classification, copy) : "—" },
    ];
  }

  return [
    ...pipeline,
    { label: copy.audit.riskGate, value: copy.audit.trade, detail: riskDetail, risk: true },
    {
      label: copy.audit.buyFilled,
      value: execution?.filled_avg_price != null ? formatCurrency(execution.filled_avg_price) : "—",
      detail: execution?.filled_qty != null ? execution.filled_qty.toLocaleString("en-US", { maximumFractionDigits: 8 }) : undefined,
    },
    { label: copy.audit.exitMonitor, value: tradeExit ? `${tradeExit.horizon_minutes} ${copy.replay.minutes}` : "—" },
    { label: copy.audit.exitReason, value: tradeExit ? exitReasonLabel(tradeExit.reason, language) : "—" },
    {
      label: copy.audit.sellFilled,
      value: tradeExit?.filled_avg_price != null ? formatCurrency(tradeExit.filled_avg_price) : "—",
      detail: tradeExit?.filled_qty != null ? tradeExit.filled_qty.toLocaleString("en-US", { maximumFractionDigits: 8 }) : undefined,
    },
    { label: copy.audit.regretClassification, value: event ? classificationLabel(event.classification, copy) : "—" },
  ];
}

function AuditTrail({
  decision,
  detail,
  detailError,
  loading,
  stage,
  outcome,
  event,
  execution,
  tradeExit,
  language,
  copy,
}: {
  decision?: DecisionListItem;
  detail: DecisionDetail | null;
  detailError: string | null;
  loading: boolean;
  stage: number;
  outcome?: Outcome;
  event?: RegretEvent;
  execution?: Execution;
  tradeExit?: TradeExit;
  language: Language;
  copy: Translation;
}) {
  if (!decision) return null;

  const trade = decision.decision === "ACCEPT";
  const title = trade ? copy.audit.tradeTitle : copy.audit.title;
  const auditNodes = detail ? buildAuditTrailNodes(decision, detail, outcome, event, execution, tradeExit, language, copy) : [];

  return (
    <section className="py-12" aria-label={title}>
      <h2 className="text-[18px] text-slate-100">{title}</h2>

      {loading ? (
        <div className="mt-10 grid gap-6 sm:grid-cols-5">{[0, 1, 2, 3, 4].map((item) => <div className="skeleton h-24" key={item} />)}</div>
      ) : detailError ? (
        <div className="mt-8 border-l border-[#e9a19a] pl-4 text-sm text-[#e9a19a]">{copy.states.detailsUnavailable} {detailError}</div>
      ) : detail ? (
        <>
          <ol className="terminal-scroll relative mt-10 grid auto-cols-[minmax(112px,1fr)] grid-flow-col gap-y-7 overflow-x-auto pb-4">
            <div className="absolute left-5 right-5 top-[5px] hidden border-t border-[#333c3f] sm:block" />
            {auditNodes.map((item, index) => (
              <li className="relative px-2 text-center sm:px-3" key={`${item.label}-${index}`}>
                <span className={`relative z-10 mx-auto block size-2.5 border-2 ${index === stage ? "border-cyan-200 bg-cyan-300 ring-2 ring-cyan-300/25" : index < stage ? "border-[#4a5558] bg-[#4a5558]" : "border-[#4a5558] bg-[#0f1314]"}`} />
                <p className={`editorial-number mt-5 text-[14px] ${item.risk ? "text-cyan-300" : "text-slate-300"}`}>{String(index + 1).padStart(2, "0")} {item.label}</p>
                <p className={`mt-2 text-[17px] leading-6 ${item.critic && detail.critic.verdict === "CHALLENGE" ? "text-[#e9a19a]" : "text-slate-100"}`}>{item.value}</p>
                {item.detail && <p className="mt-1 text-[11px] text-slate-600">{item.detail}</p>}
              </li>
            ))}
          </ol>

          <details className="mt-12 border-t border-[#30383b] pt-5">
            <summary className="cursor-pointer text-[12px] font-semibold uppercase tracking-[0.08em] text-slate-400 hover:text-slate-100">{copy.audit.persistedDetails}</summary>
            <p className="mt-2 text-xs text-slate-600">{copy.audit.persistedNote}</p>
            <div className="mt-8 grid gap-10 lg:grid-cols-2 lg:gap-0">
              <article className="lg:pr-10">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h3 className="flex items-center gap-2 text-base text-slate-100"><BrainCircuit className="size-4 text-slate-500" />{copy.audit.analystRecord}</h3>
                  <span className="text-xs text-slate-600">{detail.analyst.provider} · {detail.analyst.model}</span>
                </div>
                <p className="mt-5 text-sm leading-7 text-slate-300">{detail.analyst.thesis}</p>
                <dl className="mt-6 grid grid-cols-4 gap-3 border-y border-[#30383b] py-4">
                  {[
                    [copy.audit.confidenceLabel, formatPercent(detail.analyst.confidence)],
                    [copy.audit.entry, formatCurrency(detail.analyst.entry_price)],
                    [copy.audit.stop, formatCurrency(detail.analyst.stop_loss)],
                    [copy.audit.target, formatCurrency(detail.analyst.target_price)],
                  ].map(([label, value]) => <div className="min-w-0" key={label}><dt className="text-[11px] text-slate-600">{label}</dt><dd className="mt-1.5 truncate font-mono text-xs text-slate-300">{value}</dd></div>)}
                </dl>
                <p className="mt-5 text-xs text-slate-600">{copy.audit.invalidation}</p>
                <p className="mt-1.5 text-xs leading-6 text-slate-500">{detail.analyst.invalidation}</p>
                <p className="mt-5 text-xs text-slate-600">{copy.audit.evidence}</p>
                <ul className="mt-2 space-y-2 border-l border-[#30383b] pl-4 text-xs leading-6 text-slate-500">{detail.analyst.evidence.slice(0, 3).map((item) => <li key={item}>{item}</li>)}</ul>
              </article>

              <article className="border-t border-[#30383b] pt-10 lg:border-l lg:border-t-0 lg:pl-10 lg:pt-0">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h3 className="flex items-center gap-2 text-base text-slate-100"><Bot className="size-4 text-slate-500" />{detail.critic.degraded_mode ? "Fallback Critic" : copy.audit.adversarialCritic}</h3>
                  <span className="text-xs text-slate-600">{detail.critic.provider} · {detail.critic.model}</span>
                </div>
                <dl className="mt-6 grid grid-cols-3 gap-3 border-y border-[#30383b] py-4">
                  <div><dt className="text-[11px] text-slate-600">{copy.audit.verdict}</dt><dd className="mt-1.5 flex items-center gap-1.5 font-mono text-xs text-slate-300">{detail.critic.verdict === "PASS" ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}{detail.critic.verdict}</dd></div>
                  <div><dt className="text-[11px] text-slate-600">{copy.audit.adjustment}</dt><dd className="mt-1.5 font-mono text-xs text-slate-300">{formatSignedPercent(detail.critic.confidence_adjustment)}</dd></div>
                  <div><dt className="text-[11px] text-slate-600">{copy.audit.consistency}</dt><dd className="mt-1.5 font-mono text-xs text-slate-300">{formatPercent(detail.critic.thesis_consistency)}</dd></div>
                </dl>
                <p className="mt-5 text-xs text-slate-600">{copy.audit.concerns}</p>
                <ul className="mt-2 space-y-3 border-l border-[#30383b] pl-4 text-xs leading-6 text-slate-500">{detail.critic.concerns.slice(0, 3).map((concern) => <li key={concern}>{concern}</li>)}</ul>
                <div className="mt-6 border-t border-[#30383b] pt-4">
                  <p className="text-xs text-slate-600">{copy.audit.riskSummary}</p>
                  <p className="mt-2 font-mono text-sm text-slate-300">R:R {detail.risk.reward_risk_ratio.toFixed(2)} / Risk {detail.risk.risk_score.toFixed(1)} / {decisionStatusLabel(detail.risk.decision, language)}</p>
                </div>
              </article>
            </div>
          </details>
        </>
      ) : null}
    </section>
  );
}

export function Dashboard() {
  const { language, copy } = useLanguage();
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [data, setData] = useState<DashboardData | null>(null);
  const [partialErrors, setPartialErrors] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detailState, setDetailState] = useState<{
    id: number;
    data: DecisionDetail | null;
    error: string | null;
  } | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [replayKey, setReplayKey] = useState(0);
  const [replayStage, setReplayStage] = useState(4);

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
      setSelectedId((current) => {
        if (current !== null) return current;
        const featuredId = featuredReplayDecisionId(result.data.outcomes, result.data.regretEvents);
        if (featuredId !== null) return featuredId;
        const evaluatedIds = new Set(result.data.regretEvents.map((event) => event.risk_decision_id));
        return result.data.decisions.find((decision) => !evaluatedIds.has(decision.id))?.id ?? null;
      });
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

  const failedCandidates = useMemo(
    () => data?.candidates.filter((candidate) => ["ANALYSIS_FAILED", "CRITIC_FAILED", "RISK_FAILED"].includes(candidate.status)) ?? [],
    [data],
  );
  const replayReadyIds = useMemo(
    () => persistedReplayDecisionIds(data?.outcomes ?? [], data?.regretEvents ?? []),
    [data],
  );
  const selectedDecision = data?.decisions.find((decision) => decision.id === selectedId);
  const selectedOutcome = data?.outcomes.find((outcome) => outcome.risk_decision_id === selectedId);
  const selectedEvent = data?.regretEvents.find((event) => event.risk_decision_id === selectedId);
  const selectedExecution = data?.executions.find((execution) => execution.risk_decision_id === selectedId);
  const selectedExit = data?.exits.find((tradeExit) => tradeExit.executed_trade_id === selectedExecution?.id);
  const detail = detailState?.id === selectedId ? detailState.data : null;
  const detailError = detailState?.id === selectedId ? detailState.error : null;
  const detailLoading = selectedId !== null && detailState?.id !== selectedId;

  function replay() {
    setReplayKey((value) => value + 1);
    setReplayStage(0);
    const finalStage = selectedDecision?.decision === "ACCEPT" ? 9 : 7;
    for (let nextStage = 1; nextStage <= finalStage; nextStage += 1) {
      window.setTimeout(() => setReplayStage(nextStage), nextStage * 260);
    }
  }

  if (loadState === "loading") return <SkeletonDashboard />;
  if (loadState === "offline" || !data) return <OfflineState onRetry={() => void load()} />;

  return (
    <main className="mx-auto w-full max-w-[1600px] px-5 pb-5 sm:px-7">
      <DashboardHeader agentStatus={data.agentStatus} backendHealthy={data.health?.status === "ok"} copy={copy} onRefresh={() => void load(true)} refreshing={refreshing} />

      {partialErrors.length > 0 && (
        <div className="mt-4 flex items-start gap-3 border-l border-[#e9a19a] pl-4 text-xs leading-5 text-[#e9a19a]">
          <AlertCircle className="mt-0.5 size-4 shrink-0" /><span>{copy.states.partialData} ({partialErrors.join(", ")})</span>
        </div>
      )}

      <Hero copy={copy} data={data} />

      <section className="grid gap-10 border-b border-[#3b4548] py-12 lg:grid-cols-[minmax(310px,0.47fr)_minmax(0,1fr)] lg:items-start">
        <DecisionStream copy={copy} decisions={data.decisions} events={data.regretEvents} failedCandidates={failedCandidates} language={language} onSelect={setSelectedId} replayReadyIds={replayReadyIds} selectedId={selectedId} />
        <ReplaySurface copy={copy} decision={selectedDecision} event={selectedEvent} execution={selectedExecution} language={language} onReplay={replay} outcome={selectedOutcome} replayKey={replayKey} tradeExit={selectedExit} />
      </section>

      <AuditTrail copy={copy} decision={selectedDecision} detail={detail} detailError={detailError} event={selectedEvent} execution={selectedExecution} language={language} loading={detailLoading} outcome={selectedOutcome} stage={replayStage} tradeExit={selectedExit} />

      <footer className="flex flex-col gap-2 border-t border-[#30383b] py-5 text-[10px] uppercase tracking-[0.08em] text-slate-700 sm:flex-row sm:items-center sm:justify-between">
        <span>{copy.footer}</span><span className="font-mono normal-case tracking-normal">{API_BASE_URL}</span>
      </footer>
    </main>
  );
}
