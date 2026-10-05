"""Testes do agente Text-to-SQL com `FunctionModel`: 0 chamadas reais a LLM.

Cobrem o fluxo pergunta → ferramenta → resposta, retry após SQL inválido/timeout, corte de
linhas enviadas ao modelo, teto de requisições e tradução do 429 de cota.
"""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelResponse, RetryPromptPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.agent import AgentAnswer, ask, build_agent
from app.agent.llm import QuotaExceeded
from app.config import Settings
from app.db.guardrails import validate_sql

Responder = Callable[[list[ModelMessage], AgentInfo], ModelResponse]
"""Resposta planejada para a n-ésima chamada do modelo (1-based)."""


def _final(info: AgentInfo, answer: str, sql: str | None = None, assumptions: list[str] | None = None) -> ModelResponse:
    """Chama a ferramenta de saída real do agente com a resposta final."""
    return ModelResponse(
        parts=[
            ToolCallPart(
                info.output_tools[0].name,
                {"answer": answer, "sql": sql, "assumptions": assumptions or []},
            )
        ],
        model_name="test/model",
    )


def _tool_call(sql: str) -> ModelResponse:
    """Chama a ferramenta `run_sql` com o SQL informado."""
    return ModelResponse(parts=[ToolCallPart("run_sql", {"sql": sql})], model_name="test/model")


