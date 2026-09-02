import type { Classification } from "./api";

export const CLASSIFICATION_META: Record<
  Classification,
  { label: string; description: string; tone: string }
> = {
  MISSED_ALPHA: {
    label: "Missed alpha",
    description: "The rejected trade would have captured upside.",
    tone: "amber",
  },
  AVOIDED_LOSS: {
    label: "Avoided loss",
    description: "The rejection protected capital from a losing trade.",
    tone: "blue",
  },
  CORRECT_EXECUTION: {
    label: "Correct execution",
    description: "The accepted paper trade added or preserved value.",
    tone: "green",
  },
  BAD_EXECUTION: {
    label: "Bad execution",
    description: "The accepted paper trade reduced value.",
    tone: "red",
  },
};

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatCurrency(value: number): string {
  return currency.format(Number.isFinite(value) ? value : 0);
}

export function formatSignedCurrency(value: number): string {
  const safe = Number.isFinite(value) ? value : 0;
  return `${safe > 0 ? "+" : ""}${currency.format(safe)}`;
}

export function formatPercent(value: number, digits = 1): string {
  const safe = Number.isFinite(value) ? value : 0;
  return `${(safe * 100).toFixed(digits)}%`;
}

export function formatSignedPercent(value: number, digits = 1): string {
  const safe = Number.isFinite(value) ? value : 0;
  return `${safe > 0 ? "+" : ""}${(safe * 100).toFixed(digits)}%`;
}

export function criticModeLabel(provider: string): string {
  return provider === "azure-fallback" ? "Fallback Critic" : "Primary Critic";
}

export function decisionValueMessage(value: number): string {
  if (value > 0) return "Value added or protected";
  if (value < 0) return "Value destroyed or missed";
  return "No measured value change";
}

export function toUserMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "The backend could not be reached. Check the API and try again.";
}
