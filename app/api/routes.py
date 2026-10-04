"""Rotas HTTP da API (SPEC-07).

Cada rota apenas traduz HTTP para as camadas de baixo: `AskService` (cache + agente),
`run_safe_query` (SQL direto, sem LLM) e `get_quota`. As dependências leem
`request.app.state` e podem ser trocadas nos testes com `app.dependency_overrides`.
"""

import sqlite3
from collections.abc import Awaitable, Callable
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.agent.llm import QuotaInfo, get_quota
from app.agent.prompts import TABLE_DOCS
from app.agent.service import AskResult, AskService
from app.api.schemas import (
    AskRequest,
    AskResponse,
    ErrorResponse,
    HealthResponse,
    QuotaResponse,
    SchemaResponse,
    SqlRequest,
    SqlResponse,
)
from app.config import Settings
from app.db.connection import check_database
from app.db.query import run_safe_query

router = APIRouter(prefix="/api/v1")
health_router = APIRouter()

QuotaFetcher = Callable[[Settings], Awaitable[QuotaInfo]]

_ASK_ERRORS = {
    400: {"model": ErrorResponse},
    422: {"model": ErrorResponse, "description": "Validação do request ou limite de chamadas do agente excedido."},
    429: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
    504: {"model": ErrorResponse},
}


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_ask_service(request: Request) -> AskService:
    return request.app.state.ask_service


def get_quota_fetcher() -> QuotaFetcher:
    return get_quota


SettingsDep = Annotated[Settings, Depends(get_settings)]
ServiceDep = Annotated[AskService, Depends(get_ask_service)]
QuotaFetcherDep = Annotated[QuotaFetcher, Depends(get_quota_fetcher)]


@router.post("/ask", response_model=AskResponse, responses=_ASK_ERRORS)
async def ask(payload: AskRequest, service: ServiceDep) -> AskResult:
    return await service.ask(payload.question)


@router.post(
    "/sql",
    response_model=SqlResponse,
    responses={400: {"model": ErrorResponse}, 504: {"model": ErrorResponse}},
)
def execute_sql(payload: SqlRequest, settings: SettingsDep) -> SqlResponse:
    safe_sql, result = run_safe_query(payload.sql, settings)
    return SqlResponse(
        sql=safe_sql,
        columns=result.columns,
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
    )


@router.get("/schema", response_model=SchemaResponse)
def schema() -> SchemaResponse:
    return SchemaResponse(tables=TABLE_DOCS)


@router.get("/quota", response_model=QuotaResponse, responses={502: {"model": ErrorResponse}})
async def quota(settings: SettingsDep, fetcher: QuotaFetcherDep) -> QuotaResponse | JSONResponse:
    try:
        info = await fetcher(settings)
    except httpx.HTTPError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "error": "QuotaUnavailable",
                "detail": f"Não foi possível consultar a cota do OpenRouter: {exc}",
            },
        )
    return QuotaResponse(used=info.used, limit=info.limit, remaining=info.remaining)


@health_router.get(
    "/health",
    responses={200: {"model": HealthResponse}, 503: {"model": HealthResponse}},
    summary="Estado da aplicação",
)
def health(settings: SettingsDep) -> JSONResponse:
    try:
        check_database(settings.db_path)
    except sqlite3.Error as exc:
        body = HealthResponse(status="error", database=str(exc), models=settings.llm_models)
        return JSONResponse(status_code=503, content=body.model_dump())
    body = HealthResponse(status="ok", database="ok", models=settings.llm_models)
    return JSONResponse(status_code=200, content=body.model_dump())
