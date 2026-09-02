import assert from "node:assert/strict";
import test from "node:test";

import {
  CLASSIFICATION_META,
  criticModeLabel,
  decisionValueMessage,
  formatCurrency,
  formatSignedCurrency,
  formatSignedPercent,
  toUserMessage,
} from "../src/lib/presentation";

test("formats the dashboard's monetary and percentage values", () => {
  assert.equal(formatCurrency(835.748), "$835.75");
  assert.equal(formatSignedCurrency(12.5), "+$12.50");
  assert.equal(formatSignedCurrency(-12.5), "-$12.50");
  assert.equal(formatSignedPercent(0.0375), "+3.8%");
});

test("presents critic fallback honestly", () => {
  assert.equal(criticModeLabel("azure-fallback"), "Fallback Critic");
  assert.equal(criticModeLabel("nvidia"), "Primary Critic");
});

test("defines all four counterfactual classes", () => {
  assert.deepEqual(Object.keys(CLASSIFICATION_META).sort(), [
    "AVOIDED_LOSS",
    "BAD_EXECUTION",
    "CORRECT_EXECUTION",
    "MISSED_ALPHA",
  ]);
});

test("describes positive, negative, and neutral decision value", () => {
  assert.equal(decisionValueMessage(1), "Value added or protected");
  assert.equal(decisionValueMessage(-1), "Value destroyed or missed");
  assert.equal(decisionValueMessage(0), "No measured value change");
});

test("turns API errors into a stable user-facing message", () => {
  assert.equal(toUserMessage(new Error("Backend request failed for /health")), "Backend request failed for /health");
  assert.equal(toUserMessage(null), "The backend could not be reached. Check the API and try again.");
});
