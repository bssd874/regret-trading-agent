from sqlalchemy import inspect

from backend.app import models as _models  # noqa: F401
from backend.app.db.database import Base, engine


Base.metadata.create_all(bind=engine)
required = {
    "candidate_trades",
    "decision_analyses",
    "critic_analyses",
    "risk_decisions",
    "executed_trades",
    "shadow_trades",
    "outcome_snapshots",
    "regret_events",
}
tables = set(inspect(engine).get_table_names())
missing = required - tables

if missing:
    raise RuntimeError(f"Missing tables: {sorted(missing)}")

print("REGRET_DAY02_TABLES_OK")
for table in sorted(required):
    print(table)
