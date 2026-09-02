from pathlib import Path


DAY02_MODULES = (
    "outcome_engine.py",
    "outcome_pipeline.py",
    "regret_engine.py",
    "regret_metrics_service.py",
)
FORBIDDEN = (
    "submit_order",
    "MarketOrderRequest",
    "cancel_order",
    "replace_order",
    "close_position",
    "close_all_positions",
)


def test_day02_modules_contain_no_order_mutations():
    services = Path(__file__).parents[1] / "app" / "services"
    for filename in DAY02_MODULES:
        source = (services / filename).read_text(encoding="utf-8")
        for forbidden in FORBIDDEN:
            assert forbidden not in source
