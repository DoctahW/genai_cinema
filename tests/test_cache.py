"""Testes do cache de respostas, sem rede e sem LLM."""

import sqlite3
from contextlib import closing
from pathlib import Path

from app.agent.cache import AnswerCache, cache_key, normalize_question


def test_normalize_question_remove_acentos_e_colapsa_espacos() -> None:
    assert normalize_question("  Qual é a  RECEITA\tTotal? ") == "qual e a receita total?"


def test_cache_key_igual_para_acentos_diferentes() -> None:
    assert cache_key("Ação", ["model:free"], "v1") == cache_key("acao", ["model:free"], "v1")


def test_cache_key_muda_com_modelos_ordem_e_prompt_version() -> None:
    base = cache_key("receita total", ["a:free", "b:free"], "v1")
    assert cache_key("receita total", ["b:free", "a:free"], "v1") != base
    assert cache_key("receita total", ["a:free"], "v1") != base
    assert cache_key("receita total", ["a:free", "b:free"], "v2") != base


def test_get_chave_ausente_retorna_none(tmp_path: Path) -> None:
    cache = AnswerCache(tmp_path / "answers.db", ttl_s=60)
    assert cache.get("inexistente") is None


def test_set_get_roundtrip_preserva_acentos_e_numeros(tmp_path: Path) -> None:
    path = tmp_path / "answers.db"
    cache = AnswerCache(path, ttl_s=60)
    payload = {"answer": "A receita total é R$ 1.234,56", "rows": [[1, 42.5], [-3, 0]], "count": 2}
    cache.set("k", payload)
    assert cache.get("k") == payload
    with closing(sqlite3.connect(path)) as conn:
        (raw,) = conn.execute("SELECT payload FROM answers WHERE key = 'k'").fetchone()
    assert "é" in raw  # ensure_ascii=False: acentos gravados literalmente


def test_persistencia_entre_instancias(tmp_path: Path) -> None:
    path = tmp_path / "cache" / "answers.db"
    AnswerCache(path, ttl_s=60).set("k", {"v": "café"})
    assert AnswerCache(path, ttl_s=60).get("k") == {"v": "café"}


def test_expiracao_usa_relogio_injetavel(tmp_path: Path) -> None:
    now = [1000.0]
    cache = AnswerCache(tmp_path / "answers.db", ttl_s=60, clock=lambda: now[0])
    cache.set("k", {"v": 1})
    now[0] = 1059.0
    assert cache.get("k") == {"v": 1}
    now[0] = 1060.0  # created_at + ttl_s == now -> expirado
    assert cache.get("k") is None


def test_ttl_zero_desliga_cache(tmp_path: Path) -> None:
    path = tmp_path / "answers.db"
    cache = AnswerCache(path, ttl_s=0)
    cache.set("k", {"v": 1})
    assert cache.get("k") is None
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM answers").fetchone() == (0,)


def test_upsert_sobrescreve_sem_duplicar(tmp_path: Path) -> None:
    path = tmp_path / "answers.db"
    cache = AnswerCache(path, ttl_s=60)
    cache.set("k", {"v": 1})
    cache.set("k", {"v": 2})
    assert cache.get("k") == {"v": 2}
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM answers").fetchone() == (1,)


def test_cria_diretorio_pai_inexistente(tmp_path: Path) -> None:
    path = tmp_path / "novo" / "sub" / "answers.db"
    AnswerCache(path, ttl_s=60).set("k", {"v": 1})
    assert path.is_file()
