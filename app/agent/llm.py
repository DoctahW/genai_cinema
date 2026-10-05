import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel
from pydantic_ai.exceptions import (
    FallbackExceptionGroup,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
)
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import Settings

MODEL_TIMEOUT_S = 60.0

QUOTA_TIMEOUT_S = 15.0

_KEY_ENDPOINT = "/key"


class QuotaExceeded(Exception):
    """Cota diária do OpenRouter esgotada (429 sem `upstream`)."""

    def __init__(self, reset_at: datetime, message: str | None = None) -> None:
        self.reset_at = reset_at
        super().__init__(
            message
            or (
                "Cota diária de modelos gratuitos do OpenRouter esgotada. "
                f"O contador reseta à meia-noite UTC (21h no horário de Brasília), em {reset_at.isoformat()}."
            )
        )


class ModelsUnavailable(Exception):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "Todos os modelos configurados estão indisponíveis ou lotados no momento. Tente novamente mais tarde."
        )


class QuotaInfo(BaseModel):
    used: int | None = None
    limit: int | None = None
    remaining: int | None = None


def next_reset(now: datetime) -> datetime:
    """Próxima meia-noite UTC estritamente depois de `now` (= 21h no horário de Brasília)."""
    if now.tzinfo is None:
        raise ValueError("next_reset exige um datetime com timezone")
    now_utc = now.astimezone(UTC)
    tomorrow = now_utc.date() + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=UTC)


def _error_payload(body: object) -> dict[str, Any] | None:
    payload = body
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    if not isinstance(payload, dict):
        return None
    inner = payload.get("error")
    return inner if isinstance(inner, dict) else payload


def _mentions_upstream(body: object) -> bool:
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except ValueError:
            return "upstream" in body.lower()
        return _mentions_upstream(parsed)
    error = _error_payload(body)
    if error is None:
        return False
    message = error.get("message")
    if isinstance(message, str) and "upstream" in message.lower():
        return True
    metadata = error.get("metadata")
    if isinstance(metadata, dict):
        if metadata.get("provider_name"):
            return True
        if "upstream_provider" in metadata:
            return True
    return "upstream_provider" in error


def is_upstream_rate_limit(exc: BaseException) -> bool:
    """True só para 429 de provedor lotado: pode trocar de modelo sem gastar a cota diária."""
    if not isinstance(exc, ModelHTTPError) or exc.status_code != 429:
        return False
    return _mentions_upstream(exc.body)


def should_fallback(exc: Exception) -> bool:
    """Predicado do `FallbackModel`: vale a pena tentar o próximo modelo com este erro."""
    if is_upstream_rate_limit(exc):
        return True
    if isinstance(exc, ModelHTTPError):
        # 404: o modelo saiu do catálogo do OpenRouter; os outros da cadeia continuam válidos.
        return exc.status_code == 404 or 500 <= exc.status_code < 600
    # Dentro de `Model.request`, UnexpectedModelBehavior é resposta malformada do provedor
    # (ex.: `finish_reason` inválido); outro modelo pode responder direito.
    if isinstance(exc, UnexpectedModelBehavior):
        return True
    # Erros sem status HTTP (conexão, timeout, stream interrompido): outro modelo pode responder.
    return isinstance(exc, ModelAPIError)


def _is_daily_quota_error(exc: BaseException) -> bool:
    return isinstance(exc, ModelHTTPError) and exc.status_code == 429 and not is_upstream_rate_limit(exc)


def _leaf_exceptions(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        leaves: list[BaseException] = []
        for inner in exc.exceptions:
            leaves.extend(_leaf_exceptions(inner))
        return leaves
    return [exc]


def classify_llm_error(exc: BaseException) -> QuotaExceeded | ModelsUnavailable | None:
    """Traduz erros do pydantic-ai em erros de domínio: cota esgotada ou modelos indisponíveis."""
    if _is_daily_quota_error(exc):
        return QuotaExceeded(next_reset(datetime.now(UTC)))
    if isinstance(exc, FallbackExceptionGroup):
        if any(_is_daily_quota_error(member) for member in _leaf_exceptions(exc)):
            return QuotaExceeded(next_reset(datetime.now(UTC)))
        return ModelsUnavailable()
    # Cadeia de um só modelo: erros elegíveis a fallback chegam isolados (sem grupo). UnexpectedModelBehavior
    # fica de fora porque, fora do `Model.request`, também sinaliza retries esgotados do agente (502).
    if isinstance(exc, Exception) and not isinstance(exc, UnexpectedModelBehavior) and should_fallback(exc):
        return ModelsUnavailable()
    return None


def build_model(settings: Settings, http_client: httpx.AsyncClient | None = None) -> Model:
    api_key = settings.openrouter_api_key.get_secret_value()
    models = [
        OpenAIChatModel(
            name,
            provider=OpenAIProvider(
                openai_client=AsyncOpenAI(
                    base_url=settings.openrouter_base_url,
                    api_key=api_key,
                    max_retries=0,
                    timeout=MODEL_TIMEOUT_S,
                    http_client=http_client,
                )
            ),
        )
        for name in settings.llm_models
    ]
    if len(models) == 1:
        return models[0]
    return FallbackModel(*models, fallback_on=should_fallback)


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _parse_quota(payload: object) -> QuotaInfo:
    if not isinstance(payload, dict):
        return QuotaInfo()
    data = payload.get("data")
    source = data if isinstance(data, dict) else payload
    quota = source.get("free_model_daily_requests")
    if not isinstance(quota, dict):
        return QuotaInfo()
    return QuotaInfo(
        used=_as_int(quota.get("used")),
        limit=_as_int(quota.get("limit")),
        remaining=_as_int(quota.get("remaining")),
    )


async def get_quota(settings: Settings, client: httpx.AsyncClient | None = None) -> QuotaInfo:
    owns_client = client is None
    http_client = client if client is not None else httpx.AsyncClient(timeout=QUOTA_TIMEOUT_S)
    try:
        response = await http_client.get(
            f"{settings.openrouter_base_url.rstrip('/')}{_KEY_ENDPOINT}",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key.get_secret_value()}"},
        )
        response.raise_for_status()
        return _parse_quota(response.json())
    finally:
        if owns_client:
            await http_client.aclose()
