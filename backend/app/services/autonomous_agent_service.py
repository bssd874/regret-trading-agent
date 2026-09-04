import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, settings
from backend.app.models.agent_cycle import AgentCycle
from backend.app.models.candidate_trade import CandidateTrade
from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.outcome_snapshot import OutcomeSnapshot
from backend.app.models.regret_event import RegretEvent
from backend.app.models.risk_decision import RiskDecision
from backend.app.models.trade_exit import TradeExit
from backend.app.services.decision_pipeline import decision_pipeline
from backend.app.services.decision_router import decision_router
from backend.app.services.execution_sync_service import execution_sync_service
from backend.app.services.market_scout import market_scout
from backend.app.services.outcome_pipeline import outcome_pipeline
from backend.app.services.position_exit_service import position_exit_service
from backend.app.services.runtime_control_service import (
    HOLD_REASON_RUNTIME_DISARMED,
    RuntimeControlService,
    runtime_control_service,
)
from backend.app.services.trade_exit_sync_service import trade_exit_sync_service


AGENT_CYCLE_ALREADY_RUNNING = "AGENT_CYCLE_ALREADY_RUNNING"
TERMINAL_EXECUTION_STATUSES = frozenset(
    {"filled", "canceled", "expired", "rejected"}
)
TERMINAL_EXIT_STATUSES = frozenset(
    {"filled", "canceled", "expired", "rejected"}
)
COUNT_FIELDS = (
    "scouted_count",
    "analyzed_count",
    "accepted_count",
    "rejected_count",
    "failed_count",
    "shadow_created_count",
    "paper_execution_count",
    "execution_held_count",
    "outcomes_evaluated_count",
    "regret_events_created_count",
)


class ScoutService(Protocol):
    def run(self, db: Session, limit: int = 5):
        ...


class PipelineService(Protocol):
    def run(self, *, db: Session, candidate_id: int) -> dict:
        ...


class RouterService(Protocol):
    def route(self, *, db: Session, decision_id: int) -> dict:
        ...


class OutcomesService(Protocol):
    def evaluate_due(self, *, db: Session) -> dict:
        ...


class ExecutionSynchronizer(Protocol):
    def sync(self, *, db: Session, execution_id: int) -> ExecutedTrade:
        ...


class PositionExitManager(Protocol):
    def monitor_execution(self, *, db: Session, execution_id: int) -> dict:
        ...


class TradeExitSynchronizer(Protocol):
    def sync(self, *, db: Session, exit_id: int) -> TradeExit:
        ...


