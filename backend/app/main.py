from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.agent_routes import router as agent_router
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
    version="0.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Accept", "Content-Type"],
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

app.include_router(
    agent_router,
    prefix="/api",
)
