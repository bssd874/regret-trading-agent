from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ConsensusResult:
    original_confidence: float
    critic_adjustment: float
    adjusted_confidence: float


class ConsensusEngine:

    def combine(
        self,
        *,
        analyst_confidence: float,
        critic_adjustment: float,
    ) -> ConsensusResult:

        if not isfinite(analyst_confidence) or not (
            0.0 <= analyst_confidence <= 1.0
        ):
            raise ValueError(
                "analyst_confidence must be 0..1"
            )

        if not isfinite(critic_adjustment) or not (
            -0.20 <= critic_adjustment <= 0.0
        ):
            raise ValueError(
                "critic_adjustment must be "
                "between -0.20 and 0"
            )

        adjusted = (
            analyst_confidence
            + critic_adjustment
        )

        adjusted = max(
            0.0,
            min(1.0, adjusted),
        )

        return ConsensusResult(
            original_confidence=round(
                analyst_confidence,
                4,
            ),
            critic_adjustment=round(
                critic_adjustment,
                4,
            ),
            adjusted_confidence=round(
                adjusted,
                4,
            ),
        )


consensus_engine = ConsensusEngine()