class AgentCycleAlreadyRunning(RuntimeError):
    def __init__(self) -> None:
        super().__init__(AGENT_CYCLE_ALREADY_RUNNING)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_error(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        message = exc.__class__.__name__
    return message[:500]


def _load_json_list(value: str) -> list[dict]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


class AutonomousAgent:
    """Thin orchestration over REGRET's existing decision services."""

    def __init__(
        self,
        *,
        scout: ScoutService = market_scout,
        pipeline: PipelineService = decision_pipeline,
        router: RouterService = decision_router,
        outcomes: OutcomesService = outcome_pipeline,
        execution_sync: ExecutionSynchronizer = execution_sync_service,
        exit_manager: PositionExitManager = position_exit_service,
        exit_sync: TradeExitSynchronizer = trade_exit_sync_service,
        runtime_control: RuntimeControlService = runtime_control_service,
        config: Settings = settings,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.scout = scout
        self.pipeline = pipeline
        self.router = router
        self.outcomes = outcomes
        self.execution_sync = execution_sync
        self.exit_manager = exit_manager
        self.exit_sync = exit_sync
        self.runtime_control = runtime_control
        self.config = config
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def mode(self, *, execution_enabled: bool | None = None) -> str:
        enabled = (
            bool(self.config.paper_execution_enabled)
            if execution_enabled is None
            else execution_enabled
        )
        return "AUTONOMOUS_PAPER" if enabled else "OBSERVE"

    def _now(self) -> datetime:
        return _utc(self.now_provider())

    def _claim_cycle(
        self,
        *,
        db: Session,
        trigger: str,
        mode: str,
    ) -> AgentCycle:
        normalized_trigger = str(trigger).strip().upper()
        if normalized_trigger not in {"SCHEDULED", "MANUAL"}:
            raise ValueError("trigger must be SCHEDULED or MANUAL")

        now = self._now()
        running = list(
            db.scalars(
                select(AgentCycle)
                .where(AgentCycle.status == "RUNNING")
                .order_by(AgentCycle.started_at)
            ).all()
        )

        for existing in running:
            age_seconds = (now - _utc(existing.heartbeat_at)).total_seconds()
            if age_seconds <= self.config.autonomous_stale_cycle_seconds:
                raise AgentCycleAlreadyRunning()

        for stale in running:
            stale.status = "ABANDONED"
            stale.finished_at = now
            stale.errors_json = json.dumps(
                [
                    *_load_json_list(stale.errors_json),
                    {
                        "phase": "CLAIM",
                        "code": "STALE_CYCLE_ABANDONED",
                        "abandoned_at": now.isoformat(),
                    },
                ]
            )

        cycle = AgentCycle(
            trigger=normalized_trigger,
            status="RUNNING",
            mode=mode,
            started_at=now,
            heartbeat_at=now,
            summary_json=json.dumps(
                {
                    "phase": "CLAIMED",
                    "candidates": [],
                }
            ),
            errors_json="[]",
        )
        db.add(cycle)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise AgentCycleAlreadyRunning() from exc

        db.refresh(cycle)
        return cycle

    def _checkpoint(
        self,
        *,
        db: Session,
        cycle_id: int,
        phase: str,
        counts: dict[str, int],
        summary: dict,
        errors: list[dict],
    ) -> AgentCycle:
        cycle = db.get(AgentCycle, cycle_id)
        if cycle is None:
            raise RuntimeError("Claimed AgentCycle no longer exists")

        cycle.heartbeat_at = self._now()
        for field in COUNT_FIELDS:
            setattr(cycle, field, counts[field])
        summary["phase"] = phase
        cycle.summary_json = json.dumps(summary)
        cycle.errors_json = json.dumps(errors)
        db.commit()
        db.refresh(cycle)
        return cycle

    @staticmethod
    def _database_counts(db: Session) -> tuple[int, int]:
        outcomes = db.scalar(select(func.count()).select_from(OutcomeSnapshot))
        events = db.scalar(select(func.count()).select_from(RegretEvent))
        return int(outcomes or 0), int(events or 0)

    def _evaluate_outcomes(
        self,
        *,
        db: Session,
        phase: str,
        counts: dict[str, int],
        summary: dict,
        errors: list[dict],
    ) -> None:
        try:
            outcomes_before, events_before = self._database_counts(db)
            result = self.outcomes.evaluate_due(db=db)
            outcomes_after, events_after = self._database_counts(db)
        except Exception as exc:
            db.rollback()
            errors.append(
                {
                    "phase": phase,
                    "code": "OUTCOME_EVALUATION_FAILED",
                    "error": _safe_error(exc),
                }
            )
            summary[phase.lower()] = {"status": "FAILED"}
            return

        counts["outcomes_evaluated_count"] += max(
            outcomes_after - outcomes_before,
            0,
        )
        counts["regret_events_created_count"] += max(
            events_after - events_before,
            0,
        )
        summary[phase.lower()] = result

        for item in result.get("items", []):
            if item.get("status") == "ERROR":
                errors.append(
                    {
                        "phase": phase,
                        "code": "OUTCOME_ITEM_FAILED",
                        "source_type": item.get("source_type"),
                        "source_id": item.get("source_id"),
                        "error": item.get("reason", "Outcome evaluation failed safely"),
                    }
                )

    @staticmethod
    def _execution_status(value: object) -> str:
        return str(getattr(value, "value", value) or "").strip().lower()

    def _sync_execution(
        self,
        *,
        db: Session,
        execution_id: int,
        phase: str,
        summary: dict,
        errors: list[dict],
    ) -> dict:
        previous_status = ""
        try:
            execution = db.get(ExecutedTrade, execution_id)
            previous_status = self._execution_status(
                execution.status if execution is not None else None
            )
            synchronized = self.execution_sync.sync(
                db=db,
                execution_id=execution_id,
            )
            current_status = self._execution_status(synchronized.status)
            became_filled = (
                current_status == "filled" and previous_status != "filled"
            )
        except Exception as exc:
            db.rollback()
            failure = {
                "execution_id": execution_id,
                "previous_status": previous_status,
                "status": "SYNC_FAILED",
            }
            errors.append(
                {
                    "phase": phase,
                    "execution_id": execution_id,
                    "code": "EXECUTION_SYNC_FAILED",
                    "error": _safe_error(exc),
                }
            )
            return failure

        summary["executions_synced"] += 1
        if became_filled:
            summary["executions_filled"] += 1

        return {
            "execution_id": synchronized.id,
            "previous_status": previous_status,
            "status": current_status,
            "became_filled": became_filled,
            "filled_qty": synchronized.filled_qty,
            "filled_avg_price": synchronized.filled_avg_price,
        }

    def _reconcile_executions(
        self,
        *,
        db: Session,
        summary: dict,
        errors: list[dict],
    ) -> None:
        execution_ids = list(
            db.scalars(
                select(ExecutedTrade.id)
                .where(
                    ExecutedTrade.alpaca_order_id.is_not(None),
                    ExecutedTrade.alpaca_order_id != "",
                    func.lower(ExecutedTrade.status).not_in(
                        TERMINAL_EXECUTION_STATUSES
                    ),
                )
                .order_by(ExecutedTrade.created_at, ExecutedTrade.id)
            ).all()
        )
        reconciliation = {
            "eligible_count": len(execution_ids),
            "items": [],
        }
        for execution_id in execution_ids:
            reconciliation["items"].append(
                self._sync_execution(
                    db=db,
                    execution_id=int(execution_id),
                    phase="EXECUTION_RECONCILIATION",
                    summary=summary,
                    errors=errors,
                )
            )
        summary["execution_reconciliation"] = reconciliation

    def _sync_trade_exit(
        self,
        *,
        db: Session,
        exit_id: int,
        phase: str,
        summary: dict,
        errors: list[dict],
    ) -> dict:
        previous_status = ""
        try:
            trade_exit = db.get(TradeExit, exit_id)
            previous_status = self._execution_status(
                trade_exit.status if trade_exit is not None else None
            )
            synchronized = self.exit_sync.sync(db=db, exit_id=exit_id)
            current_status = self._execution_status(synchronized.status)
            became_filled = (
                current_status == "filled" and previous_status != "filled"
            )
        except Exception as exc:
            db.rollback()
            errors.append(
                {
                    "phase": phase,
                    "exit_id": exit_id,
                    "code": "EXIT_SYNC_FAILED",
                    "error": _safe_error(exc),
                }
            )
            return {
                "exit_id": exit_id,
                "previous_status": previous_status,
                "status": "SYNC_FAILED",
            }

        summary["exits_synced"] += 1
        if became_filled:
            summary["exits_filled"] += 1
        return {
            "exit_id": synchronized.id,
            "execution_id": synchronized.executed_trade_id,
            "previous_status": previous_status,
            "status": current_status,
            "became_filled": became_filled,
            "filled_qty": synchronized.filled_qty,
            "filled_avg_price": synchronized.filled_avg_price,
        }

    def _reconcile_trade_exits(
        self,
        *,
        db: Session,
        summary: dict,
        errors: list[dict],
    ) -> None:
        exit_ids = list(
            db.scalars(
                select(TradeExit.id)
                .where(
                    TradeExit.alpaca_order_id.is_not(None),
                    TradeExit.alpaca_order_id != "",
                    func.lower(TradeExit.status).not_in(TERMINAL_EXIT_STATUSES),
                )
                .order_by(TradeExit.created_at, TradeExit.id)
            ).all()
        )
        reconciliation = {
            "eligible_count": len(exit_ids),
            "items": [],
        }
        for exit_id in exit_ids:
            reconciliation["items"].append(
                self._sync_trade_exit(
                    db=db,
                    exit_id=int(exit_id),
                    phase="EXIT_RECONCILIATION",
                    summary=summary,
                    errors=errors,
                )
            )
        summary["exit_reconciliation"] = reconciliation

    def _monitor_open_positions(
        self,
        *,
        db: Session,
        summary: dict,
        errors: list[dict],
    ) -> None:
        filled_exit_exists = (
            select(TradeExit.id)
            .where(
                TradeExit.executed_trade_id == ExecutedTrade.id,
                func.lower(TradeExit.status) == "filled",
            )
            .exists()
        )
        execution_ids = list(
            db.scalars(
                select(ExecutedTrade.id)
                .where(
                    func.lower(ExecutedTrade.status) == "filled",
                    ExecutedTrade.filled_qty > 0,
                    ExecutedTrade.filled_avg_price > 0,
                    ~filled_exit_exists,
                )
                .order_by(ExecutedTrade.created_at, ExecutedTrade.id)
            ).all()
        )
        monitoring = {"eligible_count": len(execution_ids), "items": []}

        for execution_id in execution_ids:
            summary["open_positions_checked"] += 1
            try:
                result = self.exit_manager.monitor_execution(
                    db=db,
                    execution_id=int(execution_id),
                )
            except Exception as exc:
                db.rollback()
                errors.append(
                    {
                        "phase": "POSITION_MONITORING",
                        "execution_id": int(execution_id),
                        "code": "POSITION_EXIT_FAILED",
                        "error": _safe_error(exc),
                    }
                )
                monitoring["items"].append(
                    {
                        "execution_id": int(execution_id),
                        "action": "ERROR",
                    }
                )
                continue

            action = str(result.get("action", "")).strip().upper()
            if action in {"HOLD", "EXIT_HELD"}:
                summary["exit_holds"] += 1
            elif action == "EXIT_TRIGGERED":
                summary["exits_triggered"] += 1
                exit_id = result.get("exit_id")
                if result.get("order_submitted") and exit_id is not None:
                    result["immediate_sync"] = self._sync_trade_exit(
                        db=db,
                        exit_id=int(exit_id),
                        phase="IMMEDIATE_EXIT_SYNC",
                        summary=summary,
                        errors=errors,
                    )
            monitoring["items"].append(result)

        summary["position_monitoring"] = monitoring

    def _current_risk(
        self,
        *,
        db: Session,
        candidate_id: int,
        cycle_started_at: datetime,
        previous_risk_id: int | None,
    ) -> RiskDecision:
        risk = db.scalar(
            select(RiskDecision).where(RiskDecision.candidate_id == candidate_id)
        )
        if risk is None:
            raise RuntimeError("DecisionPipeline persisted no RiskDecision")
        if previous_risk_id is not None or risk.id == previous_risk_id:
            raise RuntimeError("RiskDecision was not produced by the current cycle")
        if _utc(risk.created_at) < _utc(cycle_started_at):
            raise RuntimeError("RiskDecision predates the current cycle")
        return risk

    def _finish(
        self,
        *,
        db: Session,
        cycle_id: int,
        status: str,
        counts: dict[str, int],
        summary: dict,
        errors: list[dict],
    ) -> AgentCycle:
        cycle = self._checkpoint(
            db=db,
            cycle_id=cycle_id,
            phase="FINISHED",
            counts=counts,
            summary=summary,
            errors=errors,
        )
        cycle.status = status
        cycle.finished_at = self._now()
        cycle.heartbeat_at = cycle.finished_at
        db.commit()
        db.refresh(cycle)
        return cycle

    def run_cycle(
        self,
        *,
        db: Session,
        trigger: str = "SCHEDULED",
    ) -> AgentCycle:
        execution_enabled = bool(self.config.paper_execution_enabled)
        new_entries_enabled = bool(
            self.config.autonomous_new_entries_enabled
        )
        mode = self.mode(execution_enabled=execution_enabled)
        runtime_audit = self.runtime_control.cycle_audit(db)
        entry_armed = bool(runtime_audit.get("effective_armed", False))
        cycle = self._claim_cycle(db=db, trigger=trigger, mode=mode)
        cycle_id = cycle.id
        cycle_started_at = cycle.started_at
        counts = {field: 0 for field in COUNT_FIELDS}
        summary: dict = {
            "phase": "CLAIMED",
            "mode": mode,
            "execution_enabled_at_start": execution_enabled,
            "new_entries_enabled_at_start": new_entries_enabled,
            "runtime_control_at_start": runtime_audit,
            "runtime_entry_armed_at_start": entry_armed,
            "executions_synced": 0,
            "executions_filled": 0,
            "open_positions_checked": 0,
            "exit_holds": 0,
            "exits_triggered": 0,
            "exits_synced": 0,
            "exits_filled": 0,
            "candidate_ids": [],
            "candidates": [],
        }
        errors: list[dict] = []
        fatal_failure = False
        selected_count = 0

        try:
            self._checkpoint(
                db=db,
                cycle_id=cycle_id,
                phase="EXECUTION_RECONCILIATION",
                counts=counts,
                summary=summary,
                errors=errors,
            )
            self._reconcile_executions(
                db=db,
                summary=summary,
                errors=errors,
            )
            self._checkpoint(
                db=db,
                cycle_id=cycle_id,
                phase="EXIT_RECONCILIATION",
                counts=counts,
                summary=summary,
                errors=errors,
            )
            self._reconcile_trade_exits(
                db=db,
                summary=summary,
                errors=errors,
            )
            self._checkpoint(
                db=db,
                cycle_id=cycle_id,
                phase="POSITION_MONITORING",
                counts=counts,
                summary=summary,
                errors=errors,
            )
            self._monitor_open_positions(
                db=db,
                summary=summary,
                errors=errors,
            )
            self._checkpoint(
                db=db,
                cycle_id=cycle_id,
                phase="OUTCOMES_BEFORE",
                counts=counts,
                summary=summary,
                errors=errors,
            )
            self._evaluate_outcomes(
                db=db,
                phase="OUTCOMES_BEFORE",
                counts=counts,
                summary=summary,
                errors=errors,
            )

            self._checkpoint(
                db=db,
                cycle_id=cycle_id,
                phase="SCOUTING",
                counts=counts,
                summary=summary,
                errors=errors,
            )
            if new_entries_enabled:
                try:
                    scouted = list(
                        self.scout.run(
                            db=db,
                            limit=self.config.autonomous_max_candidates_per_cycle,
                        )
                    )
                except Exception as exc:
                    db.rollback()
                    errors.append(
                        {
                            "phase": "SCOUT",
                            "code": "SCOUT_FAILED",
                            "error": _safe_error(exc),
                        }
                    )
                    scouted = []
                    fatal_failure = True
            else:
                scouted = []

            selected = scouted[: self.config.autonomous_max_candidates_per_cycle]
            candidate_ids = [int(candidate.id) for candidate in selected]
            selected_count = len(candidate_ids)
            counts["scouted_count"] = len(scouted)
            summary["candidate_ids"] = candidate_ids
            summary["scout"] = {
                "status": "ENABLED" if new_entries_enabled else "SKIPPED",
                "reason": (
                    None
                    if new_entries_enabled
                    else "AUTONOMOUS_NEW_ENTRIES_DISABLED"
                ),
                "returned_count": len(scouted),
                "selected_count": selected_count,
                "limit": self.config.autonomous_max_candidates_per_cycle,
            }

            for candidate_id in candidate_ids:
                candidate = db.get(CandidateTrade, candidate_id)
                item: dict = {"candidate_id": candidate_id}
                if candidate is not None:
                    item["symbol"] = candidate.symbol

                previous_risk_id = db.scalar(
                    select(RiskDecision.id).where(
                        RiskDecision.candidate_id == candidate_id
                    )
                )

                try:
                    self.pipeline.run(db=db, candidate_id=candidate_id)
                    risk = self._current_risk(
                        db=db,
                        candidate_id=candidate_id,
                        cycle_started_at=cycle_started_at,
                        previous_risk_id=previous_risk_id,
                    )
                except Exception as exc:
                    db.rollback()
                    candidate = db.get(CandidateTrade, candidate_id)
                    failure_code = (
                        candidate.status
                        if candidate is not None
                        and candidate.status
                        in {"ANALYSIS_FAILED", "CRITIC_FAILED", "RISK_FAILED"}
                        else "CANDIDATE_PIPELINE_FAILED"
                    )
                    counts["failed_count"] += 1
                    item.update(
                        {
                            "status": "FAILED",
                            "action": "NOT_ROUTED",
                            "failure_code": failure_code,
                        }
                    )
                    errors.append(
                        {
                            "phase": "DECISION_PIPELINE",
                            "candidate_id": candidate_id,
                            "code": failure_code,
                            "error": _safe_error(exc),
                        }
                    )
                    summary["candidates"].append(item)
                    self._checkpoint(
                        db=db,
                        cycle_id=cycle_id,
                        phase="CANDIDATE_FAILED",
                        counts=counts,
                        summary=summary,
                        errors=errors,
                    )
                    continue

                counts["analyzed_count"] += 1
                item.update(
                    {
                        "status": "DECIDED",
                        "risk_decision_id": risk.id,
                        "risk_decision": risk.decision,
                    }
                )

                decision = str(risk.decision).strip().upper()
                if decision == "REJECT":
                    counts["rejected_count"] += 1
                    try:
                        route = self.router.route(db=db, decision_id=risk.id)
                        item["action"] = "SHADOW_ROUTE"
                        item["shadow_trade_id"] = route.get("shadow_trade_id")
                        if not route.get("idempotent_replay", False):
                            counts["shadow_created_count"] += 1
                    except Exception as exc:
                        db.rollback()
                        counts["failed_count"] += 1
                        item.update(
                            {
                                "status": "FAILED",
                                "action": "ROUTING_FAILED",
                            }
                        )
                        errors.append(
                            {
                                "phase": "DECISION_ROUTER",
                                "candidate_id": candidate_id,
                                "risk_decision_id": risk.id,
                                "code": "REJECT_ROUTING_FAILED",
                                "error": _safe_error(exc),
                            }
                        )
                elif decision == "ACCEPT":
                    counts["accepted_count"] += 1
                    if not execution_enabled:
                        counts["execution_held_count"] += 1
                        item.update(
                            {
                                "action": "EXECUTION_HELD",
                                "reason": "PAPER_EXECUTION_DISABLED",
                            }
                        )
                    elif not entry_armed:
                        # The operator has not armed a new entry, or the arm
                        # expired or already spent its budget. This is a hold,
                        # not a REJECT: the decision was a genuine ACCEPT.
                        counts["execution_held_count"] += 1
                        item.update(
                            {
                                "action": "EXECUTION_HELD",
                                "reason": HOLD_REASON_RUNTIME_DISARMED,
                            }
                        )
                    else:
                        try:
                            route = self.router.route(db=db, decision_id=risk.id)
                            item["action"] = "PAPER_EXECUTION"
                            item["executed_trade_id"] = route.get(
                                "executed_trade_id"
                            )
                            item["order_submitted"] = bool(
                                route.get("order_submitted", False)
                            )
                            counts["paper_execution_count"] += 1
                            if (
                                item["order_submitted"]
                                and not route.get("idempotent_replay", False)
                            ):
                                item["runtime_control_after"] = (
                                    self.runtime_control.consume_execution(
                                        db,
                                        cycle_id=cycle_id,
                                    )
                                )
                                # One arm session buys once; any further
                                # candidate in this cycle is held.
                                entry_armed = (
                                    self.runtime_control.is_entry_armed(db)
                                )
                            if (
                                item["order_submitted"]
                                and not route.get("idempotent_replay", False)
                                and item["executed_trade_id"] is not None
                            ):
                                item["immediate_sync"] = self._sync_execution(
                                    db=db,
                                    execution_id=int(item["executed_trade_id"]),
                                    phase="IMMEDIATE_EXECUTION_SYNC",
                                    summary=summary,
                                    errors=errors,
                                )
                        except Exception as exc:
                            db.rollback()
                            counts["failed_count"] += 1
                            item.update(
                                {
                                    "status": "FAILED",
                                    "action": "ROUTING_FAILED",
                                }
                            )
                            errors.append(
                                {
                                    "phase": "DECISION_ROUTER",
                                    "candidate_id": candidate_id,
                                    "risk_decision_id": risk.id,
                                    "code": "ACCEPT_ROUTING_FAILED",
                                    "error": _safe_error(exc),
                                }
                            )
                else:
                    counts["failed_count"] += 1
                    item.update(
                        {
                            "status": "FAILED",
                            "action": "NOT_ROUTED",
                        }
                    )
                    errors.append(
                        {
                            "phase": "RISK_DECISION",
                            "candidate_id": candidate_id,
                            "risk_decision_id": risk.id,
                            "code": "INVALID_RISK_DECISION",
                        }
                    )

                summary["candidates"].append(item)
                self._checkpoint(
                    db=db,
                    cycle_id=cycle_id,
                    phase="CANDIDATE_COMPLETE",
                    counts=counts,
                    summary=summary,
                    errors=errors,
                )

            self._checkpoint(
                db=db,
                cycle_id=cycle_id,
                phase="OUTCOMES_AFTER",
                counts=counts,
                summary=summary,
                errors=errors,
            )
            self._evaluate_outcomes(
                db=db,
                phase="OUTCOMES_AFTER",
                counts=counts,
                summary=summary,
                errors=errors,
            )
        except Exception as exc:
            db.rollback()
            fatal_failure = True
            errors.append(
                {
                    "phase": "CYCLE",
                    "code": "AGENT_CYCLE_FAILED",
                    "error": _safe_error(exc),
                }
            )

        if fatal_failure or (
            selected_count > 0
            and counts["failed_count"] == selected_count
            and counts["analyzed_count"] == 0
        ):
            status = "FAILED"
        elif errors:
            status = "PARTIAL_FAILED"
        else:
            status = "COMPLETED"

        return self._finish(
            db=db,
            cycle_id=cycle_id,
            status=status,
            counts=counts,
            summary=summary,
            errors=errors,
        )


autonomous_agent = AutonomousAgent()
