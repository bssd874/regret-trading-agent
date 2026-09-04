import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api.admin_routes import router as admin_router
from backend.app.api.agent_routes import router as agent_router
from backend.app.api.routes import router
from backend.app.core.config import settings
from backend.app.db.database import Base, engine
from backend.app import models as _models  # noqa: F401


# =========================================================
# Create missing database tables
# =========================================================

def bootstrap_schema() -> None:
    """Create missing tables outside serverless runtimes.

    Serverless functions are short-lived and share the hosted PostgreSQL
    database with `backend.scripts.init_db` and the scheduled one-shot agent,
    which own schema creation. Running DDL on every cold start would add
    latency and would make the whole API fail to import whenever the database
    is momentarily unreachable.
    """
    if os.getenv("VERCEL"):
        return

    Base.metadata.create_all(bind=engine)


bootstrap_schema()


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
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Accept", "Content-Type"],
)


PUBLIC_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Operator control is a separate, independently authenticated surface. It
# must keep working while every other public mutation stays blocked, so it
# is exempt from the public write gate — never from its own admin secret.
ADMIN_API_PREFIX = "/api/admin/"


@app.middleware("http")
async def protect_public_write_api(request: Request, call_next):
    if (
        request.url.path.startswith("/api/")
        and not request.url.path.startswith(ADMIN_API_PREFIX)
        and request.method.upper() in PUBLIC_WRITE_METHODS
        and not settings.public_write_api_enabled
    ):
        return JSONResponse(
            status_code=403,
            content={
                "detail": (
                    "Public write API is disabled for this deployment."
                )
            },
        )

    return await call_next(request)


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


app.include_router(
    admin_router,
    prefix="/api",
)
