export function unsignedMagnitude(value: number): number {
  return Math.abs(Number.isFinite(value) ? value : 0);
}

export function signedDecisionValue(value: number): number {
  return Number.isFinite(value) ? value : 0;
}

type PersistedReplayRecord = {
  risk_decision_id: number;
};

type ReplayEvent = PersistedReplayRecord & {
  decision_value: number;
};

type ReplayDecision = {
  id: number;
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

export function isMaterialDecisionValue(value: number): boolean {
  return Number.isFinite(value) && Math.abs(value) > Number.EPSILON;
}

export function featuredReplayDecisionId(
  outcomes: PersistedReplayRecord[],
  events: ReplayEvent[],
): number | null {
  const replayReadyIds = persistedReplayDecisionIds(outcomes, events);
  return events.find(
    (event) => replayReadyIds.has(event.risk_decision_id)
      && isMaterialDecisionValue(event.decision_value),
  )?.risk_decision_id ?? null;
}

export function orderReplayDecisions<T extends ReplayDecision>(
  decisions: T[],
  events: ReplayEvent[],
  selectedId: number | null,
): T[] {
  const materialValueById = new Map(
    events
      .filter((event) => isMaterialDecisionValue(event.decision_value))
      .map((event) => [event.risk_decision_id, Math.abs(event.decision_value)]),
  );

  return [...decisions].sort((left, right) => {
    const selectedDifference = Number(right.id === selectedId) - Number(left.id === selectedId);
    if (selectedDifference !== 0) return selectedDifference;
    const valueDifference = (materialValueById.get(right.id) ?? -1)
      - (materialValueById.get(left.id) ?? -1);
    return valueDifference !== 0 ? valueDifference : right.id - left.id;
  });
}
