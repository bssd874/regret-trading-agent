import { buildTwoPointGraph } from "@/lib/counterfactual-graph";
import { formatCurrency } from "@/lib/presentation";

export function CounterfactualGraph({
  entryPrice,
  evaluationPrice,
  entryLabel,
  evaluationLabel,
  replayKey,
}: {
  entryPrice: number;
  evaluationPrice: number;
  entryLabel: string;
  evaluationLabel: string;
  replayKey: number;
}) {
  const model = buildTwoPointGraph(entryPrice, evaluationPrice);

  return (
    <svg
      aria-label={`${entryLabel} ${formatCurrency(entryPrice)}, ${evaluationLabel} ${formatCurrency(evaluationPrice)}`}
      className="h-44 w-full"
      data-direction={model.direction}
      data-factual-points={model.points.length}
      key={replayKey}
      role="img"
      viewBox="0 0 420 160"
    >
      <path
        className="replay-line"
        d={model.path}
        fill="none"
        stroke="#52646b"
        strokeDasharray="3 7"
        strokeLinecap="round"
        strokeWidth="2"
      />
      {model.points.map((point, index) => (
        <g className={index === 1 ? "replay-dot" : undefined} key={point.kind}>
          <circle
            data-factual-point={point.kind}
            cx={point.x}
            cy={point.y}
            fill="#0d1011"
            r="5"
            stroke="#090b0c"
            strokeWidth="3"
          />
          <text
            fill="#a7afb1"
            fontFamily="Georgia, serif"
            fontSize="13"
            textAnchor={index === 0 ? "start" : "end"}
            x={index === 0 ? point.x + 8 : point.x - 8}
            y={point.y - 8}
          >
            {formatCurrency(point.price)} ({index === 0 ? entryLabel : evaluationLabel})
          </text>
        </g>
      ))}
    </svg>
  );
}
