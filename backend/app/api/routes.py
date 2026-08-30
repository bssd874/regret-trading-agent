from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.db.database import get_db
from backend.app.models.candidate_trade import CandidateTrade
from backend.app.schemas.candidate_trade import CandidateTradeResponse
from backend.app.services.alpaca_service import alpaca_service
from backend.app.services.market_scout import market_scout


router = APIRouter()


@router.get("/account")
def get_account():

    account = alpaca_service.get_account()

    return {
        "status": getattr(
            account.status,
            "value",
            str(account.status),
        ),
        "cash": float(account.cash),
        "equity": float(account.equity),
        "buying_power": float(
            account.buying_power
        ),
        "paper": True,
    }


@router.get("/market/movers")
def get_market_movers():

    movers = alpaca_service.get_market_movers(
        top=10
    )

    return {
        "gainers": [
            {
                "symbol": item.symbol,
                "price": item.price,
                "percent_change":
                    item.percent_change,
            }
            for item in movers.gainers
        ],

        "losers": [
            {
                "symbol": item.symbol,
                "price": item.price,
                "percent_change":
                    item.percent_change,
            }
            for item in movers.losers
        ],
    }


@router.post(
    "/scout/run",
    response_model=list[CandidateTradeResponse],
)
def run_scout(
    db: Session = Depends(get_db),
):

    return market_scout.run(
        db=db,
        limit=5,
    )


@router.get(
    "/candidates",
    response_model=list[CandidateTradeResponse],
)
def get_candidates(
    db: Session = Depends(get_db),
):

    statement = (
        select(CandidateTrade)
        .order_by(
            desc(CandidateTrade.created_at)
        )
        .limit(50)
    )

    return list(
        db.scalars(statement).all()
    )
