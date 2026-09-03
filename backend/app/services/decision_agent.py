import json
from math import isfinite

from backend.app.models.candidate_trade import (
    CandidateTrade,
)
from backend.app.schemas.decision import (
    DecisionAnalysisOutput,
)
from backend.app.services.llm.azure_provider import (
    azure_provider,
)
from backend.app.services.llm.base import StructuredLLMProvider
from backend.app.services.llm.json_utils import (
    extract_json_object,
)


MAX_ENTRY_DEVIATION_PCT = 0.02


class DecisionAgent:

    def __init__(
        self,
        provider: StructuredLLMProvider = azure_provider,
    ) -> None:
        self.provider = provider

    def analyze(
        self,
        candidate: CandidateTrade,
    ) -> DecisionAnalysisOutput:

        reference = float(candidate.entry_price)

        if not isfinite(reference) or reference <= 0:
            raise ValueError("Candidate reference price must be positive")

        context = {
            "symbol": candidate.symbol,
            "direction": "LONG",
            "reference_price":
                candidate.entry_price,
            "price_change_pct":
                candidate.price_change_pct,
            "volume_ratio":
                candidate.volume_ratio,
            "scout_score":
                candidate.scout_score,
            "strategy":
                candidate.strategy,
            "source":
                candidate.source,
        }

        prompt = f"""
You are the PRIMARY MARKET ANALYST for REGRET,
a paper-trading research system.

You analyze a LONG trade candidate.

IMPORTANT RULES:

- You DO NOT execute trades.
- You DO NOT approve trades.
- You DO NOT override risk controls.
- Use ONLY the supplied evidence.
- Do NOT invent news, fundamentals,
  analyst ratings, earnings, macro events,
  or external market data.
- Calibrate confidence to the strength and limits of the supplied evidence.
- Use the full continuous 0-to-1 confidence range when warranted.
- Do not round confidence into fixed buckets such as 0.5, 0.6, or 0.7.
- High confidence requires unusually strong, internally consistent supplied
  evidence; weak or conflicting evidence requires lower confidence.
- Being conservative means representing uncertainty accurately, not applying
  an automatic confidence ceiling.
- The supplied reference price is the only
  current market-price reference available.

Candidate data:

{json.dumps(context, indent=2)}

Return ONE JSON object only.

Required schema:

{{
  "symbol": "{candidate.symbol}",
  "direction": "LONG",
  "thesis": "string",
  "confidence": 0.0,
  "entry_price": 0.0,
  "stop_loss": 0.0,
  "target_price": 0.0,
  "horizon_minutes": 60,
  "invalidation": "string",
  "evidence_summary": ["string"]
}}

Constraints:

- confidence must be between 0 and 1
- confidence must reflect only the supplied evidence and must not be increased
  merely to make a candidate pass downstream risk controls
- entry_price must stay within 2 percent
  of the supplied reference price
- stop_loss must be below entry_price
- target_price must be above entry_price
- evidence_summary must only refer to
  supplied evidence
"""

        raw = self.provider.generate(
            prompt,
            response_model=DecisionAnalysisOutput,
        )

        payload = extract_json_object(raw)

        result = (
            DecisionAnalysisOutput.model_validate(
                payload
            )
        )

        if (
            result.symbol.upper()
            != candidate.symbol.upper()
        ):
            raise ValueError(
                "Analyst returned wrong symbol"
            )

        deviation = abs(
            result.entry_price - reference
        ) / reference

        if deviation > MAX_ENTRY_DEVIATION_PCT:
            raise ValueError(
                "Analyst entry price deviates "
                "more than 2% from reference"
            )

        return result


decision_agent = DecisionAgent()
