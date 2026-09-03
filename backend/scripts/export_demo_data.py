import argparse
from pathlib import Path

from backend.app.db.database import SessionLocal
from backend.app.db.demo_data import DemoDataError, write_demo_export


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export persisted REGRET demo records without credentials."
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Explicitly replace an existing output file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        payload = write_demo_export(db, args.output, overwrite=args.force)
    except (DemoDataError, OSError) as exc:
        print(f"Demo export failed safely: {exc}")
        return 1
    finally:
        db.close()

    row_count = sum(len(rows) for rows in payload["tables"].values())
    print(f"Exported {row_count} persisted records to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
