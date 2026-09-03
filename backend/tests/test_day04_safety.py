from pathlib import Path


FORBIDDEN = (
    "submit_order",
    "MarketOrderRequest",
    "cancel_order",
    "replace_order",
    "close_position",
    "close_all_positions",
)


def test_autonomous_agent_sources_contain_no_order_mutation_calls():
    backend = Path(__file__).parents[1]
    sources = (
        backend / "app" / "services" / "autonomous_agent_service.py",
        backend / "scripts" / "run_autonomous_agent.py",
    )
    for source_path in sources:
        source = source_path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN:
            assert forbidden not in source
