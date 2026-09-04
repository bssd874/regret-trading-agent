"""The runtime arm gates NEW entries only, and spends exactly one budget."""

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select

from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.shadow_trade import ShadowTrade
from backend.app.core.config import settings
from backend.app.services.alpaca_service import alpaca_service
from backend.app.services.decision_router import decision_router
from backend.app.services.execution_sync_service import ExecutionSyncService
from backend.app.services.paper_execution_service import paper_execution_service
from backend.app.services.runtime_control_service import (
    HOLD_REASON_RUNTIME_DISARMED,
)
from backend.tests.runtime_control_helpers import (
    NOW,
    make_service,
    seed_control,
)
from backend.tests.test_autonomous_agent_service import (
    _agent,
    _settings,
    StubAnalyst,
    StubCritic,
    build_pipeline,
)
from backend.tests.test_decision_router import _create_routing_chain


def _count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def _config(**overrides):
    values = {"paper_execution_enabled": True}
    values.update(overrides)
    return _settings(**values)


@pytest.fixture
def paper_broker(monkeypatch):
    """A deterministic fake broker. No real Alpaca call is ever made."""
    # The master capability is ON for these tests, so anything that blocks a
    # BUY is proven to be the runtime arm layer rather than the kill switch.
    monkeypatch.setattr(settings, "paper_execution_enabled", True)
    monkeypatch.setattr(
        alpaca_service,
        "get_account",
        MagicMock(return_value=SimpleNamespace(equity="100000")),
    )
    submit = MagicMock(
        side_effect=[
            SimpleNamespace(
                id=f"paper-runtime-{index}",
                status="accepted",
                filled_qty=None,
                filled_avg_price=None,
            )
            for index in range(1, 6)
        ]
    )
    monkeypatch.setattr(
        paper_execution_service,
        "submit_long_market_order",
        submit,
    )
    provider = MagicMock()
    provider.get_order.return_value = SimpleNamespace(
        status="filled",
        filled_qty="1.5",
        filled_avg_price="101.25",
    )
    return SimpleNamespace(submit=submit, provider=provider)


def _armed_control(db, *, executions_used=0, max_new_executions=1):
    return seed_control(
        db,
        state="ARMED",
        new_entries_armed=True,
        arm_session_id="entry-gate-session",
        armed_at=NOW,
        armed_until=NOW + timedelta(minutes=15),
        max_new_executions=max_new_executions,
        executions_used=executions_used,
    )


def _run(db, config, *, symbols=("ONE",), broker=None):
    return _agent(
        symbols=symbols,
        router=decision_router,
        execution_sync=(
            ExecutionSyncService(broker.provider) if broker else None
        ),
        config=config,
        runtime_control=make_service(config),
    ).run_cycle(db=db)


# ---------------------------------------------------------------
# 21-22 holds
# ---------------------------------------------------------------
def test_disarmed_current_cycle_accept_is_held_not_rejected(
    db_session,
    paper_broker,
):
    config = _config()
    cycle = _run(db_session, config, broker=paper_broker)
    summary = json.loads(cycle.summary_json)

    assert cycle.accepted_count == 1
    assert cycle.execution_held_count == 1
    assert cycle.paper_execution_count == 0
    assert cycle.rejected_count == 0
    assert _count(db_session, ExecutedTrade) == 0
    item = summary["candidates"][0]
    assert item["action"] == "EXECUTION_HELD"
    assert item["reason"] == HOLD_REASON_RUNTIME_DISARMED
    assert item["risk_decision"] == "ACCEPT"
    paper_broker.submit.assert_not_called()


def test_start_requested_accept_is_held(db_session, paper_broker):
    seed_control(
        db_session,
        state="START_REQUESTED",
        arm_session_id="pending-session",
        start_requested_at=NOW,
        request_expires_at=NOW + timedelta(minutes=5),
    )
    config = _config()

    cycle = _run(db_session, config, broker=paper_broker)
    summary = json.loads(cycle.summary_json)

    assert cycle.execution_held_count == 1
    assert cycle.paper_execution_count == 0
    assert summary["candidates"][0]["reason"] == HOLD_REASON_RUNTIME_DISARMED
    paper_broker.submit.assert_not_called()


