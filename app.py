"""Vercel Python/ASGI entrypoint for the existing REGRET FastAPI app."""

from backend.app.main import app

__all__ = ["app"]
