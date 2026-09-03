export function unsignedMagnitude(value: number): number {
  return Math.abs(Number.isFinite(value) ? value : 0);
}

export function signedDecisionValue(value: number): number {
  return Number.isFinite(value) ? value : 0;
}

type PersistedReplayRecord = {
  risk_decision_id: number;
};

export function persistedReplayDecisionIds(
  outcomes: PersistedReplayRecord[],
  events: PersistedReplayRecord[],
): Set<number> {
  const decisionsWithOutcomes = new Set(outcomes.map((outcome) => outcome.risk_decision_id));
  return new Set(
    events
      .filter((event) => decisionsWithOutcomes.has(event.risk_decision_id))
      .map((event) => event.risk_decision_id),
  );
}