# ---------------------------------------------------------------
# 23-25 armed entry, budget, auto-disarm
# ---------------------------------------------------------------
def test_armed_current_cycle_accept_submits_one_paper_buy(
    db_session,
    paper_broker,
):
    _armed_control(db_session)
    config = _config()

    cycle = _run(db_session, config, broker=paper_broker)
    summary = json.loads(cycle.summary_json)

    assert cycle.paper_execution_count == 1
    assert cycle.execution_held_count == 0
    assert _count(db_session, ExecutedTrade) == 1
    paper_broker.submit.assert_called_once()
    assert summary["runtime_control_at_start"]["effective_armed"] is True


def test_submitted_buy_consumes_budget_and_auto_disarms(
    db_session,
    paper_broker,
):
    _armed_control(db_session)
    config = _config()
    service = make_service(config)

    _run(db_session, config, broker=paper_broker)

    control = service.get_control(db_session)
    assert control.executions_used == 1
    assert control.state == "DISARMED"
    assert control.new_entries_armed is False
    assert control.last_disarm_reason == "EXECUTION_BUDGET_USED"
    assert service.is_entry_armed(db_session) is False


def test_second_candidate_cannot_submit_a_second_buy(
    db_session,
    paper_broker,
):
    _armed_control(db_session)
    config = _config(autonomous_max_candidates_per_cycle=2)

    cycle = _run(
        db_session,
        config,
        symbols=("ONE", "TWO"),
        broker=paper_broker,
    )
    summary = json.loads(cycle.summary_json)

    assert cycle.accepted_count == 2
    assert cycle.paper_execution_count == 1
    assert cycle.execution_held_count == 1
    assert _count(db_session, ExecutedTrade) == 1
    assert paper_broker.submit.call_count == 1
    actions = [item.get("action") for item in summary["candidates"]]
    assert actions == ["PAPER_EXECUTION", "EXECUTION_HELD"]
    assert summary["candidates"][1]["reason"] == HOLD_REASON_RUNTIME_DISARMED


# ---------------------------------------------------------------
# 27 no historical catch-up
# ---------------------------------------------------------------
def test_historical_accept_is_not_executed_when_the_operator_arms(
    db_session,
    candidate_factory,
    paper_broker,
):
    historical = candidate_factory(symbol="OLD")
    historical_risk, _ = _create_routing_chain(
        db_session,
        historical,
        decision="ACCEPT",
    )
    _armed_control(db_session)
    config = _config()

    cycle = _run(db_session, config, broker=paper_broker)

    executions = list(db_session.scalars(select(ExecutedTrade)))
    assert len(executions) == 1
    # The single execution belongs to this cycle's candidate, never the
    # historical ACCEPT that was held before the operator armed.
    assert executions[0].risk_decision_id != historical_risk.id
    assert executions[0].symbol != "OLD"
    assert cycle.paper_execution_count == 1


# ---------------------------------------------------------------
# 28-29 REJECT while armed
# ---------------------------------------------------------------
def test_reject_while_armed_creates_a_shadow_trade(db_session, paper_broker):
    _armed_control(db_session)
    config = _config()

    cycle = _agent(
        pipeline=build_pipeline(
            analyst=StubAnalyst(confidence=0.40),
            critic=StubCritic(adjustment=-0.15),
        ),
        router=decision_router,
        execution_sync=ExecutionSyncService(paper_broker.provider),
        config=config,
        runtime_control=make_service(config),
    ).run_cycle(db=db_session)

    assert cycle.rejected_count == 1
    assert cycle.shadow_created_count == 1
    assert _count(db_session, ShadowTrade) == 1
    assert _count(db_session, ExecutedTrade) == 0
    paper_broker.submit.assert_not_called()


def test_reject_does_not_consume_execution_budget_or_disarm(
    db_session,
    paper_broker,
):
    _armed_control(db_session)
    config = _config()
    service = make_service(config)

    _agent(
        pipeline=build_pipeline(
            analyst=StubAnalyst(confidence=0.40),
            critic=StubCritic(adjustment=-0.15),
        ),
        router=decision_router,
        execution_sync=ExecutionSyncService(paper_broker.provider),
        config=config,
        runtime_control=service,
    ).run_cycle(db=db_session)

    control = service.get_control(db_session)
    assert control.executions_used == 0
    assert control.state == "ARMED"
    assert service.is_entry_armed(db_session) is True
