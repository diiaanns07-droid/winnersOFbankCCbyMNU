"""Веб-демо для банковского аналитика поверх общего движка ``run_review``.

Запуск: ``python -m bcc_review.web`` (см. ``python -m bcc_review.web --help``).
"""

from .app import App, create_app, make_server, serve_in_thread
from .engine import EngineSpec, resolve_engine
from .service import Settings

__all__ = ["App", "EngineSpec", "Settings", "create_app", "make_server", "resolve_engine", "serve_in_thread"]
