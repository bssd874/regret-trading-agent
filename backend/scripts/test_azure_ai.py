"""Analysis-only Azure smoke test; no trading client is used."""

from backend.app.models.candidate_trade import CandidateTrade
from backend.app.services.decision_agent import decision_agent


def main() -> None:
    candidate = CandidateTrade(
        symbol="TEST",
        side="BUY",
        strategy="momentum",
        entry_price=100.0,
        price_change_pct=3.0,
        volume_ratio=2.0,
        scout_score=5.0,
        source="provider_smoke_test",
        status="NEW",
    )
    result = decision_agent.analyze(candidate)

    print("REGRET_AZURE_OK")
    print(f"symbol={result.symbol}")
    print(f"direction={result.direction}")
    print(f"confidence={result.confidence}")
    print("structured_output=VALID")
    print("order_submitted=False")


if __name__ == "__main__":
    main()
