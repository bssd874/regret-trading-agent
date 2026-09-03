import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { agentStatusLabel, translations } from "../src/i18n/translations";

test("AGENT OFFLINE renders for disabled autonomy", () => {
  assert.equal(
    agentStatusLabel({ enabled: false, paper_execution_enabled: false }, "en"),
    "AGENT OFFLINE",
  );
});

test("AGENT ACTIVE · OBSERVE renders with execution disabled", () => {
  assert.equal(
    agentStatusLabel({ enabled: true, paper_execution_enabled: false }, "en"),
    "AGENT ACTIVE · OBSERVE",
  );
});

test("AGENT ACTIVE · PAPER AUTONOMOUS renders with execution enabled", () => {
  assert.equal(
    agentStatusLabel({ enabled: true, paper_execution_enabled: true }, "en"),
    "AGENT ACTIVE · PAPER AUTONOMOUS",
  );
});

test("agent status strings switch to Indonesian", () => {
  assert.equal(
    agentStatusLabel({ enabled: false, paper_execution_enabled: false }, "id"),
    "AGENT NONAKTIF",
  );
  assert.equal(
    agentStatusLabel({ enabled: true, paper_execution_enabled: false }, "id"),
    "AGENT AKTIF · OBSERVASI",
  );
  assert.equal(
    agentStatusLabel({ enabled: true, paper_execution_enabled: true }, "id"),
    "AGENT AKTIF · PAPER OTONOM",
  );
  assert.equal(translations.id.header.lastCycle, "Siklus terakhir");
});

test("dashboard consumes exits and renders realized fields as read-only data", () => {
  const dashboardSource = readFileSync(
    new URL("../src/components/dashboard.tsx", import.meta.url),
    "utf8",
  );
  const apiSource = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");

  assert.match(apiSource, /getExits:[\s\S]*\/api\/exits/);
  assert.match(dashboardSource, /copy\.replay\.buy/);
  assert.match(dashboardSource, /copy\.replay\.sell/);
  assert.match(dashboardSource, /copy\.replay\.realizedPnl/);
  assert.match(dashboardSource, /tradeExit\.reason/);
});

test("dashboard introduces no manual trading controls", () => {
  const source = readFileSync(
    new URL("../src/components/dashboard.tsx", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(source, />\s*(BUY|SELL|EXECUTE|CLOSE)\s*</i);
  assert.doesNotMatch(source, /\/api\/agent\/run-once/);
});
