/**
 * Pure view logic for the operator runtime control.
 *
 * The operator never chooses a symbol, a side, a price, or a risk outcome.
 * These helpers only describe whether REGRET is currently permitted to open a
 * NEW autonomous paper position, and what the single available action is.
 */

export type RuntimeControlState = "DISARMED" | "START_REQUESTED" | "ARMED";

export type EntryExecutionState =
  | "MASTER_DISABLED"
  | "DISARMED"
  | "STARTING"
  | "ARMED"
  | "EXPIRED"
  | "BUDGET_EXHAUSTED";

export type RuntimeControl = {
  state: RuntimeControlState;
  new_entries_armed: boolean;
  effective_new_entries_armed: boolean;
  entry_execution_state: EntryExecutionState;
  master_execution_available: boolean;
  armed_at: string | null;
  armed_until: string | null;
  request_expires_at: string | null;
  start_requested_at: string | null;
  executions_used: number;
  max_new_executions: number;
  last_disarm_reason: string | null;
  last_cycle_id: number | null;
  arm_ttl_minutes: number;
  seconds_remaining: number;
  dispatch_configured: boolean;
};

export type OperatorAction = "ARM" | "DISARM" | "NONE";

export type OperatorCopy = {
  disarmed: string;
  newEntriesBlocked: string;
  newEntriesDisarmed: string;
  starting: string;
  waitingForCycle: string;
  armed: string;
  analysisEnabled: string;
  armAction: string;
  disarmAction: string;
  remaining: string;
  budget: string;
  budgetUsed: string;
  positionMonitorActive: string;
  openPositionMonitorRemains: string;
  masterDisabled: string;
  dispatchUnavailable: string;
};

export type OperatorView = {
  /** Machine-readable state, also used as a test/data attribute. */
  entryState: EntryExecutionState;
  statusLabel: string;
  detailLabel: string;
  action: OperatorAction;
  actionLabel: string | null;
  /** Countdown text while a window is running, else null. */
  countdown: string | null;
  budgetLabel: string;
  /** True once an arm session has spent its execution budget. */
  showPositionMonitor: boolean;
  tone: "armed" | "starting" | "idle" | "blocked";
};

/** `900` -> `"15:00"`. Clamps negatives to zero. */
export function formatArmCountdown(seconds: number): string {
  const total = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

export function formatExecutionBudget(
  control: Pick<RuntimeControl, "executions_used" | "max_new_executions">,
  copy: Pick<OperatorCopy, "budgetUsed">,
): string {
  const used = Math.max(0, control.executions_used ?? 0);
  const max = Math.max(1, control.max_new_executions ?? 1);
  return `${used} / ${max} ${copy.budgetUsed}`;
}

/**
 * Derive everything the control panel renders from the persisted state.
 *
 * A spent budget or a manual disarm never implies the agent is off: the open
 * position keeps its autonomous target / stop / horizon protection, so those
 * states surface the safety-monitor line instead.
 */
export function operatorView(
  control: RuntimeControl | null,
  copy: OperatorCopy,
): OperatorView {
  const budgetLabel = formatExecutionBudget(
    control ?? { executions_used: 0, max_new_executions: 1 },
    copy,
  );

  if (!control || !control.master_execution_available) {
    return {
      entryState: "MASTER_DISABLED",
      statusLabel: copy.disarmed,
      detailLabel: copy.masterDisabled,
      action: "NONE",
      actionLabel: null,
      countdown: null,
      budgetLabel,
      showPositionMonitor: false,
      tone: "blocked",
    };
  }

  const spent = (control.executions_used ?? 0) > 0;

  switch (control.entry_execution_state) {
    case "ARMED":
      return {
        entryState: "ARMED",
        statusLabel: copy.armed,
        detailLabel: copy.analysisEnabled,
        action: "DISARM",
        actionLabel: copy.disarmAction,
        countdown: formatArmCountdown(control.seconds_remaining),
        budgetLabel,
        showPositionMonitor: false,
        tone: "armed",
      };

    case "STARTING":
      return {
        entryState: "STARTING",
        statusLabel: copy.starting,
        detailLabel: copy.waitingForCycle,
        action: "NONE",
        actionLabel: null,
        countdown: formatArmCountdown(control.seconds_remaining),
        budgetLabel,
        showPositionMonitor: false,
        tone: "starting",
      };

    case "BUDGET_EXHAUSTED":
      return {
        entryState: "BUDGET_EXHAUSTED",
        statusLabel: copy.newEntriesDisarmed,
        detailLabel: copy.positionMonitorActive,
        action: "NONE",
        actionLabel: null,
        countdown: null,
        budgetLabel,
        showPositionMonitor: true,
        tone: "idle",
      };

    default: {
      // DISARMED or EXPIRED. If a BUY already consumed this session's budget
      // the operator must still see that exit safety is running.
      const dispatchable = control.dispatch_configured;
      return {
        entryState: control.entry_execution_state,
        statusLabel: spent ? copy.newEntriesDisarmed : copy.disarmed,
        detailLabel: spent
          ? copy.positionMonitorActive
          : dispatchable
            ? copy.newEntriesBlocked
            : copy.dispatchUnavailable,
        action: dispatchable ? "ARM" : "NONE",
        actionLabel: dispatchable ? copy.armAction : null,
        countdown: null,
        budgetLabel,
        showPositionMonitor: spent,
        tone: dispatchable ? "idle" : "blocked",
      };
    }
  }
}

/** The password is required for every operator mutation. */
export function canSubmitOperatorAction(password: string): boolean {
  return password.trim().length > 0;
}
