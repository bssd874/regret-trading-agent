from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.regret_event import RegretEvent


CLASSIFICATIONS = (
    "MISSED_ALPHA",
    "AVOIDED_LOSS",
    "CORRECT_EXECUTION",
    "BAD_EXECUTION",
)


class RegretMetricsService:
    def calculate(self, *, db: Session) -> dict:
        events = list(db.scalars(select(RegretEvent)).all())
        counts = {name: 0 for name in CLASSIFICATIONS}

        decision_value = 0.0
        missed_alpha = 0.0
        avoided_loss = 0.0
        correct_execution_value = 0.0
        bad_execution_loss = 0.0

        for event in events:
            counts[event.classification] += 1
            decision_value += event.decision_value

            if event.classification == "MISSED_ALPHA" and event.pnl_amount > 0:
                missed_alpha += event.pnl_amount
            elif event.classification == "AVOIDED_LOSS" and event.pnl_amount <= 0:
                avoided_loss += abs(event.pnl_amount)
            elif (
                event.classification == "CORRECT_EXECUTION"
                and event.pnl_amount > 0
            ):
                correct_execution_value += event.pnl_amount
            elif event.classification == "BAD_EXECUTION" and event.pnl_amount < 0:
                bad_execution_loss += abs(event.pnl_amount)

        return {
            "total_decisions_evaluated": len(events),
            "decision_value": decision_value,
            "missed_alpha": missed_alpha,
            "avoided_loss": avoided_loss,
            "correct_execution_value": correct_execution_value,
            "bad_execution_loss": bad_execution_loss,
            "classification_counts": counts,
        }


regret_metrics_service = RegretMetricsService()
