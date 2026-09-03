import argparse
from pathlib import Path

from backend.app.db.database import SessionLocal
from backend.app.db.demo_data import (
    DemoDataError,
    import_demo_payload,
    load_demo_export,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a validated REGRET demo export exactly once or idempotently."
    )
    parser.add_argument("--input", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        payload = load_demo_export(args.input)
        result = import_demo_payload(db, payload)
    except (DemoDataError, OSError) as exc:
        print(f"Demo import failed safely: {exc}")
        return 1
    finally:
        db.close()

    print(
        "Demo import completed: "
        f"inserted={result['inserted']}, skipped={result['skipped']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
