import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.database import Base
from backend.app.models import (  # noqa: F401
    CandidateTrade,
    CriticAnalysis,
    DecisionAnalysis,
    RiskDecision,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def candidate_factory(db_session):
    def create(**overrides):
        values = {
            "symbol": "TEST",
            "side": "BUY",
            "strategy": "momentum",
            "entry_price": 100.0,
            "price_change_pct": 3.0,
            "volume_ratio": 2.0,
            "scout_score": 5.0,
            "source": "unit_test",
            "status": "NEW",
        }
        values.update(overrides)
        candidate = CandidateTrade(**values)
        db_session.add(candidate)
        db_session.commit()
        db_session.refresh(candidate)
        return candidate

    return create
