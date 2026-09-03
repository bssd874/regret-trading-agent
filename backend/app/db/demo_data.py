import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

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


DEMO_DATA_FORMAT = "regret-demo-data"
DEMO_DATA_VERSION = 1

# Foreign-key parents must appear before their dependants. AgentCycle is
# independent but retained because it supplies dashboard observability.
DEMO_MODELS = (
    AgentCycle,
    CandidateTrade,
    DecisionAnalysis,
    CriticAnalysis,
    RiskDecision,
    ExecutedTrade,
    TradeExit,
    ShadowTrade,
    OutcomeSnapshot,
    RegretEvent,
)


class DemoDataError(ValueError):
    pass


def _datetime_string(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _datetime_string(value)
    return value


def _model_columns(model) -> tuple[str, ...]:
    return tuple(column.name for column in model.__table__.columns)


def export_demo_payload(db: Session) -> dict[str, Any]:
    tables: dict[str, list[dict[str, Any]]] = {}
    for model in DEMO_MODELS:
        columns = _model_columns(model)
        records = list(db.scalars(select(model).order_by(model.id)).all())
        tables[model.__tablename__] = [
            {
                column: _serialize_value(getattr(record, column))
                for column in columns
            }
            for record in records
        ]

    return {
        "format": DEMO_DATA_FORMAT,
        "version": DEMO_DATA_VERSION,
        "exported_at": _datetime_string(datetime.now(timezone.utc)),
        "tables": tables,
    }


def write_demo_export(
    db: Session,
    output_path: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    if output_path.exists() and not overwrite:
        raise DemoDataError(
            f"Refusing to overwrite existing export: {output_path}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = export_demo_payload(db)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return payload


def load_demo_export(input_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DemoDataError(f"Unable to read a valid demo export: {input_path}") from exc
    validate_demo_payload(payload)
    return payload


def validate_demo_payload(payload: object) -> None:
    if not isinstance(payload, dict):
        raise DemoDataError("Demo export root must be an object")
    if payload.get("format") != DEMO_DATA_FORMAT:
        raise DemoDataError("Unsupported demo export format")
    if payload.get("version") != DEMO_DATA_VERSION:
        raise DemoDataError("Unsupported demo export version")
    if set(payload) - {"format", "version", "exported_at", "tables"}:
        raise DemoDataError("Demo export contains unsupported root fields")

    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise DemoDataError("Demo export tables must be an object")
    expected_tables = {model.__tablename__ for model in DEMO_MODELS}
    if set(tables) != expected_tables:
        raise DemoDataError("Demo export table set is incompatible")

    for model in DEMO_MODELS:
        table_name = model.__tablename__
        rows = tables[table_name]
        if not isinstance(rows, list):
            raise DemoDataError(f"{table_name} must contain a list of rows")
        expected_columns = set(_model_columns(model))
        seen_ids: set[int] = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != expected_columns:
                raise DemoDataError(f"{table_name} row columns are incompatible")
            row_id = row.get("id")
            if not isinstance(row_id, int) or isinstance(row_id, bool) or row_id < 1:
                raise DemoDataError(f"{table_name} contains an invalid primary key")
            if row_id in seen_ids:
                raise DemoDataError(f"{table_name} contains duplicate primary keys")
            seen_ids.add(row_id)


def _coerce_row(model, row: dict[str, Any]) -> dict[str, Any]:
    values = dict(row)
    for column in model.__table__.columns:
        value = values[column.name]
        if isinstance(column.type, DateTime) and value is not None:
            if not isinstance(value, str):
                raise DemoDataError(
                    f"{model.__tablename__}.{column.name} must be an ISO datetime"
                )
            try:
                values[column.name] = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise DemoDataError(
                    f"{model.__tablename__}.{column.name} has an invalid datetime"
                ) from exc
    return values


def _record_matches(record, row: dict[str, Any]) -> bool:
    return all(
        _serialize_value(getattr(record, column)) == _serialize_value(value)
        for column, value in row.items()
    )


def _synchronize_postgres_sequences(db: Session) -> None:
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    for model in DEMO_MODELS:
        table_name = model.__tablename__
        db.execute(
            text(
                "SELECT setval("
                f"pg_get_serial_sequence('{table_name}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table_name}), 1), "
                f"EXISTS(SELECT 1 FROM {table_name})"
                ")"
            )
        )


def import_demo_payload(db: Session, payload: object) -> dict[str, Any]:
    validate_demo_payload(payload)
    assert isinstance(payload, dict)
    tables = payload["tables"]
    assert isinstance(tables, dict)

    result: dict[str, Any] = {
        "inserted": 0,
        "skipped": 0,
        "tables": {},
    }
    try:
        for model in DEMO_MODELS:
            table_name = model.__tablename__
            table_result = {"inserted": 0, "skipped": 0}
            for raw_row in tables[table_name]:
                row = _coerce_row(model, raw_row)
                existing = db.get(model, row["id"])
                if existing is not None:
                    if not _record_matches(existing, row):
                        raise DemoDataError(
                            f"Conflicting existing row {table_name}#{row['id']}"
                        )
                    table_result["skipped"] += 1
                    result["skipped"] += 1
                    continue
                db.add(model(**row))
                table_result["inserted"] += 1
                result["inserted"] += 1
            db.flush()
            result["tables"][table_name] = table_result

        _synchronize_postgres_sequences(db)
        db.commit()
    except DemoDataError:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise DemoDataError(
            "Target database rejected the demo dataset; no records were committed"
        ) from exc
    return result
