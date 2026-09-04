import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { translations } from "../src/i18n/translations";
import {
  canSubmitOperatorAction,
  formatArmCountdown,
  formatExecutionBudget,
  operatorView,
  type RuntimeControl,
} from "../src/lib/operator";

const EN = translations.en.operator;
const ID = translations.id.operator;

function control(overrides: Partial<RuntimeControl> = {}): RuntimeControl {
  return {
    state: "DISARMED",
    new_entries_armed: false,
    effective_new_entries_armed: false,
    entry_execution_state: "DISARMED",
    master_execution_available: true,
    armed_at: null,
    armed_until: null,
    request_expires_at: null,
    start_requested_at: null,
    executions_used: 0,
    max_new_executions: 1,
    last_disarm_reason: null,
    last_cycle_id: null,
    arm_ttl_minutes: 15,
    seconds_remaining: 0,
    dispatch_configured: true,
    ...overrides,
  };
}

// ---------------------------------------------------------------
// 44-48 state rendering
// ---------------------------------------------------------------
test("renders the disarmed state with an arm action", () => {
  const view = operatorView(control(), EN);
  assert.equal(view.entryState, "DISARMED");
  assert.equal(view.statusLabel, EN.disarmed);
  assert.equal(view.detailLabel, EN.newEntriesBlocked);
  assert.equal(view.action, "ARM");
  assert.equal(view.actionLabel, EN.armAction);
  assert.equal(view.showPositionMonitor, false);
});

test("renders the starting state without claiming the agent is armed", () => {
  const view = operatorView(
    control({
      state: "START_REQUESTED",
      entry_execution_state: "STARTING",
      seconds_remaining: 240,
    }),
    EN,
  );
  assert.equal(view.statusLabel, EN.starting);
  assert.equal(view.detailLabel, EN.waitingForCycle);
  assert.notEqual(view.statusLabel, EN.armed);
  assert.equal(view.action, "NONE");
  assert.equal(view.countdown, "04:00");
});

test("renders the armed state with countdown, budget and a disarm action", () => {
  const view = operatorView(
    control({
      state: "ARMED",
      new_entries_armed: true,
      effective_new_entries_armed: true,
      entry_execution_state: "ARMED",
      seconds_remaining: 872,
    }),
    EN,
  );
  assert.equal(view.statusLabel, EN.armed);
  assert.equal(view.detailLabel, EN.analysisEnabled);
  assert.equal(view.countdown, "14:32");
  assert.equal(view.budgetLabel, `0 / 1 ${EN.budgetUsed}`);
  assert.equal(view.action, "DISARM");
  assert.equal(view.actionLabel, EN.disarmAction);
});

test("formats the arm countdown and clamps invalid input", () => {
  assert.equal(formatArmCountdown(900), "15:00");
  assert.equal(formatArmCountdown(59), "00:59");
  assert.equal(formatArmCountdown(-10), "00:00");
  assert.equal(formatArmCountdown(Number.NaN), "00:00");
});

test("formats the execution budget", () => {
  assert.equal(
    formatExecutionBudget({ executions_used: 1, max_new_executions: 1 }, EN),
    `1 / 1 ${EN.budgetUsed}`,
  );
});

// ---------------------------------------------------------------
// 53 post-BUY safety monitoring
// ---------------------------------------------------------------
test("after a BUY the panel shows monitoring, not a stopped agent", () => {
  const view = operatorView(
    control({
      executions_used: 1,
      last_disarm_reason: "EXECUTION_BUDGET_USED",
    }),
    EN,
  );
  assert.equal(view.statusLabel, EN.newEntriesDisarmed);
  assert.equal(view.detailLabel, EN.positionMonitorActive);
  assert.equal(view.showPositionMonitor, true);
  assert.equal(view.budgetLabel, `1 / 1 ${EN.budgetUsed}`);
});

test("an exhausted budget still reports position monitoring", () => {
  const view = operatorView(
    control({
      state: "ARMED",
      entry_execution_state: "BUDGET_EXHAUSTED",
      executions_used: 1,
    }),
    EN,
  );
  assert.equal(view.entryState, "BUDGET_EXHAUSTED");
  assert.equal(view.detailLabel, EN.positionMonitorActive);
  assert.equal(view.action, "NONE");
});

test("an expired arm falls back to the disarmed presentation", () => {
  const view = operatorView(
    control({
      state: "ARMED",
      new_entries_armed: true,
      entry_execution_state: "EXPIRED",
    }),
    EN,
  );
  assert.equal(view.action, "ARM");
  assert.equal(view.statusLabel, EN.disarmed);
});

test("the master switch blocks arming entirely", () => {
  const view = operatorView(
    control({
      master_execution_available: false,
      entry_execution_state: "MASTER_DISABLED",
    }),
    EN,
  );
  assert.equal(view.action, "NONE");
  assert.equal(view.actionLabel, null);
  assert.equal(view.detailLabel, EN.masterDisabled);
});

