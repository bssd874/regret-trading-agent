from sqlalchemy import inspect

from backend.app.db.database import engine


inspector = inspect(engine)

print("=" * 60)
print("REGRET — DAY 01 DATABASE CHECK")
print("=" * 60)

tables = inspector.get_table_names()

for table in tables:
    print(table)

print("=" * 60)

required = {
    "candidate_trades",
    "decision_analyses",
    "critic_analyses",
    "risk_decisions",
    "executed_trades",
    "shadow_trades",
}

missing = required - set(tables)

if missing:
    raise RuntimeError(
        f"Missing tables: {sorted(missing)}"
    )

print("DAY 01 DATABASE TABLES: OK")