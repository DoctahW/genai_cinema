"""Cria os índices auxiliares da camada Gold e roda ANALYZE (SPEC-02).

Uso: `uv run python scripts/prepare_db.py [--db data/cinerocket.db]`.
Não altera dados; abre o banco em modo escrita apenas para criar índices.
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import quote

DEFAULT_DB_PATH = Path("data/cinerocket.db")

INDEX_STATEMENTS: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_dim_people_tipo_id_nome ON dim_people(tipo_pessoa, sk_person_id, nome_pessoa)",
    "CREATE INDEX IF NOT EXISTS ix_bridge_movie_person_person_movie ON bridge_movie_person(sk_person_id, sk_movie_id)",
)


def prepare_database(db_path: Path) -> float:
    """Cria os índices (idempotente) e roda ANALYZE. Devolve o tempo decorrido em segundos."""
    if not db_path.is_file():
        raise FileNotFoundError(
            f"banco não encontrado em '{db_path}'. Baixe o cinerocket.db para data/cinerocket.db "
            "ou informe outro caminho com --db."
        )

    absolute = quote(db_path.resolve().as_posix(), safe="/")
    started = time.monotonic()
    conn = sqlite3.connect(f"file:{absolute}?mode=rw", uri=True)
    try:
        for statement in INDEX_STATEMENTS:
            conn.execute(statement)
            print(f"ok: {statement}")
        conn.execute("ANALYZE")
        print("ok: ANALYZE")
        conn.commit()
    finally:
        conn.close()
    elapsed = time.monotonic() - started
    print(f"Banco preparado em {elapsed:.2f}s ({db_path})")
    return elapsed


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada da CLI."""
    parser = argparse.ArgumentParser(description="Cria índices auxiliares e roda ANALYZE no banco Gold.")
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, help="caminho do banco SQLite (padrão: %(default)s)"
    )
    args = parser.parse_args(argv)
    try:
        prepare_database(args.db)
    except (FileNotFoundError, sqlite3.Error) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
