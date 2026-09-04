"use client";

import { useState } from "react";
import { ShieldCheck, ShieldOff, Loader2 } from "lucide-react";

import { useLanguage } from "@/i18n/language-provider";
import {
  canSubmitOperatorAction,
  operatorView,
  type OperatorAction,
  type RuntimeControl,
} from "@/lib/operator";

const TONE_CLASS: Record<string, string> = {
  armed: "text-cyan-300",
  starting: "text-amber-300",
  idle: "text-slate-300",
  blocked: "text-slate-600",
};

export function OperatorControl({
  runtimeControl,
  onChanged,
}: {
  runtimeControl: RuntimeControl | null;
  onChanged: () => void;
}) {
  const { copy } = useLanguage();
  const text = copy.operator;
  const view = operatorView(runtimeControl, text);

  const [openAction, setOpenAction] = useState<OperatorAction | null>(null);
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setOpenAction(null);
    setPassword("");
    setError(null);
  };

  async function submit() {
    if (!openAction || openAction === "NONE") return;
    if (!canSubmitOperatorAction(password)) {
      setError(text.errorPassword);
      return;
    }

    setPending(true);
    setError(null);
    try {
      const response = await fetch(
        openAction === "ARM" ? "/api/operator/arm" : "/api/operator/disarm",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password }),
        },
      );

      if (response.ok) {
        close();
        onChanged();
        return;
      }
      if (response.status === 401) setError(text.errorPassword);
      else if (response.status === 409) setError(text.errorConflict);
      else if (response.status === 503) setError(text.errorUnavailable);
      else setError(text.errorGeneric);
    } catch {
      setError(text.errorGeneric);
    } finally {
      // The password is never retained beyond the request.
      setPassword("");
      setPending(false);
    }
  }

  return (
    <section
      aria-label={text.title}
      className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b border-[#3b4548] py-4"
      data-entry-state={view.entryState}
      data-testid="operator-control"
    >
      <div className="flex min-w-[260px] flex-col gap-1">
        <span
          className={`text-[12px] font-semibold uppercase tracking-[0.12em] ${TONE_CLASS[view.tone]}`}
          data-testid="operator-status"
        >
          {view.statusLabel}
        </span>
        <span className="text-[11px] text-slate-500" data-testid="operator-detail">
          {view.detailLabel}
        </span>
      </div>

      {view.countdown ? (
        <span className="flex flex-col gap-1 text-[11px] uppercase tracking-[0.1em] text-slate-500">
          <span className="font-mono text-[15px] text-white" data-testid="operator-countdown">
            {view.countdown}
          </span>
          {text.remaining}
        </span>
      ) : null}

      <span className="flex flex-col gap-1 text-[11px] uppercase tracking-[0.1em] text-slate-500">
        <span className="text-[13px] text-white" data-testid="operator-budget">
          {view.budgetLabel}
        </span>
        {text.budget}
      </span>

      {view.showPositionMonitor ? (
        <span className="text-[11px] text-cyan-300" data-testid="operator-monitor-note">
          {text.openPositionMonitorRemains}
        </span>
      ) : null}

      {view.action !== "NONE" && view.actionLabel ? (
        <button
          className="ml-auto flex items-center gap-2 border border-[#3b4548] px-4 py-2 text-[12px] font-semibold uppercase tracking-[0.1em] text-white transition hover:border-cyan-300 hover:text-cyan-300"
          data-testid={view.action === "ARM" ? "operator-arm" : "operator-disarm"}
          onClick={() => setOpenAction(view.action)}
          type="button"
        >
          {view.action === "ARM" ? <ShieldCheck className="size-3.5" /> : <ShieldOff className="size-3.5" />}
          {view.actionLabel}
        </button>
      ) : null}

      {openAction ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6" role="dialog" aria-modal="true" aria-label={text.modalTitle}>
          <div className="w-full max-w-lg border border-[#3b4548] bg-[#0b1014] p-7">
            <h2 className="text-[17px] font-semibold text-white">
              {openAction === "ARM" ? text.modalTitle : text.disarmAction}
            </h2>
            <p className="mt-4 text-[13px] leading-6 text-slate-400">
              {openAction === "ARM" ? text.modalBody : text.openPositionMonitorRemains}
            </p>

            {openAction === "ARM" ? (
              <ul className="mt-5 space-y-1.5 text-[12px] text-slate-400">
                {[
                  text.limitPaperOnly,
                  text.limitOneExecution,
                  text.limitArmWindow,
                  text.limitCritic,
                  text.limitRiskGate,
                  text.limitExitSafety,
                ].map((limit) => (
                  <li className="before:mr-2 before:text-cyan-300 before:content-['•']" key={limit}>
                    {limit}
                  </li>
                ))}
              </ul>
            ) : null}

            <label className="mt-6 block text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500" htmlFor="operator-password">
              {text.passwordLabel}
            </label>
            <input
              autoComplete="current-password"
              className="mt-2 w-full border border-[#3b4548] bg-transparent px-3 py-2 text-[14px] text-white outline-none focus:border-cyan-300"
              data-testid="operator-password"
              id="operator-password"
              onChange={(event) => setPassword(event.target.value)}
              placeholder={text.passwordPlaceholder}
              type="password"
              value={password}
            />

            {error ? (
              <p className="mt-3 text-[12px] text-red-300" data-testid="operator-error" role="alert">
                {error}
              </p>
            ) : null}

            <div className="mt-7 flex justify-end gap-3">
              <button
                className="px-4 py-2 text-[12px] font-semibold uppercase tracking-[0.1em] text-slate-400 transition hover:text-white"
                disabled={pending}
                onClick={close}
                type="button"
              >
                {text.cancel}
              </button>
              <button
                className="flex items-center gap-2 border border-cyan-300 px-4 py-2 text-[12px] font-semibold uppercase tracking-[0.1em] text-cyan-300 transition hover:bg-cyan-300 hover:text-[#071012] disabled:opacity-50"
                data-testid="operator-confirm"
                disabled={pending || !canSubmitOperatorAction(password)}
                onClick={submit}
                type="button"
              >
                {pending ? <Loader2 className="size-3.5 animate-spin" /> : null}
                {pending ? text.working : openAction === "ARM" ? text.confirm : text.disarmAction}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
