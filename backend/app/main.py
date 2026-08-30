from fastapi import FastAPI

from backend.app.api.routes import router
from backend.app.db.database import Base, engine

#
# Important:
# Import SQLAlchemy models before create_all.
#
from backend.app.models.candidate_trade import CandidateTrade  # noqa: F401


Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="REGRET API",
    description=(
        "Counterfactual Intelligence "
        "for Autonomous Trading"
    ),
    version="0.1.0",
)


@app.get("/health")
def health():

    return {
        "status": "ok",
        "service": "REGRET",
        "paper_trading": True,
    }


app.include_router(
    router,
    prefix="/api",
)