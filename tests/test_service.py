"""Testes do `AskService`: cache e log, com `FunctionModel` (0 chamadas reais).

Cobrem o hit de cache com pergunta normalizada, a não-gravação de erros e a linha de log
JSON única por pergunta em `app.ask`.
"""

import json
import logging

import pytest
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.agent import build_agent
from app.agent.cache import AnswerCache, cache_key
from app.agent.prompts import PROMPT_VERSION
from app.agent.service import AskService
from app.config import Settings

LOG_KEYS = {"question", "sql", "model_used", "llm_calls", "latency_ms", "cached", "error"}


def _tool_call(sql: str) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart("run_sql", {"sql": sql})], model_name="test/model")


def _final(info: AgentInfo, answer: str) -> ModelResponse:
    return ModelResponse(
        parts=[ToolCallPart(info.output_tools[0].name, {"answer": answer, "sql": None, "assumptions": []})],
        model_name="test/model",
    )


def _model(function) -> FunctionModel:
    return FunctionModel(function, model_name="test/model")


@pytest.mark.anyio
async def test_second_identical_question_hits_cache(settings: Settings) -> None:
    """A 2ª e a 3ª variações da pergunta (caixa/acentos/espaços) não chamam o modelo de novo."""
    calls: list[list[ModelMessage]] = []

    def function(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(messages)
        if len(calls) == 1:
            return _tool_call("SELECT titulo FROM dim_movies ORDER BY sk_movie_id")
        return _final(info, "Há quatro filmes no banco.")

    service = AskService(
        build_agent(_model(function)),
        settings,
        AnswerCache(settings.cache_path, settings.cache_ttl_s),
    )

    first = await service.ask("Qual é a receita média dos filmes?")
    assert (first.cached, first.llm_calls) == (False, 2)
    assert first.sql is not None
    assert first.columns == ["titulo"]
    assert first.row_count == 4
    assert first.model_used == "test/model"

    second = await service.ask("  QUAL  E A  RECEITA MEDIA  DOS FILMES?  ")
    assert (second.cached, second.llm_calls) == (True, 0)
    assert second.answer == first.answer
    assert second.rows == first.rows
    assert second.model_used == first.model_used
    assert len(calls) == 2

    third = await service.ask("qual é a receita média dos filmes?")
    assert third.cached is True
    assert len(calls) == 2


@pytest.mark.anyio
async def test_error_is_not_cached(settings: Settings) -> None:
    """Um erro não entra no cache: a próxima tentativa volta a chamar o modelo."""
    state = {"n": 0}

    def function(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        state["n"] += 1
        if state["n"] == 1:
            raise UsageLimitExceeded("Atingiu o limite de requisições do agente.")
        if state["n"] == 2:
            return _tool_call("SELECT titulo FROM dim_movies ORDER BY sk_movie_id")
        return _final(info, "Há quatro filmes no banco.")

    cache = AnswerCache(settings.cache_path, settings.cache_ttl_s)
    service = AskService(build_agent(_model(function)), settings, cache)
    question = "Quais filmes existem?"
    key = cache_key(question, settings.llm_models, PROMPT_VERSION)

    with pytest.raises(UsageLimitExceeded):
        await service.ask(question)

    assert cache.get(key) is None
    assert state["n"] == 1

    recovered = await service.ask(question)

    assert recovered.cached is False
    assert recovered.llm_calls == 2
    assert cache.get(key) is not None
    assert state["n"] == 3


@pytest.mark.anyio
async def test_one_json_log_per_question(settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    """Cada pergunta (sucesso, hit e erro) gera exatamente uma linha JSON em `app.ask`."""
    cache = AnswerCache(settings.cache_path, settings.cache_ttl_s)
    state = {"n": 0}

    def function(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        state["n"] += 1
        if state["n"] == 1:
            return _tool_call("SELECT titulo FROM dim_movies ORDER BY sk_movie_id")
        return _final(info, "Há quatro filmes no banco.")

    service = AskService(build_agent(_model(function)), settings, cache)

    with caplog.at_level(logging.DEBUG, logger="app.ask"):
        await service.ask("Quais filmes existem?")
        success = _app_ask_records(caplog)
        assert len(success) == 1
        payload = json.loads(success[0].message)
        assert set(payload) == LOG_KEYS
        assert payload["question"] == "Quais filmes existem?"
        assert payload["sql"]
        assert payload["model_used"] == "test/model"
        assert payload["llm_calls"] == 2
        assert payload["cached"] is False
        assert payload["error"] is None
        assert isinstance(payload["latency_ms"], (int, float))

        caplog.clear()
        await service.ask("  quais filmes existem? ")
        hit = _app_ask_records(caplog)
        assert len(hit) == 1
        hit_payload = json.loads(hit[0].message)
        assert hit_payload["cached"] is True
        assert hit_payload["llm_calls"] == 0
        assert hit_payload["error"] is None

        caplog.clear()

        def failing(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise UsageLimitExceeded("A pergunta exigiu chamadas demais.")

        failing_service = AskService(build_agent(_model(failing)), settings, cache)
        with pytest.raises(UsageLimitExceeded):
            await failing_service.ask("Pergunta que estoura o limite")

        failed = _app_ask_records(caplog)
        assert len(failed) == 1
        error_payload = json.loads(failed[0].message)
        assert set(error_payload) == LOG_KEYS
        assert error_payload["error"] == "UsageLimitExceeded"
        assert error_payload["sql"] is None
        assert error_payload["model_used"] is None
        assert error_payload["llm_calls"] is None
        assert error_payload["cached"] is False


def _app_ask_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == "app.ask"]
