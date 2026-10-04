"""Testes do acesso somente leitura e do timeout."""

import sqlite3
import time

import pytest

from app.db.connection import QueryResult, QueryTimeout, check_database, connect_readonly, execute_query
from app.db.guardrails import SQLValidationError
from app.db.query import run_safe_query

HEAVY_SQL = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT count(*) FROM c"
WRITE_SQL = [
    "INSERT INTO dim_genres VALUES ('g9', 'X')",
    "UPDATE dim_movies SET titulo = 'x'",
    "DELETE FROM dim_movies",
    "CREATE TABLE x (y INTEGER)",
]


def _counts(db_path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("dim_movies", "dim_genres", "bridge_movie_person")
        }
    finally:
        conn.close()


@pytest.mark.parametrize("sql", WRITE_SQL)
def test_writes_fail_even_without_guardrail(sql: str, mini_db_path) -> None:
    before = _counts(mini_db_path)

    with pytest.raises(sqlite3.Error):
        execute_query(mini_db_path, sql, timeout_s=2, max_rows=5)

    assert _counts(mini_db_path) == before


def test_attach_is_rejected(mini_db_path) -> None:
    with pytest.raises(sqlite3.Error):
        execute_query(mini_db_path, "ATTACH DATABASE ':memory:' AS aux", timeout_s=2, max_rows=5)


def test_heavy_query_raises_query_timeout(mini_db_path) -> None:
    started = time.monotonic()
    with pytest.raises(QueryTimeout) as excinfo:
        execute_query(mini_db_path, HEAVY_SQL, timeout_s=0.3, max_rows=5)
    elapsed = time.monotonic() - started

    assert elapsed < 2
    assert "0.3" in str(excinfo.value)


def test_truncated_is_true_at_limit(mini_db_path) -> None:
    result = execute_query(mini_db_path, "SELECT sk_movie_id FROM dim_movies", timeout_s=2, max_rows=3)

    assert isinstance(result, QueryResult)
    assert result.row_count == 3
    assert len(result.rows) == 3
    assert result.truncated


def test_truncated_is_false_below_limit(mini_db_path) -> None:
    result = execute_query(mini_db_path, "SELECT sk_movie_id FROM dim_movies", timeout_s=2, max_rows=5)

    assert result.row_count == 4
    assert not result.truncated


def test_connect_readonly_handles_special_path(tmp_path) -> None:
    weird_dir = tmp_path / "com espaço#e?x"
    weird_dir.mkdir()
    db_path = weird_dir / "m.db"
    writer = sqlite3.connect(db_path)
    try:
        writer.execute("CREATE TABLE t (x INTEGER)")
        writer.execute("INSERT INTO t VALUES (1)")
        writer.commit()
    finally:
        writer.close()

    conn = connect_readonly(db_path)
    try:
        assert conn.execute("SELECT x FROM t").fetchone() == (1,)
        with pytest.raises(sqlite3.Error):
            conn.execute("INSERT INTO t VALUES (2)")
    finally:
        conn.close()


def test_check_database_ok(mini_db_path) -> None:
    check_database(mini_db_path)


def test_check_database_missing_file(tmp_path) -> None:
    with pytest.raises(sqlite3.Error):
        check_database(tmp_path / "nope.db")


def test_run_safe_query_rejects_invalid_sql(settings) -> None:
    with pytest.raises(SQLValidationError):
        run_safe_query("DROP TABLE dim_movies", settings)


def test_run_safe_query_imposes_limit_and_executes(settings) -> None:
    safe_sql, result = run_safe_query("SELECT titulo FROM dim_movies ORDER BY titulo", settings)

    assert "limit" in safe_sql.lower()
    assert result.row_count <= settings.sql_max_rows


def test_run_safe_query_marks_truncation_when_limit_was_imposed(settings) -> None:
    # Sem LIMIT do usuário, o guardrail impõe max_rows + 1: o corte precisa aparecer em `truncated`.
    limited = settings.model_copy(update={"sql_max_rows": 2})

    _, result = run_safe_query("SELECT titulo FROM dim_movies ORDER BY titulo", limited)

    assert result.row_count == 2
    assert result.truncated is True
