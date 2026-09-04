"""Create the runtime-control table on an already-populated database.

Why this exists: the FastAPI app deliberately skips `create_all` on Vercel, so
a serverless deployment never issues DDL. The runtime-control feature adds one
new table, and without it `/api/agent/status` fails as soon as the runtime
control service runs its first SELECT. This repository has no migration
framework, so provisioning is an explicit, auditable step.

Scope is deliberately narrow. It creates exactly one table and touches nothing
else: no `drop_all`, no `ALTER`, no change to `agent_cycles` or its CHECK
constraints, no row deleted, no existing table recreated. Running it twice is
safe.

It does not arm anything. Schema creation and runtime arming are separate
concerns: the singleton control row is left to the runtime service, which
creates it lazily in the DISARMED state.

Usage (with DATABASE_URL injected into the process, never committed):

    python -m backend.scripts.ensure_runtime_control_schema
"""

import argparse

from sqlalchemy import func, inspect, select

from backend.app import models as _models  # noqa: F401
from backend.app.core.config import Settings, settings
from backend.app.db.database import SessionLocal, engine
from backend.app.models.agent_runtime_control import AgentRuntimeControl
from backend.app.services.db_diagnostics import automation_database_error


TABLE_NAME = AgentRuntimeControl.__tablename__

STATUS_CREATED = "CREATED"
STATUS_ALREADY_EXISTS = "ALREADY_EXISTS"


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Create the agent_runtime_controls table if it is missing. "
            "Idempotent, non-destructive, and creates nothing else."
        )
    )


def ensure_runtime_control_schema(
    *,
    config: Settings = settings,
    engine_bind=engine,
    session_factory=SessionLocal,
    environ: dict | None = None,
) -> int:
    """Create the runtime-control table when absent. Returns an exit code."""
    misconfigured = automation_database_error(config, environ)
    if misconfigured:
        # Never provision a throwaway SQLite file in a hosted environment.
        print(misconfigured)
        return 1

    try:
        existed = inspect(engine_bind).has_table(TABLE_NAME)
        # checkfirst keeps a second run a no-op rather than an error.
        AgentRuntimeControl.__table__.create(
            bind=engine_bind,
            checkfirst=True,
        )
        present = inspect(engine_bind).has_table(TABLE_NAME)
    except Exception as exc:
        print(
            "REGRET runtime-control schema bootstrap failed safely: "
            f"{type(exc).__name__}"
        )
        return 1

    if not present:
        print(f"RUNTIME_CONTROL_TABLE={TABLE_NAME} was not created")
        return 1

    row_present = False
    db = None
    try:
        db = session_factory()
        row_present = bool(
            db.scalar(select(func.count()).select_from(AgentRuntimeControl))
        )
    except Exception:
        row_present = False
    finally:
        if db is not None:
            db.close()

    status = STATUS_ALREADY_EXISTS if existed else STATUS_CREATED
    print(f"RUNTIME_CONTROL_TABLE={status}")
    print("RUNTIME_CONTROL_TABLE_PRESENT=true")
    print(f"RUNTIME_CONTROL_ROW_PRESENT={'true' if row_present else 'false'}")
    # The runtime service creates the singleton lazily, always DISARMED.
    print("RUNTIME_CONTROL_DEFAULT_STATE=DISARMED")
    return 0


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return ensure_runtime_control_schema()


if __name__ == "__main__":
    raise SystemExit(main())
