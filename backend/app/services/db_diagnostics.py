"""Read-only database identity diagnostics for automated environments.

Two jobs:

1. Prove *which* database an automated run is actually attached to, without
   revealing the connection string, host, port, user, password or SSL material.
2. Refuse to let a production/automation run silently fall back to the local
   SQLite development database.

Nothing here touches the market scout, the AI providers, Alpaca, or the
autonomous agent. It issues read-only queries only.
"""

import hashlib
import os

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, settings
from backend.app.models.agent_cycle import AgentCycle
from backend.app.models.agent_runtime_control import AgentRuntimeControl
from backend.app.models.executed_trade import ExecutedTrade
from backend.app.models.shadow_trade import ShadowTrade


# Set by the GitHub Actions runner, generic CI systems, and Vercel.
AUTOMATION_ENV_VARS = ("GITHUB_ACTIONS", "CI", "VERCEL")

# Explicit opt-in so an operator can demand the strict check anywhere.
REQUIRE_DATABASE_URL_ENV_VAR = "REGRET_REQUIRE_DATABASE_URL"

DIAGNOSTIC_ONLY_ENV_VAR = "REGRET_DIAGNOSTIC_ONLY"

SQLITE_IN_AUTOMATION_MESSAGE = (
    "REGRET refused to run: this is an automated environment but "
    "DATABASE_URL is not configured, so the process would have used the "
    "local SQLite development database and persisted nothing durable."
)


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def in_automation(environ: dict | None = None) -> bool:
    """True inside GitHub Actions, generic CI, or a Vercel runtime."""
    env = environ if environ is not None else os.environ
    if _is_truthy(env.get(REQUIRE_DATABASE_URL_ENV_VAR)):
        return True
    return any(_is_truthy(env.get(name)) for name in AUTOMATION_ENV_VARS)


def diagnostic_only_requested(environ: dict | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return _is_truthy(env.get(DIAGNOSTIC_ONLY_ENV_VAR))


def uses_sqlite(config: Settings) -> bool:
    return str(config.database_url).startswith("sqlite")


def automation_database_error(
    config: Settings = settings,
    environ: dict | None = None,
) -> str | None:
    """Return a safe error message when automation would use SQLite."""
    if in_automation(environ) and uses_sqlite(config):
        return SQLITE_IN_AUTOMATION_MESSAGE
    return None


def safe_db_fingerprint(dialect: str, database_name: str, oid: str) -> str:
    """Stable identity hash over NON-SECRET database identity only.

    Deliberately excludes host, port, user, password and query parameters, so
    the digest can be compared between environments without disclosing how to
    reach the database.
    """
    material = f"{dialect}|{database_name}|{oid}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def collect_database_identity(db: Session) -> dict:
    """Read-only identity and application-fingerprint metadata."""
    bind = db.get_bind()
    dialect = bind.dialect.name

    database_name = "local-sqlite"
    database_oid = "0"
    if dialect != "sqlite":
        # current_database() and the database OID are non-secret identifiers.
        database_name = str(db.scalar(text("SELECT current_database()")) or "")
        database_oid = str(
            db.scalar(
                text(
                    "SELECT oid FROM pg_database "
                    "WHERE datname = current_database()"
                )
            )
            or "0"
        )

    inspector = inspect(bind)
    runtime_control_present = inspector.has_table(
        AgentRuntimeControl.__tablename__
    )

    def _count(model) -> int:
        if not inspector.has_table(model.__tablename__):
            return 0
        return int(db.scalar(select(func.count()).select_from(model)) or 0)

    latest_cycle_id = None
    if inspector.has_table(AgentCycle.__tablename__):
        latest_cycle_id = db.scalar(select(func.max(AgentCycle.id)))

    return {
        "db_engine": dialect,
        "db_name": database_name,
        "agent_cycle_count": _count(AgentCycle),
        "latest_agent_cycle_id": latest_cycle_id,
        "executed_trade_count": _count(ExecutedTrade),
        "shadow_trade_count": _count(ShadowTrade),
        "runtime_control_present": runtime_control_present,
        "safe_db_fingerprint": safe_db_fingerprint(
            dialect, database_name, database_oid
        ),
    }


def format_diagnostic(report: dict) -> list[str]:
    """Render the report as flat key=value lines. Never includes secrets."""
    latest = report["latest_agent_cycle_id"]
    return [
        f"DB_ENGINE={report['db_engine']}",
        f"DB_NAME={report['db_name']}",
        f"AGENT_CYCLE_COUNT={report['agent_cycle_count']}",
        f"LATEST_AGENT_CYCLE_ID={latest if latest is not None else 'none'}",
        f"EXECUTED_TRADE_COUNT={report['executed_trade_count']}",
        f"SHADOW_TRADE_COUNT={report['shadow_trade_count']}",
        "RUNTIME_CONTROL_PRESENT="
        f"{'true' if report['runtime_control_present'] else 'false'}",
        f"SAFE_DB_FINGERPRINT={report['safe_db_fingerprint']}",
    ]
