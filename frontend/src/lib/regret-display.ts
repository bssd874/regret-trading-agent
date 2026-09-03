export function unsignedMagnitude(value: number): number {
  return Math.abs(Number.isFinite(value) ? value : 0);
}

export function signedDecisionValue(value: number): number {
  return Number.isFinite(value) ? value : 0;
}
