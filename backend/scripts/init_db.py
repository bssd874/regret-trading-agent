from backend.app import models as _models  # noqa: F401
from backend.app.db.database import Base, engine


def main() -> int:
    Base.metadata.create_all(bind=engine)
    print("REGRET database schema is ready (non-destructive create-all).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
