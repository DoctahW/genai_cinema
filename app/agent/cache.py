import hashlib
import json
import sqlite3
import time
import unicodedata
from collections.abc import Callable, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

_DDL = "CREATE TABLE IF NOT EXISTS answers (key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at REAL NOT NULL)"


def normalize_question(question: str) -> str:
    """Remove acentos (NFKD sem marcas combinantes), aplica `casefold` e colapsa espaços."""
    decomposed = unicodedata.normalize("NFKD", question)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_marks.casefold().split())


def cache_key(question: str, models: Sequence[str], prompt_version: str) -> str:
    """Deriva a chave sha256 de (pergunta normalizada, modelos na ordem, versão do prompt)."""
    serialized = json.dumps(
        [normalize_question(question), list(models), prompt_version],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class AnswerCache:
    def __init__(self, path: Path | str, ttl_s: float, *, clock: Callable[[], float] = time.time) -> None:
        self._path = Path(path)
        self._ttl_s = ttl_s
        self._clock = clock
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as conn:
            conn.execute(_DDL)
            conn.commit()

    def get(self, key: str) -> dict[str, Any] | None:
        if self._ttl_s == 0:
            return None
        with closing(sqlite3.connect(self._path)) as conn:
            row = conn.execute("SELECT payload, created_at FROM answers WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        payload, created_at = row
        if created_at + self._ttl_s <= self._clock():
            return None
        return json.loads(payload)

    def set(self, key: str, payload: dict[str, Any]) -> None:
        if self._ttl_s == 0:
            return
        encoded = json.dumps(payload, ensure_ascii=False)
        with closing(sqlite3.connect(self._path)) as conn:
            conn.execute(
                "INSERT INTO answers (key, payload, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET payload = excluded.payload, created_at = excluded.created_at",
                (key, encoded, self._clock()),
            )
            conn.commit()