test("an unconfigured dispatch offers no arm action", () => {
  const view = operatorView(control({ dispatch_configured: false }), EN);
  assert.equal(view.action, "NONE");
  assert.equal(view.detailLabel, EN.dispatchUnavailable);
});

test("a null control fails closed", () => {
  const view = operatorView(null, EN);
  assert.equal(view.action, "NONE");
  assert.equal(view.entryState, "MASTER_DISABLED");
});

// ---------------------------------------------------------------
// 38-39 / 50 password gating
// ---------------------------------------------------------------
test("an operator action requires a non-empty password", () => {
  assert.equal(canSubmitOperatorAction(""), false);
  assert.equal(canSubmitOperatorAction("   "), false);
  assert.equal(canSubmitOperatorAction("secret"), true);
});

// ---------------------------------------------------------------
// 57 bilingual coverage
// ---------------------------------------------------------------
test("every operator string is translated in EN and ID", () => {
  const keys = Object.keys(EN) as Array<keyof typeof EN>;
  assert.ok(keys.length > 0);
  for (const key of keys) {
    assert.equal(typeof ID[key], "string", `missing ID copy for ${key}`);
    assert.ok(ID[key].length > 0, `empty ID copy for ${key}`);
    assert.notEqual(ID[key], EN[key], `untranslated ID copy for ${key}`);
  }
});

test("Indonesian operator copy uses the approved wording", () => {
  assert.equal(ID.disarmed, "Entry baru dinonaktifkan");
  assert.equal(ID.armAction, "Aktifkan & jalankan agent paper");
  assert.equal(ID.starting, "Agent sedang dimulai...");
  assert.equal(ID.armed, "Agent aktif · Paper otonom");
  assert.equal(ID.disarmAction, "Nonaktifkan entry baru");
  assert.equal(ID.positionMonitorActive, "Pemantauan keamanan posisi aktif");
  assert.equal(
    ID.openPositionMonitorRemains,
    "Pemantauan posisi terbuka tetap aktif",
  );
});

test("the Indonesian view renders Indonesian labels", () => {
  const view = operatorView(control(), ID);
  assert.equal(view.statusLabel, ID.disarmed);
  assert.equal(view.actionLabel, ID.armAction);
});

// ---------------------------------------------------------------
// 41-42 / 54-56 secret containment and read-only UI
// ---------------------------------------------------------------
const SRC = join(import.meta.dirname, "..", "src");
const SERVER_ONLY = [
  join("src", "lib", "operator-server.ts"),
  join("src", "app", "api"),
];

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

const allSources = walk(SRC).filter((file) => /\.(ts|tsx)$/.test(file));
const clientSources = allSources.filter(
  (file) => !SERVER_ONLY.some((fragment) => file.includes(fragment)),
);

test("no browser-reachable source references a server secret", () => {
  const forbidden = [
    "ADMIN_CONTROL_SECRET",
    "ADMIN_PANEL_PASSWORD",
    "REGRET_API_ADMIN_SECRET",
    "REGRET_GITHUB_DISPATCH_TOKEN",
    "X-Regret-Admin-Secret",
  ];
  assert.ok(clientSources.length > 0);
  for (const file of clientSources) {
    const contents = readFileSync(file, "utf8");
    for (const name of forbidden) {
      assert.ok(
        !contents.includes(name),
        `${file} must not reference ${name}`,
      );
    }
  }
});

test("no secret is ever exposed through a NEXT_PUBLIC_ variable", () => {
  for (const file of allSources) {
    const contents = readFileSync(file, "utf8");
    for (const match of contents.matchAll(/NEXT_PUBLIC_[A-Z0-9_]+/g)) {
      assert.equal(
        match[0],
        "NEXT_PUBLIC_API_BASE_URL",
        `${file} exposes ${match[0]} to the browser`,
      );
    }
  }
});

test("the server-only operator proxy is never imported by client code", () => {
  for (const file of clientSources) {
    const contents = readFileSync(file, "utf8");
    assert.ok(
      !contents.includes("operator-server"),
      `${file} must not import the server-only operator proxy`,
    );
  }
});

test("the operator control exposes no BUY, SELL or CLOSE action", () => {
  const contents = readFileSync(
    join(SRC, "components", "operator-control.tsx"),
    "utf8",
  );
  for (const forbidden of [">BUY<", ">SELL<", ">CLOSE<", "submit_order"]) {
    assert.ok(!contents.includes(forbidden));
  }
  // The only two mutations the operator can reach.
  assert.ok(contents.includes("/api/operator/arm"));
  assert.ok(contents.includes("/api/operator/disarm"));
});
