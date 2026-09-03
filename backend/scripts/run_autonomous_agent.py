import time
from collections.abc import Callable

from backend.app import models as _models  # noqa: F401
from backend.app.core.config import Settings, settings
from backend.app.db.database import Base, SessionLocal, engine
from backend.app.services.autonomous_agent_service import (
    AgentCycleAlreadyRunning,
    AutonomousAgent,
    autonomous_agent,
)


def run_worker(
    *,
    config: Settings = settings,
    agent: AutonomousAgent = autonomous_agent,
    session_factory=SessionLocal,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    if not config.autonomous_agent_enabled:
        print(
            "REGRET autonomous agent is disabled. "
            "Set AUTONOMOUS_AGENT_ENABLED=true to run the worker."
        )
        return 0

    Base.metadata.create_all(bind=engine)
    print(
        "REGRET autonomous agent started "
        f"in {agent.mode()} mode; interval={config.autonomous_cycle_seconds}s."
    )

    try:
        while True:
            db = session_factory()
            try:
                cycle = agent.run_cycle(db=db, trigger="SCHEDULED")
                print(
                    f"AgentCycle {cycle.id} finished with status {cycle.status}."
                )
            except AgentCycleAlreadyRunning:
                print(
                    "AGENT_CYCLE_ALREADY_RUNNING: this scheduled tick was skipped."
                )
            except Exception as exc:
                print(
                    "Autonomous cycle failed safely; worker will continue: "
                    f"{str(exc)[:300]}"
                )
            finally:
                db.close()

            sleep(config.autonomous_cycle_seconds)
    except KeyboardInterrupt:
        print("REGRET autonomous agent stopped gracefully.")
        return 0


def main() -> int:
    return run_worker()


if __name__ == "__main__":
    raise SystemExit(main())
