"""Testes do fallback, classificação de erros e cota do OpenRouter.

OpenRouter simulado com `httpx.MockTransport`: nenhuma chamada real, nenhuma rede.
"""

import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError

from app.agent.llm import (
    ModelsUnavailable,
    QuotaExceeded,
    QuotaInfo,
    build_model,
    classify_llm_error,
    get_quota,
    is_upstream_rate_limit,
    next_reset,
    should_fallback,
)
from app.config import Settings

Responder = Callable[[int], httpx.Response]
"""Resposta planejada para a n-ésima (1-based) chamada de um modelo."""

UPSTREAM_429 = {
    "error": {
        "message": "nvidia/nemotron-3.5-lightning:free is temporarily rate-limited upstream. Please retry shortly.",
        "code": 429,
        "metadata": {"raw": "...", "provider_name": "Nvidia"},
    }
}

DAILY_429 = {
    "error": {
        "message": (
            "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day"
        ),
        "code": 429,
        "metadata": {"headers": {"X-RateLimit-Limit": "50", "X-RateLimit-Remaining": "0"}},
    }
}


class Router:
    """Handler do MockTransport que registra chamadas por modelo do request JSON."""

    def __init__(self, responders: dict[str, Responder]) -> None:
        self.responders = responders
        self.calls: Counter[str] = Counter()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        self.calls[model] += 1
        return self.responders[model](self.calls[model])


def chat_ok(model: str, content: str = "resultado") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def http_error(status: int, body: dict) -> httpx.Response:
    return httpx.Response(status, json=body)


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def run_expecting_error(agent: Agent, question: str) -> BaseException:
    with pytest.raises(BaseException) as excinfo:
        await agent.run(question)
    return excinfo.value


@pytest.mark.anyio
async def test_upstream_429_falls_back_to_next_model(settings: Settings) -> None:
    router = Router(
        {
            "primary/model:free": lambda n: http_error(429, UPSTREAM_429),
            "secondary/model:free": lambda n: chat_ok("secondary/model:free"),
        }
    )
    async with make_client(router) as client:
        agent = Agent(build_model(settings, client), output_type=str)
        result = await agent.run("oi")

    assert result.output == "resultado"
    assert result.response.model_name == "secondary/model:free"
    assert dict(router.calls) == {"primary/model:free": 1, "secondary/model:free": 1}


@pytest.mark.anyio
async def test_daily_quota_429_stops_chain(settings: Settings) -> None:
    router = Router(
        {
            "primary/model:free": lambda n: http_error(429, DAILY_429),
            "secondary/model:free": lambda n: chat_ok("secondary/model:free"),
        }
    )
    async with make_client(router) as client:
        agent = Agent(build_model(settings, client), output_type=str)
        error = await run_expecting_error(agent, "oi")

    classified = classify_llm_error(error)
    assert isinstance(classified, QuotaExceeded)
    assert "21h" in str(classified) and "Brasília" in str(classified)
    assert classified.reset_at.tzinfo is not None
    assert classified.reset_at == next_reset(datetime.now(UTC))
    # Nunca repetir no mesmo modelo nem tentar o próximo.
    assert dict(router.calls) == {"primary/model:free": 1}


@pytest.mark.anyio
async def test_all_upstream_429_raises_models_unavailable(settings: Settings) -> None:
    router = Router(
        {
            "primary/model:free": lambda n: http_error(429, UPSTREAM_429),
            "secondary/model:free": lambda n: http_error(429, UPSTREAM_429),
        }
    )
    async with make_client(router) as client:
        agent = Agent(build_model(settings, client), output_type=str)
        error = await run_expecting_error(agent, "oi")

    classified = classify_llm_error(error)
    assert isinstance(classified, ModelsUnavailable)
    assert dict(router.calls) == {"primary/model:free": 1, "secondary/model:free": 1}


@pytest.mark.anyio
async def test_server_error_falls_back(settings: Settings) -> None:
    router = Router(
        {
            "primary/model:free": lambda n: http_error(500, {"error": {"message": "boom"}}),
            "secondary/model:free": lambda n: chat_ok("secondary/model:free"),
        }
    )
    async with make_client(router) as client:
        agent = Agent(build_model(settings, client), output_type=str)
        result = await agent.run("oi")

    assert result.response.model_name == "secondary/model:free"
    assert dict(router.calls) == {"primary/model:free": 1, "secondary/model:free": 1}


