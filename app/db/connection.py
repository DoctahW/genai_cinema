import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel


class QueryTimeout(Exception):
    """Consulta interrompida por exceder o tempo limite configurado."""


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool


def _readonly_uri(db_path: Path) -> str:
    absolute = quote(db_path.resolve().as_posix(), safe="/")
    return f"file:{absolute}?mode=ro"


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(_readonly_uri(db_path), uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    except Exception:
        conn.close()
        raise
    return conn


def execute_query(db_path: Path, sql: str, *, timeout_s: float, max_rows: int) -> QueryResult:
    """Executa `sql` (sem validar) numa conexão nova e devolve até `max_rows` linhas."""
    deadline = time.monotonic() + timeout_s
    expired = False

    def _on_progress() -> int:
        nonlocal expired
        if time.monotonic() >= deadline:
            expired = True
            return 1
        return 0

    conn = connect_readonly(db_path)
    try:
        conn.set_progress_handler(_on_progress, 1000)
        try:
            cursor = conn.execute(sql)
            fetched = cursor.fetchmany(max_rows + 1)
            columns = [column[0] for column in cursor.description] if cursor.description else []
        except sqlite3.OperationalError as exc:
            if expired:
                raise QueryTimeout(f"Consulta excedeu o tempo limite de {timeout_s:g} s.") from exc
            raise
        rows = [list(row) for row in fetched[:max_rows]]
        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=len(fetched) > max_rows,
        )
    finally:
        conn.close()


def check_database(db_path: Path) -> None:
    conn = connect_readonly(db_path)
    try:
        conn.execute("SELECT 1 FROM dim_movies LIMIT 1").fetchall()
    finally:
        conn.close()
