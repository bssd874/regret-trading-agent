from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CandidateTradeResponse(BaseModel):
    id: int
    symbol: str
    side: str
    strategy: str

    entry_price: float
    price_change_pct: float
    volume_ratio: float
    scout_score: float

    source: str
    status: str

    created_at: datetime

    model_config = ConfigDict(from_attributes=True)