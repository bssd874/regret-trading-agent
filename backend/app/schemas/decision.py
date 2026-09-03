from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ShortText = Annotated[
    str,
    Field(min_length=1, max_length=300),
]


class StrictOutputModel(BaseModel):
    """Base model for data crossing an LLM or API boundary."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class DecisionAnalysisOutput(StrictOutputModel):
    symbol: str = Field(
        min_length=1,
        max_length=16,
        pattern=r"^[A-Z][A-Z0-9.\-]*$",
    )
    direction: Literal["LONG"]
    thesis: str = Field(min_length=20, max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0)
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    target_price: float = Field(gt=0)
    horizon_minutes: int = Field(ge=5, le=1440)
    invalidation: str = Field(min_length=10, max_length=600)
    evidence_summary: list[ShortText] = Field(
        min_length=1,
        max_length=5,
    )

    @model_validator(mode="after")
    def validate_trade_levels(self):
        if self.stop_loss >= self.entry_price:
            raise ValueError("stop_loss must be below entry_price")

        if self.target_price <= self.entry_price:
            raise ValueError("target_price must be above entry_price")

        return self


class CriticAnalysisOutput(StrictOutputModel):
    # There are intentionally no symbol, direction, price, approval,
    # rejection, sizing, or execution fields in this schema.
    verdict: Literal["PASS", "CHALLENGE"]
    confidence_adjustment: float = Field(ge=-0.20, le=0.0)
    thesis_consistency: float = Field(ge=0.0, le=1.0)
    concerns: list[ShortText] = Field(
        default_factory=list,
        max_length=5,
    )

    @model_validator(mode="after")
    def validate_verdict(self):
        if self.verdict == "PASS":
            if self.confidence_adjustment != 0.0:
                raise ValueError("PASS must use confidence_adjustment=0")
            if self.concerns:
                raise ValueError("PASS must not include material concerns")
        else:
            if self.confidence_adjustment >= 0.0:
                raise ValueError("CHALLENGE must reduce confidence")
            if not self.concerns:
                raise ValueError("CHALLENGE must include a concrete concern")

        return self


class AnalystResponse(StrictOutputModel):
    provider: Literal["azure"]
    model: str
    symbol: str
    direction: Literal["LONG"]
    thesis: str
    confidence: float
    entry_price: float
    stop_loss: float
    target_price: float
    horizon_minutes: int
    invalidation: str
    evidence: list[str]


class CriticResponse(StrictOutputModel):
    provider: Literal["nvidia", "azure-fallback"]
    model: str
    verdict: Literal["PASS", "CHALLENGE"]
    confidence_adjustment: float
    thesis_consistency: float
    concerns: list[str]
    degraded_mode: bool = False


class ConsensusResponse(StrictOutputModel):
    original_confidence: float
    critic_adjustment: float
    adjusted_confidence: float


class RiskResponse(StrictOutputModel):
    decision: Literal["ACCEPT", "REJECT"]
    risk_score: float
    reward_risk_ratio: float
    proposed_position_pct: float
    reasons: list[str]


class AnalyzeCandidateResponse(StrictOutputModel):
    candidate_id: int
    analysis_id: int
    critic_id: int
    decision_id: int
    symbol: str
    analyst: AnalystResponse
    critic: CriticResponse
    consensus: ConsensusResponse
    risk: RiskResponse
    candidate_status: Literal["ACCEPTED", "REJECTED"]
    order_submitted: Literal[False]


class DecisionListItem(StrictOutputModel):
    id: int
    candidate_id: int
    symbol: str
    analyst_confidence: float
    critic_adjustment: float
    adjusted_confidence: float
    critic_verdict: Literal["PASS", "CHALLENGE"]
    critic_provider: Literal["nvidia", "azure-fallback"] = "nvidia"
    degraded_mode: bool = False
    reward_risk_ratio: float
    risk_score: float
    decision: Literal["ACCEPT", "REJECT"]
    reasons: list[str]
    created_at: datetime
    order_submitted: Literal[False]


class DecisionDetail(StrictOutputModel):
    id: int
    candidate_id: int
    analyst: AnalystResponse
    critic: CriticResponse
    consensus: ConsensusResponse
    risk: RiskResponse
    created_at: datetime
    order_submitted: Literal[False]
