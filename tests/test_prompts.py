"""Testes do contexto semântico do agente: sem rede."""

import hashlib
import re
import sqlite3

from app.agent.prompts import (
    GENRE_TRANSLATIONS,
    PROMPT_VERSION,
    STATUS_VALUES,
    TABLE_DOCS,
    build_system_prompt,
)
from tests.conftest import GOLD_TABLES, SCHEMA_SQL

GENRES_EN = {
    "Action",
    "Adventure",
    "Animation",
    "Comedy",
    "Crime",
    "Documentary",
    "Drama",
    "Family",
    "Fantasy",
    "History",
    "Horror",
    "Music",
    "Mystery",
    "Romance",
    "Science Fiction",
    "Thriller",
    "Tv Movie",
    "War",
    "Western",
}

STATUSES = {"Lançado", "Em Produção", "Planejado", "Pós-Produção"}


def _schema_columns() -> dict[str, list[str]]:
    """Lê o DDL de referência num SQLite em memória: tabela → colunas na ordem do DDL."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'")
        ]
        return {table: [row[1] for row in conn.execute(f"PRAGMA table_info({table})")] for table in tables}
    finally:
        conn.close()


def test_table_docs_have_exactly_the_gold_tables() -> None:
    schema = _schema_columns()
    names = [table.name for table in TABLE_DOCS]
    assert len(names) == len(set(names)) == 10
    assert set(names) == set(schema) == set(GOLD_TABLES)


def test_table_docs_columns_match_ddl_order() -> None:
    schema = _schema_columns()
    for table in TABLE_DOCS:
        assert [column.name for column in table.columns] == schema[table.name], table.name


def test_table_docs_columns_are_documented() -> None:
    for table in TABLE_DOCS:
        assert table.description.strip()
        for column in table.columns:
            assert column.type.strip() and column.description.strip(), f"{table.name}.{column.name}"


def test_prompt_cites_every_table_and_column() -> None:
    prompt = build_system_prompt()
    for table in TABLE_DOCS:
        assert table.name in prompt
        for column in table.columns:
            assert column.name in prompt, f"{table.name}.{column.name}"


def test_prompt_does_not_offer_internal_tables() -> None:
    prompt = build_system_prompt()
    assert "alembic_version" not in prompt
    assert "sqlite_master" not in prompt


def test_prompt_contains_all_genres_and_statuses() -> None:
    prompt = build_system_prompt()
    assert {en for _, en in GENRE_TRANSLATIONS} == GENRES_EN
    for pt, en in GENRE_TRANSLATIONS:
        assert f"{pt}={en}" in prompt
    assert set(STATUS_VALUES) == STATUSES
    for status in STATUSES:
        assert f"'{status}'" in prompt


def test_prompt_is_deterministic_and_versioned() -> None:
    prompt = build_system_prompt()
    assert prompt == build_system_prompt()
    assert re.fullmatch(r"[0-9a-f]{12}", PROMPT_VERSION)
    digest = hashlib.sha256(prompt.encode()).hexdigest()[:12]
    assert digest == PROMPT_VERSION
