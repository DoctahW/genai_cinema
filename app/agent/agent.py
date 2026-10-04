import asyncio
import sqlite3
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, AgentRunResult, ModelRetry, RunContext, UsageLimits
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model

from app.agent.llm import classify_llm_error
from app.agent.prompts import build_system_prompt
from app.config import Settings
from app.db.connection import QueryResult, QueryTimeout
from app.db.guardrails import SQLValidationError
from app.db.query import run_safe_query

MAX_ROWS_TO_MODEL = 50

TOOL_RETRIES = 10
# Tentativas da ferramenta; o teto efetivo de chamadas é `UsageLimits.request_limit`.


@dataclass
class Deps:
    """Dependências da execução: configuração e último resultado observado."""

    settings: Settings
    last_sql: str | None = None
    last_result: QueryResult | None = None


class AgentAnswer(BaseModel):

    answer: str = Field(
        description="Resposta à pergunta do usuário, em português do Brasil, citando os números vindos da consulta."
    )
    sql: str | None = Field(
        default=None,
        description="Consulta SQL executada para embasar a resposta; nulo quando nenhuma consulta foi necessária.",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Premissas e escolhas de interpretação adotadas, em português do Brasil; vazio se não houver.",
    )


@dataclass
class AskOutcome:
    """Resultado consolidado de uma pergunta: resposta, SQL executado e uso de modelos."""

    answer: AgentAnswer
    sql: str | None
    result: QueryResult | None
    model_used: str | None
    llm_calls: int


def build_agent(model: Model) -> Agent[Deps, AgentAnswer]:
    agent: Agent[Deps, AgentAnswer] = Agent(
        model,
        deps_type=Deps,
        output_type=AgentAnswer,
        system_prompt=build_system_prompt(),
    )

    # sequential: chamadas paralelas da ferramenta disputariam `ctx.deps.last_*`.
    @agent.tool(retries=TOOL_RETRIES, sequential=True)
    async def run_sql(ctx: RunContext[Deps], sql: str) -> dict[str, Any]:
        try:
            safe_sql, result = await asyncio.to_thread(run_safe_query, sql, ctx.deps.settings)
        except SQLValidationError as exc:
            raise ModelRetry(str(exc)) from exc
        except QueryTimeout as exc:
            raise ModelRetry(f"{exc} Reformule com uma consulta mais simples ou com mais filtros.") from exc
        except sqlite3.Error as exc:
            raise ModelRetry(f"Erro do SQLite ao executar a consulta: {exc}") from exc

        ctx.deps.last_sql = safe_sql
        ctx.deps.last_result = result
        return {
            "columns": result.columns,
            "rows": result.rows[:MAX_ROWS_TO_MODEL],
            "row_count": result.row_count,
            "truncated": result.truncated,
            "rows_omitted_for_model": max(0, result.row_count - MAX_ROWS_TO_MODEL),
        }

    return agent


async def ask(agent: Agent[Deps, AgentAnswer], question: str, settings: Settings) -> AskOutcome:
    """Pergunta ao agente e consolida a resposta com o SQL e o resultado efetivamente executados."""
    deps = Deps(settings)
    try:
        result = await agent.run(
            question,
            deps=deps,
            usage_limits=UsageLimits(request_limit=settings.agent_request_limit),
        )
    except Exception as exc:
        classified = classify_llm_error(exc)
        if classified is not None:
            raise classified from exc
        raise

    return AskOutcome(
        answer=result.output,
        sql=deps.last_sql,
        result=deps.last_result,
        model_used=_model_used(result),
        llm_calls=result.usage.requests,
    )


def _model_used(result: AgentRunResult[AgentAnswer]) -> str | None:
    for message in reversed(result.all_messages()):
        if isinstance(message, ModelResponse) and message.model_name:
            return message.model_name
    return None