@pytest.mark.anyio
async def test_auth_error_does_not_fall_back(settings: Settings) -> None:
    router = Router(
        {
            "primary/model:free": lambda n: http_error(401, {"error": {"message": "No auth credentials"}}),
            "secondary/model:free": lambda n: chat_ok("secondary/model:free"),
        }
    )
    async with make_client(router) as client:
        agent = Agent(build_model(settings, client), output_type=str)
        error = await run_expecting_error(agent, "oi")

    assert classify_llm_error(error) is None
    assert dict(router.calls) == {"primary/model:free": 1}


@pytest.mark.anyio
async def test_single_model_upstream_429_is_models_unavailable(settings: Settings) -> None:
    single = settings.model_copy(update={"llm_models": ["primary/model:free"]})
    router = Router({"primary/model:free": lambda n: http_error(429, UPSTREAM_429)})
    async with make_client(router) as client:
        agent = Agent(build_model(single, client), output_type=str)
        error = await run_expecting_error(agent, "oi")

    assert isinstance(classify_llm_error(error), ModelsUnavailable)
    assert dict(router.calls) == {"primary/model:free": 1}


@pytest.mark.anyio
async def test_single_model_daily_429_is_quota_exceeded(settings: Settings) -> None:
    single = settings.model_copy(update={"llm_models": ["primary/model:free"]})
    router = Router({"primary/model:free": lambda n: http_error(429, DAILY_429)})
    async with make_client(router) as client:
        agent = Agent(build_model(single, client), output_type=str)
        error = await run_expecting_error(agent, "oi")

    assert isinstance(classify_llm_error(error), QuotaExceeded)
    assert dict(router.calls) == {"primary/model:free": 1}


def test_classify_llm_error_auth_error_is_none() -> None:
    assert classify_llm_error(ModelHTTPError(401, "m", {"error": {"message": "No auth"}})) is None


def test_classify_llm_error_unreachable_model_is_models_unavailable() -> None:
    assert isinstance(classify_llm_error(ModelHTTPError(503, "m", {"error": {"message": "down"}})), ModelsUnavailable)
    assert isinstance(classify_llm_error(ModelAPIError("m", "connection error")), ModelsUnavailable)


def test_should_fallback_predicate() -> None:
    assert should_fallback(ModelHTTPError(429, "m", UPSTREAM_429))
    assert should_fallback(ModelHTTPError(503, "m", {"error": {"message": "unavailable"}}))
    assert should_fallback(ModelAPIError("m", "connection error"))
    assert not should_fallback(ModelHTTPError(429, "m", DAILY_429))
    assert not should_fallback(ModelHTTPError(401, "m", {"error": {"message": "No auth"}}))
    assert not should_fallback(ModelHTTPError(400, "m", {"error": {"message": "bad"}}))
    assert is_upstream_rate_limit(ModelHTTPError(429, "m", UPSTREAM_429))
    # O corpo pode vir como o próprio objeto de erro, sem o invólucro "error".
    assert is_upstream_rate_limit(ModelHTTPError(429, "m", UPSTREAM_429["error"]))
    assert not is_upstream_rate_limit(ModelHTTPError(429, "m", DAILY_429))
    assert not is_upstream_rate_limit(ModelHTTPError(500, "m", UPSTREAM_429))


@pytest.mark.anyio
async def test_get_quota_reads_nested_data(settings: Settings) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "data": {
                    "label": "x",
                    "free_model_daily_requests": {"used": 12, "limit": 50, "remaining": 38},
                }
            },
        )

    async with make_client(handler) as client:
        info = await get_quota(settings, client)

    assert info == QuotaInfo(used=12, limit=50, remaining=38)
    assert seen["url"] == "https://openrouter.test/api/v1/key"
    assert seen["authorization"] == "Bearer test-key"


@pytest.mark.anyio
async def test_get_quota_accepts_root_and_missing_fields(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"free_model_daily_requests": {"used": 1}})

    async with make_client(handler) as client:
        info = await get_quota(settings, client)

    assert info == QuotaInfo(used=1, limit=None, remaining=None)


@pytest.mark.anyio
async def test_get_quota_propagates_http_error(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    async with make_client(handler) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await get_quota(settings, client)


def test_next_reset_near_midnight() -> None:
    assert next_reset(datetime(2026, 10, 4, 23, 59, 59, tzinfo=UTC)) == datetime(2026, 10, 5, tzinfo=UTC)
    assert next_reset(datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)) == datetime(2026, 10, 6, tzinfo=UTC)
    # 20h30 em Brasília (UTC-3) já é 23h30 UTC: o reset é a meia-noite UTC seguinte.
    brasilia = timezone(timedelta(hours=-3))
    assert next_reset(datetime(2026, 10, 4, 20, 30, tzinfo=brasilia)) == datetime(2026, 10, 5, tzinfo=UTC)
