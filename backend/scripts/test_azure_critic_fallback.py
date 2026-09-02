"""Live Azure critic-fallback smoke test with a simulated Kimi outage."""

from backend.app.models.candidate_trade import CandidateTrade
from backend.app.schemas.decision import DecisionAnalysisOutput
from backend.app.services.critic_agent import CriticAgent
from backend.app.services.llm.azure_provider import azure_provider


class UnavailablePrimary:
    def generate(self, prompt, *, response_model):
        raise TimeoutError("simulated primary provider timeout")


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
    analysis = DecisionAnalysisOutput(
        symbol="TEST",
        direction="LONG",
        thesis="Supplied momentum and volume support a cautious long thesis.",
        confidence=0.8,
        entry_price=100.0,
        stop_loss=98.0,
        target_price=104.0,
        horizon_minutes=60,
        invalidation="The thesis fails below the supplied stop level.",
        evidence_summary=["Price rose 3% with 2x relative volume."],
    )

    review = CriticAgent(
        UnavailablePrimary(),
        azure_provider,
    ).critique_with_metadata(
        candidate=candidate,
        analysis=analysis,
    )

    print("REGRET_AZURE_CRITIC_FALLBACK_OK")
    print(f"provider={review.provider}")
    print(f"verdict={review.output.verdict}")
    print(f"confidence_adjustment={review.output.confidence_adjustment}")
    print("structured_output=VALID")
    print("order_submitted=False")


if __name__ == "__main__":
    main()
