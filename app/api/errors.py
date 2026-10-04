import math
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded

from app.agent.llm import ModelsUnavailable, QuotaExceeded
from app.db.connection import QueryTimeout
from app.db.guardrails import SQLValidationError

_USAGE_LIMIT_DETAIL = "A pergunta exigiu chamadas demais ao modelo; reformule de forma mais específica."
_UNEXPECTED_DETAIL = "O modelo devolveu uma resposta inesperada; tente reformular a pergunta."
_AUTH_DETAIL = "O OpenRouter recusou a chave (HTTP {status}); confira OPENROUTER_API_KEY no .env."
_PROVIDER_DETAIL = "Falha ao chamar o modelo no OpenRouter (HTTP {status})."


def register_exception_handlers(app: FastAPI) -> None:
    """Mapeia as exceções de domínio para HTTP com o mesmo formato de erro."""
    app.add_exception_handler(SQLValidationError, _validation)
    app.add_exception_handler(QueryTimeout, _timeout)
    app.add_exception_handler(QuotaExceeded, _quota)
    app.add_exception_handler(UsageLimitExceeded, _usage_limit)
    app.add_exception_handler(UnexpectedModelBehavior, _unexpected)
    app.add_exception_handler(ModelsUnavailable, _models_unavailable)
    # Depois de QuotaExceeded/ModelsUnavailable (já traduzidos no agente): sobra erro do provedor, ex. 401/402/400.
    app.add_exception_handler(ModelAPIError, _provider_error)


def _payload(exc: Exception, detail: str | None = None) -> dict[str, str]:
    return {"error": type(exc).__name__, "detail": detail or str(exc)}


def _validation(_: Request, exc: SQLValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content=_payload(exc))


def _timeout(_: Request, exc: QueryTimeout) -> JSONResponse:
    return JSONResponse(status_code=504, content=_payload(exc))


def _quota(_: Request, exc: QuotaExceeded) -> JSONResponse:
    seconds = max(0, math.ceil((exc.reset_at - datetime.now(UTC)).total_seconds()))
    return JSONResponse(status_code=429, content=_payload(exc), headers={"Retry-After": str(seconds)})


def _usage_limit(_: Request, exc: UsageLimitExceeded) -> JSONResponse:
    return JSONResponse(status_code=422, content=_payload(exc, _USAGE_LIMIT_DETAIL))


def _unexpected(_: Request, exc: UnexpectedModelBehavior) -> JSONResponse:
    return JSONResponse(status_code=502, content=_payload(exc, _UNEXPECTED_DETAIL))


def _models_unavailable(_: Request, exc: ModelsUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content=_payload(exc))


def _provider_error(_: Request, exc: ModelAPIError) -> JSONResponse:
    status = exc.status_code if isinstance(exc, ModelHTTPError) else None
    template = _AUTH_DETAIL if status in {401, 403} else _PROVIDER_DETAIL
    return JSONResponse(status_code=502, content=_payload(exc, template.format(status=status or "-")))
