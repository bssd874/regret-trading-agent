from datetime import datetime, timezone

import pytest

from backend.app.models.outcome_snapshot import OutcomeSnapshot
from backend.app.models.regret_event import RegretEvent
from backend.app.services.regret_metrics_service import RegretMetricsService
from backend.tests.test_decision_router import _create_routing_chain


def test_regret_metrics_aggregation(db_session, candidate_factory):
    candidate = candidate_factory()
    risk, _ = _create_routing_chain(db_session, candidate, decision="REJECT")
    now = datetime.now(timezone.utc)
    values = [
        ("MISSED_ALPHA", 100.0, -100.0),
        ("AVOIDED_LOSS", -40.0, 40.0),
        ("CORRECT_EXECUTION", 75.0, 75.0),
        ("BAD_EXECUTION", -25.0, -25.0),
    ]

    for source_id, (classification, pnl, decision_value) in enumerate(
        values,
        start=1,
    ):
        decision = "REJECT" if classification in {
            "MISSED_ALPHA",
            "AVOIDED_LOSS",
        } else "ACCEPT"
        outcome = OutcomeSnapshot(
            source_type="SHADOW" if decision == "REJECT" else "EXECUTED",
            source_id=source_id,
            candidate_id=candidate.id,
            risk_decision_id=risk.id,
            symbol=candidate.symbol,
            decision=decision,
            entry_price=100.0,
            evaluation_price=100.0 + pnl / 10.0,
            quantity=10.0,
            notional=1000.0,
            pnl_pct=pnl / 1000.0,
            pnl_amount=pnl,
            due_at=now,
            evaluated_at=now,
            price_source="test_snapshot",
        )
        db_session.add(outcome)
        db_session.flush()
        db_session.add(
            RegretEvent(
                outcome_id=outcome.id,
                candidate_id=candidate.id,
                risk_decision_id=risk.id,
                symbol=candidate.symbol,
                decision=decision,
                classification=classification,
                pnl_pct=pnl / 1000.0,
                pnl_amount=pnl,
                decision_value=decision_value,
            )
        )
    db_session.commit()

    metrics = RegretMetricsService().calculate(db=db_session)

    assert metrics["total_decisions_evaluated"] == 4
    assert metrics["decision_value"] == pytest.approx(-10.0)
    assert metrics["missed_alpha"] == 100.0
    assert metrics["avoided_loss"] == 40.0
    assert metrics["correct_execution_value"] == 75.0
    assert metrics["bad_execution_loss"] == 25.0
    assert metrics["classification_counts"] == {
        "MISSED_ALPHA": 1,
        "AVOIDED_LOSS": 1,
        "CORRECT_EXECUTION": 1,
        "BAD_EXECUTION": 1,
    }
