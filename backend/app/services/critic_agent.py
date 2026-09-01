import json

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
from backend.app.services.llm.nvidia_provider import (
    nvidia_provider,
)


class CriticAgent:

    def __init__(
        self,
        provider: StructuredLLMProvider = nvidia_provider,
    ) -> None:
        self.provider = provider

    def critique(
        self,
        *,
        candidate: CandidateTrade,
        analysis: DecisionAnalysisOutput,
    ) -> CriticAnalysisOutput:

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
You are the ADVERSARIAL CRITIC for REGRET.

The primary analyst has proposed a LONG paper-trading analysis.

Your job is NOT to create another trade.

Your job is to challenge the primary analyst using ONLY
the supplied evidence.

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

- Use PASS only if there is no meaningful issue
  with the primary analyst's reasoning.
- confidence_adjustment MUST be exactly 0.0.

Rules for CHALLENGE:

- Use CHALLENGE if the thesis is overconfident,
  weakly supported, contradictory, or unrealistic.
- confidence_adjustment MUST be between -0.20 and 0.0.
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

        raw = self.provider.generate(
            prompt,
            response_model=CriticAnalysisOutput,
        )

        payload = extract_json_object(raw)

        result = CriticAnalysisOutput.model_validate(
            payload
        )

        return result


critic_agent = CriticAgent()