def _scripted(responders: list[Responder]) -> tuple[FunctionModel, list[list[ModelMessage]]]:
    """`FunctionModel` que executa os responders em ordem e registra as mensagens recebidas."""
    calls: list[list[ModelMessage]] = []

    def function(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(messages)
        return responders[len(calls) - 1](messages, info)

    return FunctionModel(function, model_name="test/model"), calls


def _retry_prompt(messages: list[ModelMessage]) -> str | None:
    """Conteúdo do `RetryPromptPart` recebido pelo modelo na última mensagem, se houver."""
    for part in messages[-1].parts:
        if isinstance(part, RetryPromptPart):
            return str(part.content)
    return None


def _tool_return(messages: list[ModelMessage], tool_name: str) -> dict[str, Any] | None:
    """Conteúdo do `ToolReturnPart` da ferramenta na última mensagem, se for um dicionário."""
    for part in messages[-1].parts:
        if isinstance(part, ToolReturnPart) and part.tool_name == tool_name and isinstance(part.content, dict):
            return part.content
    return None


def _movie_count(db_path: Path) -> int:
    """Quantidade de linhas em `dim_movies` (confere que a escrita foi bloqueada)."""
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM dim_movies").fetchone()[0]
    finally:
        conn.close()


@pytest.mark.anyio
async def test_happy_path_runs_query_then_answers(settings: Settings) -> None:
    responders: list[Responder] = [
        lambda messages, info: _tool_call("SELECT titulo FROM dim_movies ORDER BY sk_movie_id"),
        lambda messages, info: _final(
            info,
            "Há quatro filmes no banco.",
            sql="SELECT titulo FROM dim_movies ORDER BY sk_movie_id",
            assumptions=["Considerei todos os filmes cadastrados."],
        ),
    ]
    model, calls = _scripted(responders)

    outcome = await ask(build_agent(model), "Quais filmes existem?", settings)

    assert len(calls) == 2
    assert outcome.llm_calls == 2
    assert outcome.model_used == "test/model"
    # Fonte de verdade é o SQL que passou pelo guardrail, não o texto que o LLM enviou.
    assert outcome.sql == validate_sql(
        "SELECT titulo FROM dim_movies ORDER BY sk_movie_id", max_rows=settings.sql_max_rows
    )
    assert outcome.result is not None
    assert outcome.result.columns == ["titulo"]
    assert outcome.result.rows == [["Filme Lucrativo"], ["Filme Prejuízo"], ["Sem Receita"], ["Futuro"]]
    assert outcome.result.row_count == 4
    assert outcome.result.truncated is False
    assert outcome.answer == AgentAnswer(
        answer="Há quatro filmes no banco.",
        sql="SELECT titulo FROM dim_movies ORDER BY sk_movie_id",
        assumptions=["Considerei todos os filmes cadastrados."],
    )


@pytest.mark.anyio
async def test_retry_after_invalid_sql(settings: Settings, mini_db_path: Path) -> None:
    before = _movie_count(mini_db_path)

    def second(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        retry = _retry_prompt(messages)
        assert retry is not None
        assert "DELETE" in retry
        return _tool_call("SELECT titulo FROM dim_movies ORDER BY sk_movie_id")

    responders: list[Responder] = [
        lambda messages, info: _tool_call("DELETE FROM dim_movies"),
        second,
        lambda messages, info: _final(info, "Listei os filmes."),
    ]
    model, calls = _scripted(responders)

    outcome = await ask(build_agent(model), "Apague os filmes.", settings)

    assert len(calls) == 3
    assert outcome.llm_calls == 3
    assert _movie_count(mini_db_path) == before
    assert outcome.result is not None
    assert outcome.result.row_count == 4


@pytest.mark.anyio
async def test_missing_column_retry_names_the_right_table(settings: Settings) -> None:
    def second(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        retry = _retry_prompt(messages)
        assert retry is not None
        assert "fact_movies_performance" in retry
        return _tool_call(
            "SELECT m.titulo, f.popularidade FROM dim_movies m "
            "JOIN fact_movies_performance f ON f.sk_movie_id = m.sk_movie_id ORDER BY f.popularidade DESC"
        )

    responders: list[Responder] = [
        lambda messages, info: _tool_call("SELECT m.titulo, m.popularidade FROM dim_movies m"),
        second,
        lambda messages, info: _final(info, "Filme Lucrativo é o mais popular."),
    ]
    model, calls = _scripted(responders)

    outcome = await ask(build_agent(model), "Os filmes mais populares", settings)

    assert len(calls) == 3
    assert outcome.result is not None
    assert outcome.result.rows[0] == ["Filme Lucrativo", 90.5]


@pytest.mark.anyio
async def test_out_of_scope_answers_without_query(settings: Settings) -> None:
    responders: list[Responder] = [
        lambda messages, info: _final(info, "Esta pergunta está fora do catálogo de filmes."),
    ]
    model, calls = _scripted(responders)

    outcome = await ask(build_agent(model), "Qual a capital da França?", settings)

    assert len(calls) == 1
    assert outcome.llm_calls == 1
    assert outcome.sql is None
    assert outcome.result is None
    assert outcome.answer.sql is None


@pytest.mark.anyio
async def test_request_limit_stops_invalid_loop(settings: Settings) -> None:
    calls: list[list[ModelMessage]] = []

    def function(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(messages)
        return _tool_call("DELETE FROM dim_movies")

    with pytest.raises(UsageLimitExceeded):
        await ask(build_agent(FunctionModel(function)), "Apague tudo.", settings)

    assert 0 < len(calls) <= settings.agent_request_limit


@pytest.mark.anyio
async def test_tool_result_is_capped_for_model(settings: Settings) -> None:
    limited = settings.model_copy(update={"sql_max_rows": 200})
    sql = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 120) SELECT x FROM c"

    def second(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        payload = _tool_return(messages, "run_sql")
        assert payload is not None
        assert len(payload["rows"]) == 50
        assert payload["row_count"] == 120
        assert payload["rows_omitted_for_model"] == 70
        return _final(info, "A consulta devolveu 120 valores.")

    responders: list[Responder] = [lambda messages, info: _tool_call(sql), second]
    model, calls = _scripted(responders)

    outcome = await ask(build_agent(model), "Gere 120 números.", limited)

    assert len(calls) == 2
    assert outcome.result is not None
    assert outcome.result.row_count == 120
    assert len(outcome.result.rows) == 120


@pytest.mark.anyio
async def test_daily_quota_429_raises_quota_exceeded(settings: Settings) -> None:
    def function(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise ModelHTTPError(
            429,
            "m",
            body={"error": {"message": "Rate limit exceeded: free-models-per-day", "code": 429}},
        )

    with pytest.raises(QuotaExceeded):
        await ask(build_agent(FunctionModel(function)), "Quais filmes existem?", settings)


@pytest.mark.anyio
async def test_timeout_becomes_retry(settings: Settings) -> None:
    limited = settings.model_copy(update={"sql_timeout_s": 0.05})
    infinite = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT COUNT(*) FROM c"

    def second(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        retry = _retry_prompt(messages)
        assert retry is not None
        assert "tempo limite" in retry
        return _tool_call("SELECT titulo FROM dim_movies ORDER BY sk_movie_id")

    responders: list[Responder] = [
        lambda messages, info: _tool_call(infinite),
        second,
        lambda messages, info: _final(info, "Listei os filmes."),
    ]
    model, calls = _scripted(responders)

    outcome = await ask(build_agent(model), "Conte infinitamente.", limited)

    assert len(calls) == 3
    assert outcome.llm_calls == 3
    assert outcome.sql == validate_sql(
        "SELECT titulo FROM dim_movies ORDER BY sk_movie_id", max_rows=limited.sql_max_rows
    )
