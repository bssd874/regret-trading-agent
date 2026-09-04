import argparse
import os

from backend.app import models as _models  # noqa: F401
from backend.app.core.config import Settings, settings
from backend.app.db.database import Base, SessionLocal, engine
from backend.app.services.db_diagnostics import (
    automation_database_error,
    collect_database_identity,
    diagnostic_only_requested,
    format_diagnostic,
)
from backend.app.services.autonomous_agent_service import (
    AgentCycleAlreadyRunning,
    AutonomousAgent,
    autonomous_agent,
)
from backend.app.services.runtime_control_service import (
    RuntimeControlService,
    runtime_control_service,
)


ARM_SESSION_ENV_VAR = "REGRET_ARM_SESSION_ID"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run exactly one REGRET autonomous cycle and exit. "
            "Optionally claim an operator arm session first."
        )
    )
    parser.add_argument(
        "--diagnostic-only",
        action="store_true",
        default=False,
        help=(
            "Report read-only database identity and exit. Runs no cycle, "
            "contacts no provider, and submits no order."
        ),
    )
    parser.add_argument(
        "--arm-session-id",
        default=None,
        help=(
            "Operator arm session to claim before the cycle. Defaults to the "
            f"{ARM_SESSION_ENV_VAR} environment variable. Not a credential."
        ),
    )
    return parser


def run_database_diagnostic(
    *,
    config: Settings = settings,
    session_factory=SessionLocal,
) -> int:
    """Print safe database identity metadata and exit.

    Never starts a cycle, never contacts Alpaca, Azure OpenAI or NVIDIA, and
    never writes anything. Exits non-zero only when the database is
    unreachable or the environment is misconfigured.
    """
    misconfigured = automation_database_error(config)
    if misconfigured:
        print(misconfigured)
        return 1

    db = None
    try:
        db = session_factory()
        report = collect_database_identity(db)
    except Exception as exc:
        print(
            "REGRET database diagnostic failed safely: "
            f"{type(exc).__name__}"
        )
        return 1
    finally:
        if db is not None:
            db.close()

    for line in format_diagnostic(report):
        print(line)
    return 0


def run_cycle_once(
    *,
    config: Settings = settings,
    agent: AutonomousAgent = autonomous_agent,
    session_factory=SessionLocal,
    engine_bind=engine,
    arm_session_id: str | None = None,
    runtime_control: RuntimeControlService = runtime_control_service,
) -> int:
    """Run one scheduled autonomous cycle and exit.

    This entrypoint is intended for bounded cron-job invocations. It delegates
    all locking, decision, routing, and execution-safety behavior to the
    existing AutonomousAgent service.

    When an arm session id is supplied, the session is claimed atomically
    before the cycle runs. A session that cannot be claimed never arms the
    system: the cycle still runs, but only as an OBSERVE-equivalent pass in
    which a genuine ACCEPT is held rather than executed.
    """
    # Checked before the enable flag: a misconfigured automated environment is
    # an error worth failing on even when the agent is intentionally paused,
    # otherwise the run is green and silent either way.
    misconfigured = automation_database_error(config)
    if misconfigured:
        # Never let an automated run persist to an ephemeral SQLite file.
        print(misconfigured)
        return 1

    if not config.autonomous_agent_enabled:
        print(
            "REGRET autonomous agent is disabled. "
            "No scheduled cycle was run."
        )
        return 0

    try:
        Base.metadata.create_all(bind=engine_bind)
    except Exception as exc:
        print(
            "REGRET autonomous cycle initialization failed safely: "
            f"{str(exc)[:300]}"
        )
        return 1

    db = None
    try:
        db = session_factory()

        session_id = (arm_session_id or "").strip()
        if session_id:
            claim = runtime_control.claim_session(db, session_id)
            if claim.get("claimed"):
                print(
                    "Arm session claimed; new paper entries are ARMED "
                    "for this cycle."
                )
            else:
                # Fail closed: run the cycle without entry permission rather
                # than arming a session we could not verify.
                print(
                    "Arm session was NOT claimed "
                    f"({claim.get('reason')}); new entries remain disarmed."
                )

        cycle = agent.run_cycle(db=db, trigger="SCHEDULED")
    except AgentCycleAlreadyRunning:
        print(
            "AGENT_CYCLE_ALREADY_RUNNING: "
            "this scheduled invocation was skipped."
        )
        return 0
    except Exception as exc:
        print(
            "REGRET autonomous cycle failed safely: "
            f"{str(exc)[:300]}"
        )
        return 1
    finally:
        if db is not None:
            db.close()

    print(
        f"AgentCycle {cycle.id} finished with status {cycle.status}; "
        "one-shot process exiting."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.diagnostic_only or diagnostic_only_requested():
        return run_database_diagnostic()
    arm_session_id = args.arm_session_id or os.getenv(ARM_SESSION_ENV_VAR)
    return run_cycle_once(arm_session_id=arm_session_id)


if __name__ == "__main__":
    raise SystemExit(main())
