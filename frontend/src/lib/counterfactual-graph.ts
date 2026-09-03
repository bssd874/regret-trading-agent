export type GraphDirection = "up" | "down" | "flat";

export type FactualPricePoint = {
  kind: "entry" | "evaluation" | "buy" | "sell";
  price: number;
  x: number;
  y: number;
};

export type TwoPointGraphModel = {
  direction: GraphDirection;
  path: string;
  points: [FactualPricePoint, FactualPricePoint];
};

export function graphDirection(
  entryPrice: number,
  evaluationPrice: number,
): GraphDirection {
  const tolerance = Math.max(Math.abs(entryPrice) * 0.001, 0.0001);
  const delta = evaluationPrice - entryPrice;
  if (Math.abs(delta) <= tolerance) return "flat";
  return delta > 0 ? "up" : "down";
}

function buildGraph(
  entryPrice: number,
  evaluationPrice: number,
  kinds: [FactualPricePoint["kind"], FactualPricePoint["kind"]],
): TwoPointGraphModel {
  const direction = graphDirection(entryPrice, evaluationPrice);
  const entryY = 78;
  const evaluationY = direction === "up" ? 38 : direction === "down" ? 118 : 78;
  const points: [FactualPricePoint, FactualPricePoint] = [
    { kind: kinds[0], price: entryPrice, x: 38, y: entryY },
    { kind: kinds[1], price: evaluationPrice, x: 382, y: evaluationY },
  ];
  const controlOneY = entryY + (evaluationY - entryY) * 0.18;
  const controlTwoY = entryY + (evaluationY - entryY) * 0.82;

  return {
    direction,
    path: `M ${points[0].x} ${points[0].y} C 150 ${controlOneY}, 270 ${controlTwoY}, ${points[1].x} ${points[1].y}`,
    points,
  };
}

export function buildTwoPointGraph(
  entryPrice: number,
  evaluationPrice: number,
): TwoPointGraphModel {
  return buildGraph(entryPrice, evaluationPrice, ["entry", "evaluation"]);
}

export function buildTradeFillGraph(
  buyFillPrice: number,
  sellFillPrice: number,
): TwoPointGraphModel {
  return buildGraph(buyFillPrice, sellFillPrice, ["buy", "sell"]);
}
