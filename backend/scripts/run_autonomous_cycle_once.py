from backend.app import models as _models  # noqa: F401
from backend.app.core.config import Settings, settings
from backend.app.db.database import Base, SessionLocal, engine
from backend.app.services.autonomous_agent_service import (
    AgentCycleAlreadyRunning,
    AutonomousAgent,
    autonomous_agent,
)


def run_cycle_once(
    *,
    config: Settings = settings,
    agent: AutonomousAgent = autonomous_agent,
    session_factory=SessionLocal,
    engine_bind=engine,
) -> int:
    """Run one scheduled autonomous cycle and exit.

    This entrypoint is intended for bounded cron-job invocations. It delegates
    all locking, decision, routing, and execution-safety behavior to the
    existing AutonomousAgent service.
    """
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


def main() -> int:
    return run_cycle_once()


if __name__ == "__main__":
    raise SystemExit(main())
