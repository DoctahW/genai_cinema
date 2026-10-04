"""Fluxo seguro de consulta (SPEC-02/SPEC-03): valida, executa e devolve o SQL usado."""

from app.config import Settings
from app.db.connection import QueryResult, execute_query
from app.db.guardrails import validate_sql


def run_safe_query(sql: str, settings: Settings) -> tuple[str, QueryResult]:
    """Valida `sql` no guardrail e o executa em modo somente leitura; devolve `(sql_usado, resultado)`."""
    safe_sql = validate_sql(sql, max_rows=settings.sql_max_rows)
    result = execute_query(
        settings.db_path,
        safe_sql,
        timeout_s=settings.sql_timeout_s,
        max_rows=settings.sql_max_rows,
    )
    return safe_sql, result
