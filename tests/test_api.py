"""Testes das rotas da API: sem rede, sem LLM real, serviço substituído.

O `TestClient` roda o lifespan de verdade (banco mini, cache em tmp); apenas o
`AskService` e o fetcher de cota são trocados via `dependency_overrides`.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded

from app.agent.llm import ModelsUnavailable, QuotaExceeded, QuotaInfo
from app.agent.service import AskResult
from app.api.routes import get_ask_service, get_quota_fetcher
from app.config import ConfigError, Settings
from app.db.connection import QueryTimeout
from app.db.guardrails import SQLValidationError
from app.main import create_app
from tests.conftest import GOLD_TABLES


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _ask_result() -> AskResult:
    return AskResult(
        answer="A receita total é R$ 2.000,00.",
        sql="SELECT SUM(receita_brl) AS total FROM fact_movies_performance LIMIT 5",
        columns=["total"],
        rows=[[2000.0]],
        row_count=1,
        truncated=False,
        assumptions=["Considerei apenas filmes com receita informada."],
        model_used="primary/model:free",
        cached=False,
        latency_ms=42.0,
        llm_calls=2,
    )


class _FakeService:
    """Serviço de perguntas falso: devolve um resultado fixo ou levanta um erro planejado."""

    def __init__(self, *, result: AskResult | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.questions: list[str] = []

    async def ask(self, question: str) -> AskResult:
        self.questions.append(question)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def test_ask_returns_full_response(client: TestClient) -> None:
    service = _FakeService(result=_ask_result())
    client.app.dependency_overrides[get_ask_service] = lambda: service

    response = client.post("/api/v1/ask", json={"question": "  Top 10 filmes com maior receita em R$  "})

    assert response.status_code == 200
    assert response.json() == _ask_result().model_dump()
    assert service.questions == ["Top 10 filmes com maior receita em R$"]


@pytest.mark.parametrize("question", ["ab", "x" * 501, "   "])
def test_ask_rejects_invalid_question(client: TestClient, question: str) -> None:
    response = client.post("/api/v1/ask", json={"question": question})
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("error", "status"),
    [
        pytest.param(SQLValidationError("tabela fora da lista"), 400, id="sql-validation"),
        pytest.param(QueryTimeout("Consulta excedeu o tempo limite de 2 s."), 504, id="query-timeout"),
        pytest.param(QuotaExceeded(datetime.now(UTC) + timedelta(hours=3)), 429, id="quota"),
        pytest.param(UsageLimitExceeded("limite"), 422, id="usage-limit"),
        pytest.param(UnexpectedModelBehavior("resposta inesperada"), 502, id="unexpected-model"),
        pytest.param(ModelsUnavailable(), 503, id="models-unavailable"),
        pytest.param(ModelHTTPError(401, "primary/model:free", {"error": {"code": 401}}), 502, id="provider-auth"),
    ],
)
def test_ask_error_mapping(client: TestClient, error: Exception, status: int) -> None:
    client.app.dependency_overrides[get_ask_service] = lambda: _FakeService(error=error)

    response = client.post("/api/v1/ask", json={"question": "Quais filmes existem?"})

    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error", "detail"}
    assert body["error"] == type(error).__name__
    assert body["detail"]
    if status == 429:
        assert int(response.headers["retry-after"]) > 0


def test_sql_runs_select(client: TestClient) -> None:
    response = client.post("/api/v1/sql", json={"sql": "SELECT titulo FROM dim_movies ORDER BY sk_movie_id"})

    assert response.status_code == 200
    body = response.json()
    assert body["columns"] == ["titulo"]
    assert body["rows"] == [["Filme Lucrativo"], ["Filme Prejuízo"], ["Sem Receita"], ["Futuro"]]
    assert body["row_count"] == 4
    assert body["truncated"] is False


def test_sql_marks_truncation(client: TestClient) -> None:
    sql = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 20) SELECT x FROM c LIMIT 50"

    body = client.post("/api/v1/sql", json={"sql": sql}).json()

    assert body["row_count"] == 5
    assert body["truncated"] is True
    assert "LIMIT 50" in body["sql"]


@pytest.mark.parametrize("sql", ["SELECT * FROM usuarios", "DELETE FROM dim_movies"])
def test_sql_rejects_invalid_and_dml(client: TestClient, sql: str) -> None:
    response = client.post("/api/v1/sql", json={"sql": sql})

    assert response.status_code == 400
    assert response.json()["error"] == "SQLValidationError"


def test_schema_lists_gold_tables(client: TestClient) -> None:
    body = client.get("/api/v1/schema").json()

    assert {table["name"] for table in body["tables"]} == set(GOLD_TABLES)
    assert len(body["tables"]) == 10
    assert all(table["columns"] for table in body["tables"])


def test_quota_passes_through_fetcher(client: TestClient) -> None:
    async def fetcher(settings: Settings) -> QuotaInfo:
        return QuotaInfo(used=12, limit=50, remaining=38)

    client.app.dependency_overrides[get_quota_fetcher] = lambda: fetcher

    response = client.get("/api/v1/quota")

    assert response.status_code == 200
    assert response.json() == {"used": 12, "limit": 50, "remaining": 38, "reset_at_brt": "21:00"}


def test_quota_failure_returns_502(client: TestClient) -> None:
    async def fetcher(settings: Settings) -> QuotaInfo:
        raise httpx.ConnectError("sem rede")

    client.app.dependency_overrides[get_quota_fetcher] = lambda: fetcher

    response = client.get("/api/v1/quota")

    assert response.status_code == 502
    body = response.json()
    assert set(body) == {"error", "detail"}
    assert body["error"] == "QuotaUnavailable"


def test_health_ok_then_503_after_db_removed(client: TestClient, mini_db_path: Path) -> None:
    ok = client.get("/health")
    assert ok.status_code == 200
    assert ok.json()["status"] == "ok"
    assert ok.json()["database"] == "ok"
    assert ok.json()["models"] == ["primary/model:free", "secondary/model:free"]

    mini_db_path.unlink()
    down = client.get("/health")

    assert down.status_code == 503
    assert down.json()["status"] == "error"


def test_startup_fails_when_db_missing(settings: Settings, tmp_path: Path) -> None:
    broken = settings.model_copy(update={"db_path": tmp_path / "ausente.db"})

    with pytest.raises(ConfigError, match="Banco de dados inacessível"), TestClient(create_app(broken)):
        pass


def test_docs_and_openapi_expose_examples(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200

    spec = client.get("/openapi.json").json()
    blob = json.dumps(spec, ensure_ascii=False)

    assert "Top 10 filmes com maior receita em R$" in blob
    assert "/api/v1/ask" in spec["paths"]
    assert "/health" in spec["paths"]
    assert "/api/v1/sql" in spec["paths"]
