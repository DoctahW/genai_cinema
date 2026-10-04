"""Testes do guardrail SQL."""

import pytest

from app.db.connection import execute_query
from app.db.guardrails import SQLValidationError, validate_sql

VALID_SQL = [
    "SELECT titulo FROM dim_movies",
    (
        "SELECT m.titulo, g.nome_genero FROM dim_movies AS m "
        "JOIN bridge_movie_genre AS bg ON bg.sk_movie_id = m.sk_movie_id "
        "JOIN dim_genres AS g ON g.sk_genre_id = bg.sk_genre_id"
    ),
    "WITH c AS (SELECT sk_movie_id FROM dim_movies) SELECT * FROM c",
    "SELECT sk_movie_id FROM dim_movies UNION SELECT sk_movie_id FROM bridge_movie_genre",
    "SELECT * FROM (SELECT titulo FROM dim_movies) AS t",
    "SELECT titulo FROM dim_movies LIMIT 1",
    "SELECT titulo FROM dim_movies LIMIT 1; -- fim",
    "SELECT TITULO FROM DIM_MOVIES",
]

INVALID_SQL = [
    "INSERT INTO dim_genres VALUES ('g9', 'X')",
    "UPDATE dim_movies SET titulo = 'x'",
    "DELETE FROM dim_movies",
    "DROP TABLE dim_movies",
    "CREATE TABLE x (y INTEGER)",
    "ALTER TABLE dim_movies ADD COLUMN z INTEGER",
    "PRAGMA table_info(dim_movies)",
    "ATTACH DATABASE ':memory:' AS aux",
    "SELECT 1; SELECT 2",
    "SELECT 1; -- x\nDROP TABLE dim_movies",
    "SELECT 1 /* a */; DELETE FROM dim_movies",
    "SELECT * FROM users",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM sqlite_temp_master",
    "SELECT * FROM alembic_version",
    "SELECT * FROM pragma_table_info('dim_movies')",
    "SELECT * FROM main.dim_movies",
    "SELECT * FROM other.dim_movies",
    "WITH c AS (SELECT * FROM sqlite_master) SELECT * FROM c",
    "SELECT * FROM dim_movies WHERE titulo IN (SELECT name FROM sqlite_master)",
    "REPLACE INTO dim_genres VALUES (1, 2)",
    "VACUUM",
    'SELECT * FROM json_each("[1]")',
    "",
    "   ",
    "SELECT FROM WHERE",
    "EXPLAIN SELECT 1",
]


@pytest.mark.parametrize("sql", VALID_SQL)
def test_valid_sql_is_accepted_and_runs(sql: str, mini_db_path) -> None:
    safe_sql = validate_sql(sql, max_rows=5)

    assert safe_sql.strip()

    result = execute_query(mini_db_path, safe_sql, timeout_s=2, max_rows=5)
    assert result.columns
    assert result.row_count == len(result.rows)


@pytest.mark.parametrize("sql", INVALID_SQL)
def test_invalid_sql_is_rejected(sql: str) -> None:
    with pytest.raises(SQLValidationError) as excinfo:
        validate_sql(sql, max_rows=5)
    assert str(excinfo.value).strip()


def test_limit_is_imposed_when_absent(mini_db_path) -> None:
    safe_sql = validate_sql("SELECT sk_movie_id FROM dim_movies", max_rows=2)

    assert "limit" in safe_sql.lower()

    result = execute_query(mini_db_path, safe_sql, timeout_s=2, max_rows=2)
    # dim_movies tem 4 linhas; row_count == 2 prova que o LIMIT imposto foi aplicado.
    assert result.row_count == 2


def test_order_by_is_preserved_with_imposed_limit(mini_db_path) -> None:
    safe_sql = validate_sql("SELECT titulo, ano_lancamento FROM dim_movies ORDER BY ano_lancamento DESC", max_rows=2)

    result = execute_query(mini_db_path, safe_sql, timeout_s=2, max_rows=2)
    # O LIMIT no mesmo nível da raiz garante o top-2 do ORDER BY DESC.
    assert [row[1] for row in result.rows] == [2028, 2022]


def test_existing_limit_is_kept(mini_db_path) -> None:
    safe_sql = validate_sql("SELECT titulo FROM dim_movies LIMIT 1", max_rows=5)

    assert "limit 1" in safe_sql.lower()
    assert "limit 5" not in safe_sql.lower()

    result = execute_query(mini_db_path, safe_sql, timeout_s=2, max_rows=5)
    assert result.row_count == 1


def test_cte_and_union_get_limit_and_run(mini_db_path) -> None:
    for sql in (
        "WITH c AS (SELECT sk_movie_id FROM dim_movies) SELECT * FROM c",
        "SELECT sk_movie_id FROM dim_movies UNION SELECT sk_movie_id FROM bridge_movie_genre",
    ):
        safe_sql = validate_sql(sql, max_rows=1)
        assert "limit" in safe_sql.lower()
        result = execute_query(mini_db_path, safe_sql, timeout_s=2, max_rows=1)
        assert result.row_count == 1
