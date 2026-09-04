import ast
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
        backend / "app" / "services" / "execution_sync_service.py",
        backend / "app" / "services" / "position_exit_service.py",
        backend / "app" / "services" / "trade_exit_sync_service.py",
        backend / "scripts" / "run_autonomous_agent.py",
        backend / "scripts" / "run_autonomous_cycle_once.py",
    )
    for source_path in sources:
        source = source_path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN:
            assert forbidden not in source


def test_order_mutation_apis_remain_isolated_to_paper_execution_service():
    app = Path(__file__).parents[1] / "app"
    allowed = app / "services" / "paper_execution_service.py"
    for source_path in app.rglob("*.py"):
        if source_path == allowed:
            continue
        source = source_path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN:
            assert forbidden not in source, f"{forbidden} found in {source_path}"


def test_all_production_trading_clients_are_hardcoded_to_paper():
    backend = Path(__file__).parents[1]
    calls = []
    for root in (backend / "app", backend / "scripts"):
        for source_path in root.rglob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if (
                    not isinstance(node.func, ast.Name)
                    or node.func.id != "TradingClient"
                ):
                    continue
                calls.append((source_path, node))
                paper = next(
                    (
                        keyword.value
                        for keyword in node.keywords
                        if keyword.arg == "paper"
                    ),
                    None,
                )
                assert isinstance(paper, ast.Constant) and paper.value is True

    assert calls
