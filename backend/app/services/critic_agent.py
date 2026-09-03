import json
from dataclasses import dataclass

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

from backend.app.models.candidate_trade import (
    CandidateTrade,
)
from backend.app.schemas.decision import (
    CriticAnalysisOutput,
    DecisionAnalysisOutput,
)
from backend.app.services.llm.json_utils import (
    extract_json_object,
)
from backend.app.services.llm.base import StructuredLLMProvider
from backend.app.services.llm.azure_provider import azure_provider
from backend.app.services.llm.nvidia_provider import (
    nvidia_provider,
)
from backend.app.core.config import settings


@dataclass(frozen=True)
class CriticReview:
    output: CriticAnalysisOutput
    provider: str
    model_name: str

    @property
    def degraded_mode(self) -> bool:
        return self.provider == "azure-fallback"


def is_provider_availability_error(exc: Exception) -> bool:
    """Return true only for transport, throttling, or provider 5xx errors."""
    if isinstance(
        exc,
        (
            APITimeoutError,
            APIConnectionError,
            RateLimitError,
            InternalServerError,
            TimeoutError,
            ConnectionError,
        ),
    ):
        return True

    if isinstance(exc, APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500

    status_code = getattr(exc, "status_code", None)
    return isinstance(status_code, int) and (
        status_code == 429 or status_code >= 500
    )


class CriticAgent:

    def __init__(
        self,
        provider: StructuredLLMProvider = nvidia_provider,
        fallback_provider: StructuredLLMProvider = azure_provider,
    ) -> None:
        self.provider = provider
        self.fallback_provider = fallback_provider

    def critique(
        self,
        *,
        candidate: CandidateTrade,
        analysis: DecisionAnalysisOutput,
    ) -> CriticAnalysisOutput:

        return self.critique_with_metadata(
            candidate=candidate,
            analysis=analysis,
        ).output

    def critique_with_metadata(
        self,
        *,
        candidate: CandidateTrade,
        analysis: DecisionAnalysisOutput,
    ) -> CriticReview:

        context = {
            "candidate": {
                "symbol": candidate.symbol,
                "reference_price": candidate.entry_price,
                "price_change_pct": candidate.price_change_pct,
                "volume_ratio": candidate.volume_ratio,
                "scout_score": candidate.scout_score,
                "strategy": candidate.strategy,
                "source": candidate.source,
            },
            "primary_analysis": analysis.model_dump(),
        }

        prompt = f"""
You are the INDEPENDENT ADVERSARIAL CRITIC for REGRET.

The primary analyst has proposed a LONG paper-trading analysis.

Your job is NOT to create another trade.

Your job is to test the primary analyst using ONLY the supplied evidence.
Adversarial means checking the thesis rigorously, not defaulting to CHALLENGE.
Do not invent or manufacture a concern merely to reduce confidence.

IMPORTANT RULES:

- You cannot execute trades.
- You cannot approve trades.
- You cannot reject trades.
- You cannot create a new symbol.
- You cannot create a new direction.
- You cannot create a new entry price.
- You cannot create a new stop loss.
- You cannot create a new target price.
- You cannot override deterministic risk controls.
- Use ONLY the supplied evidence.
- Do NOT invent external market facts.
- Do NOT invent news.
- Do NOT invent earnings information.
- Do NOT invent analyst ratings.
- Do NOT invent macroeconomic events.
- Do NOT invent order-flow data.
- Do NOT invent fundamentals.

Look specifically for:

- unsupported claims
- overconfidence
- weak evidence
- contradictions
- unrealistic assumptions
- weak relationship between the evidence and thesis
- overly optimistic interpretation of momentum or volume

You may KEEP confidence unchanged or REDUCE confidence.

You may NEVER increase confidence.

Context:

{json.dumps(context, indent=2)}

Return ONE JSON object only.

Do not use markdown.
Do not use code fences.
Do not include commentary outside the JSON.

Required schema:

{{
  "verdict": "PASS",
  "confidence_adjustment": 0.0,
  "thesis_consistency": 0.0,
  "concerns": []
}}

Allowed verdict values:

- PASS
- CHALLENGE

Rules for PASS:

- Use PASS when the thesis is internally consistent, its claims are
  proportionate to the supplied evidence, and no material concern justifies
  reducing confidence.
- confidence_adjustment MUST be exactly 0.0.
- concerns MUST be an empty array.

Rules for CHALLENGE:

- Use CHALLENGE only when one or more concrete concerns grounded in a supplied
  candidate or analysis field materially weaken the thesis.
- confidence_adjustment MUST be negative and no less than -0.20.
- concerns MUST contain at least one concrete evidence-based concern.
- Never use a positive confidence adjustment.

Rules for thesis_consistency:

- Must be between 0.0 and 1.0.
- 1.0 means internally consistent and well supported.
- 0.0 means highly inconsistent or unsupported.

CRITICAL OUTPUT RULES:

- concerns MUST be a JSON array.
- concerns MUST contain at most 5 items.
- Never return more than 5 concerns.
- If you identify more than 5 concerns,
  return only the 5 strongest concerns.
- Each concern should be concise.
- Each concern must be based only on supplied evidence.
"""

        provider = "nvidia"
        model_name = settings.nvidia_model

        try:
            raw = self.provider.generate(
                prompt,
                response_model=CriticAnalysisOutput,
            )
        except Exception as exc:
            if not is_provider_availability_error(exc):
                raise

            provider = "azure-fallback"
            model_name = settings.azure_openai_deployment
            raw = self.fallback_provider.generate(
                prompt,
                response_model=CriticAnalysisOutput,
            )

        # Validation deliberately happens after the availability-only catch.
        # Invalid NVIDIA content must fail closed and must not trigger Azure.
        payload = extract_json_object(raw)

        result = CriticAnalysisOutput.model_validate(
            payload
        )

        return CriticReview(
            output=result,
            provider=provider,
            model_name=model_name,
        )


critic_agent = CriticAgent()
