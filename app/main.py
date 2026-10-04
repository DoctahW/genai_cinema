import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI

from app.agent.agent import build_agent
from app.agent.cache import AnswerCache
from app.agent.llm import build_model
from app.agent.service import AskService
from app.api.errors import register_exception_handlers
from app.api.routes import health_router, router
from app.config import ConfigError, Settings, load_settings
from app.db.connection import check_database


def configure_logging(level: str) -> None:
    """Configura o logging raiz; a linha de `app.ask` já vem em JSON."""
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Monta a aplicação; sem `settings`, carrega do ambiente/.env durante o lifespan."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved = settings or load_settings()
        configure_logging(resolved.log_level)
        try:
            await anyio.to_thread.run_sync(check_database, resolved.db_path)
        except sqlite3.Error as exc:
            raise ConfigError(
                f"Banco de dados inacessível em '{resolved.db_path}': {exc}. "
                "Confira DB_PATH e rode 'uv run python scripts/prepare_db.py'."
            ) from exc
        app.state.settings = resolved
        app.state.ask_service = AskService(
            build_agent(build_model(resolved)),
            resolved,
            AnswerCache(resolved.cache_path, resolved.cache_ttl_s),
        )
        yield

    app = FastAPI(
        title="CineData Analytics: API Text-to-SQL",
        description="Perguntas em português do Brasil sobre a camada Gold do CineData (SQLite, somente leitura).",
        version="0.1.0",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(router)
    app.include_router(health_router)
    return app


app = create_app()
