"""Testes do script de preparo do banco."""

import sqlite3

import pytest

from scripts.prepare_db import prepare_database

EXPECTED_INDEXES = {"ix_dim_people_tipo_id_nome", "ix_bridge_movie_person_person_movie"}


def _index_names(db_path) -> set[str]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    finally:
        conn.close()


def _counts(db_path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("dim_people", "bridge_movie_person", "dim_movies")
        }
    finally:
        conn.close()


def test_prepare_is_idempotent_and_keeps_data(mini_db_path) -> None:
    before = _counts(mini_db_path)

    prepare_database(mini_db_path)
    assert EXPECTED_INDEXES.issubset(_index_names(mini_db_path))

    prepare_database(mini_db_path)
    assert EXPECTED_INDEXES.issubset(_index_names(mini_db_path))
    assert _counts(mini_db_path) == before


def test_missing_db_raises_and_does_not_create(tmp_path) -> None:
    missing = tmp_path / "nope.db"

    with pytest.raises(FileNotFoundError):
        prepare_database(missing)

    assert not missing.exists()
