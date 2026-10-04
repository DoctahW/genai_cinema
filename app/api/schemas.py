from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

from app.agent.prompts import TableDoc
from app.agent.service import AskResult

EXAMPLE_QUESTIONS: list[str] = [
    "Top 10 filmes com maior receita em R$",
    "Lucro médio por gênero, considerando apenas filmes com receita informada",
    "Filmes com maior margem de lucro, entre os que possuem receita e orçamento informados",
    "Os 5 filmes mais populares",
    "Filmes com maior divergência entre a nota TMDB e a nota IMDb",
    "Nota média IMDb por ano de lançamento",
    "Ator com mais participações em filmes lançados nos últimos 5 anos",
    "Diretores com maior nota média (mínimo de 5 filmes)",
    "Dupla ator–diretor que mais trabalhou junta",
    "Quantidade de filmes por gênero",
    "Produtora com maior lucro total",
    "Gênero com maior margem de lucro média",
    "Filmes mais avaliados pelos usuários",
    "Filmes em que a nota média dos usuários mais diverge da nota IMDb",
]
"""As 14 perguntas do enunciado; viram os exemplos do Swagger."""


class AskRequest(BaseModel):
    """Pergunta em linguagem natural sobre o catálogo de filmes."""

    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)] = Field(
        description="Pergunta em português do Brasil (3 a 500 caracteres, após remover espaços das pontas).",
        examples=EXAMPLE_QUESTIONS,
    )


class AskResponse(AskResult):
    """Resposta de `POST /api/v1/ask`; mesmos campos do resultado do serviço."""


class SqlRequest(BaseModel):
    """Consulta SQL para execução direta, sem LLM (depuração e avaliação)."""

    sql: str = Field(
        min_length=1,
        max_length=5000,
        description="Uma instrução SELECT sobre as 10 tabelas da camada Gold.",
        examples=["SELECT titulo FROM dim_movies LIMIT 3"],
    )


class SqlResponse(BaseModel):
    """Resultado da execução direta de SQL."""

    sql: str = Field(description="SQL efetivamente executado, com LIMIT imposto quando faltava.")
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool


class SchemaResponse(BaseModel):
    """Tabelas da camada Gold com colunas e descrições."""

    tables: list[TableDoc]


class QuotaResponse(BaseModel):
    """Cota diária de modelos gratuitos do OpenRouter."""

    used: int | None = None
    limit: int | None = None
    remaining: int | None = None
    reset_at_brt: str = "21:00"


class HealthResponse(BaseModel):
    """Estado da aplicação: banco acessível, configuração carregada e modelos da cadeia."""

    status: str
    database: str
    models: list[str]


class ErrorResponse(BaseModel):
    """Corpo uniforme de erro da API."""

    error: str = Field(description="Identificador do erro (nome da exceção de domínio).")
    detail: str = Field(description="Mensagem amigável em português do Brasil.")
