import assert from "node:assert/strict";
import test from "node:test";

import {
  buildTwoPointGraph,
  graphDirection,
} from "../src/lib/counterfactual-graph";
import {
  signedDecisionValue,
  unsignedMagnitude,
} from "../src/lib/regret-display";

test("aggregate Missed Alpha is displayed as an unsigned magnitude", () => {
  assert.equal(unsignedMagnitude(-22.77), 22.77);
  assert.equal(unsignedMagnitude(22.77), 22.77);
});

test("Avoided Loss replay preserves positive Decision Value", () => {
  assert.equal(signedDecisionValue(835.75), 835.75);
  assert.ok(signedDecisionValue(835.75) > 0);
});

test("Missed Alpha replay preserves negative Decision Value", () => {
  assert.equal(signedDecisionValue(-22.77), -22.77);
  assert.ok(signedDecisionValue(-22.77) < 0);
});

test("two-point graph slopes downward when evaluation is below entry", () => {
  const graph = buildTwoPointGraph(0.95, 0.55);
  assert.equal(graphDirection(0.95, 0.55), "down");
  assert.ok(graph.points[1].y > graph.points[0].y);
});

test("two-point graph slopes upward when evaluation is above entry", () => {
  const graph = buildTwoPointGraph(9.66, 9.77);
  assert.equal(graphDirection(9.66, 9.77), "up");
  assert.ok(graph.points[1].y < graph.points[0].y);
});

test("graph model contains only the two factual price points", () => {
  const graph = buildTwoPointGraph(10, 12);
  assert.equal(graph.points.length, 2);
  assert.deepEqual(graph.points.map((point) => point.kind), ["entry", "evaluation"]);
  assert.deepEqual(graph.points.map((point) => point.price), [10, 12]);
});
