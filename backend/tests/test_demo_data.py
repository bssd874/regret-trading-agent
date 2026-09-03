import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.database import Base
from backend.app.db.demo_data import (
    DEMO_MODELS,
    DemoDataError,
    export_demo_payload,
    import_demo_payload,
    validate_demo_payload,
)
from backend.app.models.agent_cycle import AgentCycle
from backend.app.models.candidate_trade import CandidateTrade
from backend.app.models.critic_analysis import CriticAnalysis
from backend.app.models.decision_analysis import DecisionAnalysis
from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.outcome_snapshot import OutcomeSnapshot
from backend.app.models.regret_event import RegretEvent
from backend.app.models.risk_decision import RiskDecision
from backend.app.models.shadow_trade import ShadowTrade
from backend.app.models.trade_exit import TradeExit


def _seed_demo_records(db):
    now = datetime(2026, 9, 3, 16, 0, tzinfo=timezone.utc)
    db.add(
        AgentCycle(
            id=20,
            trigger="SCHEDULED",
            status="COMPLETED",
            mode="AUTONOMOUS_PAPER",
            started_at=now,
            heartbeat_at=now,
            finished_at=now,
            accepted_count=1,
            paper_execution_count=1,
            summary_json='{"phase":"FINISHED"}',
            errors_json="[]",
        )
    )
    db.add_all(
        [
            CandidateTrade(
                id=49,
                symbol="TSLA",
                entry_price=383.0,
                price_change_pct=2.0,
                volume_ratio=1.5,
                scout_score=4.0,
                source="movers",
                status="DECIDED",
            ),
            CandidateTrade(
                id=19,
                symbol="DUO",
                entry_price=0.9455,
                price_change_pct=5.0,
                volume_ratio=2.0,
                scout_score=7.0,
                source="movers",
                status="DECIDED",
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            DecisionAnalysis(
                id=24,
                candidate_id=49,
                symbol="TSLA",
                direction="LONG",
                thesis="Structured test thesis",
                analyst_confidence=0.76,
                entry_price=383.0,
                stop_loss=375.5,
                target_price=410.0,
                horizon_minutes=60,
                invalidation="Break below persisted stop",
                evidence_summary='["test evidence"]',
                provider="azure",
                model_name="test-model",
            ),
            DecisionAnalysis(
                id=1,
                candidate_id=19,
                symbol="DUO",
                direction="LONG",
                thesis="Structured rejected thesis",
                analyst_confidence=0.70,
                entry_price=0.9455,
                stop_loss=0.85,
                target_price=1.25,
                horizon_minutes=60,
                invalidation="Break below persisted stop",
                evidence_summary='["test evidence"]',
                provider="azure",
                model_name="test-model",
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            CriticAnalysis(
                id=24,
                candidate_id=49,
                analysis_id=24,
                verdict="PASS",
                confidence_adjustment=0.0,
                thesis_consistency=0.9,
                concerns="[]",
                provider="nvidia",
                model_name="test-critic",
            ),
            CriticAnalysis(
                id=1,
                candidate_id=19,
                analysis_id=1,
                verdict="CHALLENGE",
                confidence_adjustment=-0.15,
                thesis_consistency=0.5,
                concerns='["test concern"]',
                provider="nvidia",
                model_name="test-critic",
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            RiskDecision(
                id=24,
                candidate_id=49,
                analysis_id=24,
                critic_id=24,
                original_confidence=0.76,
                critic_adjustment=0.0,
                adjusted_confidence=0.76,
                reward_risk_ratio=3.5,
                proposed_position_pct=0.02,
                risk_score=10.0,
                decision="ACCEPT",
                reasons="[]",
            ),
            RiskDecision(
                id=1,
                candidate_id=19,
                analysis_id=1,
                critic_id=1,
                original_confidence=0.70,
                critic_adjustment=-0.15,
                adjusted_confidence=0.55,
                reward_risk_ratio=4.3,
                proposed_position_pct=0.02,
                risk_score=30.0,
                decision="REJECT",
                reasons='["confidence below minimum threshold"]',
            ),
        ]
    )
    db.flush()
    db.add(
        ExecutedTrade(
            id=1,
            candidate_id=49,
            risk_decision_id=24,
            alpaca_order_id="paper-buy-test",
            symbol="TSLA",
            side="BUY",
            requested_notional=100.0,
            status="filled",
            filled_qty=0.26104187,
            filled_avg_price=383.042,
            submitted_at=now,
        )
    )
    db.add(
        ShadowTrade(
            id=1,
            candidate_id=19,
            risk_decision_id=1,
            symbol="DUO",
            side="BUY",
            hypothetical_entry=0.9455,
            hypothetical_notional=2000.0,
            stop_loss=0.85,
            target_price=1.25,
            horizon_minutes=60,
            status="EVALUATED",
            opened_at=now,
            evaluation_due_at=now + timedelta(minutes=60),
        )
    )
    db.flush()
    db.add(
        TradeExit(
            id=1,
            executed_trade_id=1,
            candidate_id=49,
            risk_decision_id=24,
            symbol="TSLA",
            reason="TIME_EXIT",
            trigger_price=382.445,
            target_price=410.0,
            stop_loss=375.5,
            horizon_minutes=60,
            requested_qty=0.26104187,
            alpaca_order_id="paper-sell-test",
            status="filled",
            filled_qty=0.26104187,
            filled_avg_price=382.432,
            triggered_at=now + timedelta(minutes=90),
            submitted_at=now + timedelta(minutes=90),
            closed_at=now + timedelta(minutes=91),
        )
    )
    db.flush()
    db.add_all(
        [
            OutcomeSnapshot(
                id=20,
                source_type="EXECUTED",
                source_id=1,
                candidate_id=49,
                risk_decision_id=24,
                symbol="TSLA",
                decision="ACCEPT",
                entry_price=383.042,
                evaluation_price=382.432,
                quantity=0.26104187,
                notional=99.99,
                pnl_pct=-0.0015925,
                pnl_amount=-0.15924,
                due_at=now + timedelta(minutes=91),
                evaluated_at=now + timedelta(minutes=91),
                price_source="alpaca_exit_fill",
            ),
            OutcomeSnapshot(
                id=1,
                source_type="SHADOW",
                source_id=1,
                candidate_id=19,
                risk_decision_id=1,
                symbol="DUO",
                decision="REJECT",
                entry_price=0.9455,
                evaluation_price=0.5504,
                quantity=2115.28,
                notional=2000.0,
                pnl_pct=-0.4178,
                pnl_amount=-835.75,
                due_at=now + timedelta(minutes=60),
                evaluated_at=now + timedelta(minutes=61),
                price_source="latest_trade",
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            RegretEvent(
                id=20,
                outcome_id=20,
                candidate_id=49,
                risk_decision_id=24,
                symbol="TSLA",
                decision="ACCEPT",
                classification="BAD_EXECUTION",
                pnl_pct=-0.0015925,
                pnl_amount=-0.15924,
                decision_value=-0.15924,
            ),
            RegretEvent(
                id=1,
                outcome_id=1,
                candidate_id=19,
                risk_decision_id=1,
                symbol="DUO",
                decision="REJECT",
                classification="AVOIDED_LOSS",
                pnl_pct=-0.4178,
                pnl_amount=-835.75,
                decision_value=835.75,
            ),
        ]
    )
    db.commit()


def test_demo_export_import_preserves_records_and_is_idempotent(db_session):
    _seed_demo_records(db_session)
    payload = export_demo_payload(db_session)
    assert set(payload["tables"]) == {
        model.__tablename__ for model in DEMO_MODELS
    }
    assert payload["tables"]["trade_exits"][0]["reason"] == "TIME_EXIT"
    assert payload["tables"]["regret_events"][1]["decision_value"] == -0.15924
    assert "secret" not in json.dumps(payload).lower()

    target_engine = create_engine("sqlite://")
    Base.metadata.create_all(target_engine)
    target_db = sessionmaker(bind=target_engine)()
    try:
        first = import_demo_payload(target_db, payload)
        second = import_demo_payload(target_db, payload)
        expected_count = sum(len(rows) for rows in payload["tables"].values())
        assert first == {
            "inserted": expected_count,
            "skipped": 0,
            "tables": first["tables"],
        }
        assert second["inserted"] == 0
        assert second["skipped"] == expected_count
        restored = target_db.scalar(
            select(RegretEvent).where(RegretEvent.id == 20)
        )
        assert restored is not None
        assert restored.classification == "BAD_EXECUTION"
        assert restored.decision_value == -0.15924
        assert target_db.get(TradeExit, 1).filled_avg_price == 382.432
    finally:
        target_db.close()
        target_engine.dispose()


def test_demo_import_rejects_incompatible_or_conflicting_data(db_session):
    _seed_demo_records(db_session)
    payload = export_demo_payload(db_session)
    incompatible = dict(payload)
    incompatible["tables"] = dict(payload["tables"])
    incompatible["tables"].pop("agent_cycles")
    with pytest.raises(DemoDataError, match="table set"):
        validate_demo_payload(incompatible)

    conflict = export_demo_payload(db_session)
    conflict["tables"]["candidate_trades"][0]["symbol"] = "DIFFERENT"
    with pytest.raises(DemoDataError, match="Conflicting existing row"):
        import_demo_payload(db_session, conflict)
