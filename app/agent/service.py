"""Orquestração de uma pergunta (SPEC-07/08/09): cache, agente e log estruturado.

Esta camada não conhece HTTP: recebe a pergunta, consulta o cache de respostas,
aciona o agente no miss, grava o resultado com sucesso e devolve `AskResult`.
Cada pergunta gera exatamente uma linha JSON no logger `app.ask`, inclusive quando falha.
"""

import json
import logging
import time
from typing import Any

import anyio
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.agent.agent import AgentAnswer, Deps
from app.agent.agent import ask as agent_ask
from app.agent.cache import AnswerCache, cache_key
from app.agent.prompts import PROMPT_VERSION
from app.config import Settings

logger = logging.getLogger("app.ask")


class AskResult(BaseModel):
    answer: str = Field(description="Resposta em português do Brasil.")
    sql: str | None = Field(default=None, description="SQL executado; nulo quando nenhuma consulta foi necessária.")
    columns: list[str] = Field(default_factory=list, description="Nomes das colunas do resultado.")
    rows: list[list[Any]] = Field(default_factory=list, description="Linhas devolvidas pela consulta.")
    row_count: int = Field(default=0, description="Quantidade de linhas devolvidas (após o corte).")
    truncated: bool = Field(default=False, description="Indica que a consulta foi cortada em `sql_max_rows`.")
    assumptions: list[str] = Field(default_factory=list, description="Premissas declaradas pelo agente.")
    model_used: str | None = Field(default=None, description="Modelo que respondeu de fato.")
    cached: bool = Field(default=False, description="Indica que a resposta veio do cache.")
    latency_ms: float = Field(default=0.0, description="Latência total da pergunta, em milissegundos.")
    llm_calls: int = Field(default=0, description="Chamadas ao LLM gastas nesta pergunta.")


_CACHE_FIELDS = set(AskResult.model_fields) - {"cached", "llm_calls", "latency_ms"}


class AskService:
    def __init__(self, agent: Agent[Deps, AgentAnswer], settings: Settings, cache: AnswerCache) -> None:
        self._agent = agent
        self._settings = settings
        self._cache = cache

    async def ask(self, question: str) -> AskResult:
        """Responde `question`, usando o cache quando a chave (pergunta, modelos, prompt) coincide."""
        started = time.perf_counter()
        key = cache_key(question, self._settings.llm_models, PROMPT_VERSION)
        payload = await anyio.to_thread.run_sync(self._cache.get, key)
        if payload is not None:
            result = AskResult(**payload, cached=True, llm_calls=0, latency_ms=_elapsed_ms(started))
            _log(question, result, error=None)
            return result

        try:
            outcome = await agent_ask(self._agent, question, self._settings)
        except Exception as exc:
            # Erros não entram no cache: a próxima tentativa volta a chamar o modelo.
            _log(question, None, error=type(exc).__name__, latency_ms=_elapsed_ms(started))
            raise

        result = AskResult(
            answer=outcome.answer.answer,
            sql=outcome.sql,
            columns=outcome.result.columns if outcome.result else [],
            rows=outcome.result.rows if outcome.result else [],
            row_count=outcome.result.row_count if outcome.result else 0,
            truncated=outcome.result.truncated if outcome.result else False,
            assumptions=outcome.answer.assumptions,
            model_used=outcome.model_used,
            cached=False,
            latency_ms=_elapsed_ms(started),
            llm_calls=outcome.llm_calls,
        )
        await anyio.to_thread.run_sync(self._cache.set, key, result.model_dump(include=_CACHE_FIELDS))
        _log(question, result, error=None)
        return result


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _log(question: str, result: AskResult | None, *, error: str | None, latency_ms: float | None = None) -> None:
    logger.info(
        json.dumps(
            {
                "question": question,
                "sql": result.sql if result else None,
                "model_used": result.model_used if result else None,
                "llm_calls": result.llm_calls if result else None,
                "latency_ms": result.latency_ms if result else latency_ms,
                "cached": result.cached if result else False,
                "error": error,
            },
            ensure_ascii=False,
        )
    )
