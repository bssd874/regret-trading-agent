from fastapi import FastAPI

from backend.app.api.routes import router
from backend.app.db.database import Base, engine
from backend.app import models as _models  # noqa: F401


# =========================================================
# Create missing database tables
# =========================================================

Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="REGRET API",
    description=(
        "Counterfactual Intelligence "
        "for Autonomous Trading"
    ),
    version="0.3.0",
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
