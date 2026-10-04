"""Fixtures compartilhadas: banco Gold mínimo (mesmo DDL do cinerocket.db) e Settings de teste."""

import sqlite3
from pathlib import Path

import pytest

from app.config import Settings

SCHEMA_SQL = Path(__file__).parent / "fixtures" / "schema.sql"

GOLD_TABLES = frozenset(
    {
        "dim_movies",
        "fact_movies_performance",
        "dim_genres",
        "dim_people",
        "dim_companies",
        "dim_reviews",
        "movie_reviews",
        "bridge_movie_genre",
        "bridge_movie_person",
        "bridge_movie_company",
    }
)

# (sk_movie_id, titulo, ano, status, orcamento_usd, receita_usd, lucro_usd, orcamento_brl, receita_brl,
#  lucro_brl, popularidade, nota_tmdb, qtd_tmdb, nota_imdb, qtd_imdb)
_MOVIES = [
    ("m1", "Filme Lucrativo", 2020, "Lançado", 100.0, 400.0, 300.0, 500.0, 2000.0, 1500.0, 90.5, 8.0, 1000, 7.5, 5000),
    ("m2", "Filme Prejuízo", 2021, "Lançado", 200.0, 100.0, -100.0, 1000.0, 500.0, -500.0, 50.0, 6.0, 300, 6.5, 800),
    ("m3", "Sem Receita", 2022, "Lançado", 300.0, None, -300.0, 1500.0, None, -1500.0, 70.0, 0.0, 0, None, None),
    ("m4", "Futuro", 2028, "Planejado", None, None, 0.0, None, None, 0.0, 10.0, 0.0, 0, None, None),
]


def _seed(conn: sqlite3.Connection) -> None:
    for sk, titulo, ano, status, *fact in _MOVIES:
        conn.execute(
            "INSERT INTO dim_movies (sk_movie_id, id_filme, titulo, ano_lancamento, status_filme, sinopse) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sk, f"id-{sk}", titulo, ano, status, f"Sinopse de {titulo}"),
        )
        conn.execute("INSERT INTO fact_movies_performance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (sk, *fact))
    conn.executemany(
        "INSERT INTO dim_genres VALUES (?, ?)", [("g1", "Action"), ("g2", "Drama"), ("g3", "Science Fiction")]
    )
    conn.executemany(
        "INSERT INTO bridge_movie_genre VALUES (?, ?)",
        [("m1", "g1"), ("m1", "g3"), ("m2", "g2"), ("m3", "g1"), ("m4", "g2")],
    )
    conn.executemany("INSERT INTO dim_companies VALUES (?, ?)", [("c1", "Rocket Films"), ("c2", "Cine Sul")])
    conn.executemany("INSERT INTO bridge_movie_company VALUES (?, ?)", [("m1", "c1"), ("m2", "c2"), ("m3", "c1")])
    # "Ana Lima" é Atriz e Diretora: duas linhas em dim_people, ids diferentes.
    conn.executemany(
        "INSERT INTO dim_people VALUES (?, ?, ?)",
        [
            ("p1", "Ana Lima", "Ator"),
            ("p2", "Ana Lima", "Diretor"),
            ("p3", "Bruno Reis", "Ator"),
            ("p4", "Carla Dias", "Diretor"),
        ],
    )
    conn.executemany(
        "INSERT INTO bridge_movie_person VALUES (?, ?)",
        [("m1", "p1"), ("m1", "p2"), ("m1", "p3"), ("m1", "p4"), ("m2", "p3"), ("m2", "p4"), ("m3", "p1")],
    )
    conn.executemany("INSERT INTO dim_reviews VALUES (?, ?, ?, ?)", [("r1", "m1", 13, 8.2), ("r2", "m2", 2, 4.0)])
    conn.executemany(
        "INSERT INTO movie_reviews (id, sk_movie_review_id, sk_movie_id, name, rating, text) VALUES (?, ?, ?, ?, ?, ?)",
        [(1, "mr1", "m1", "joao", 9.0, "Ótimo"), (2, "mr2", "m2", "maria", 4.0, "Fraco")],
    )
    conn.execute("INSERT INTO alembic_version VALUES ('head')")


@pytest.fixture
def mini_db_path(tmp_path: Path) -> Path:
    """Arquivo SQLite com o DDL real da camada Gold e poucas linhas de dados."""
    path = tmp_path / "mini.db"
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
        _seed(conn)
        conn.commit()
    finally:
        conn.close()
    return path


@pytest.fixture
def settings(mini_db_path: Path, tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        openrouter_api_key="test-key",
        openrouter_base_url="https://openrouter.test/api/v1",
        llm_models=["primary/model:free", "secondary/model:free"],
        db_path=mini_db_path,
        sql_timeout_s=2,
        sql_max_rows=5,
        agent_request_limit=4,
        cache_path=tmp_path / "cache" / "answers.db",
        cache_ttl_s=3600,
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
