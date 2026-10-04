"""Testes da avaliação: comparação pura, fluxo HTTP com MockTransport e golden set real."""

import json
from pathlib import Path

import httpx
import pytest
import yaml

from evals.compare import CompareSpec, compare
from evals.run_eval import GoldenItem, main

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = ROOT / "evals" / "golden.yaml"

QUESTIONS = [
    "Top 10 filmes com maior receita em R$",
    "Lucro médio por gênero, considerando apenas filmes com receita informada",
    "Filmes com maior margem de lucro, entre os que possuem receita e orçamento informados",
    "Os 5 filmes mais populares",
    "Filmes com maior divergência entre a nota TMDB e a nota IMDb",
    "Nota média IMDb por ano de lançamento",
    "Ator com mais participações em filmes lançados nos últimos 5 anos",
    "Diretores com maior nota média (mínimo de 5 filmes)",
    "Dupla ator–diretor que mais trabalhou junta",
    "Quantidade de filmes por gênero",
    "Produtora com maior lucro total",
    "Gênero com maior margem de lucro média",
    "Filmes mais avaliados pelos usuários",
    "Filmes em que a nota média dos usuários mais diverge da nota IMDb",
]


def _topk(k: int = 3) -> CompareSpec:
    return CompareSpec(
        mode="top_k", key_columns=("titulo",), order_column="receita_brl", k=k, value_column="receita_brl"
    )


REF_TOP = [["A", 100.0], ["B", 90.0], ["C", 80.0], ["D", 80.0], ["E", 70.0]]
REF_TOP_COLS = ["titulo", "receita_brl"]


# ---------------------------------------------------------------- compare: top_k


def test_top_k_empate_na_k_esima_posicao_aceito() -> None:
    result = compare(REF_TOP_COLS, REF_TOP, [["A", 100.0], ["B", 90.0], ["D", 80.0]], _topk())
    assert result.passed, result.reason


def test_top_k_ordem_diferente_aceita() -> None:
    result = compare(REF_TOP_COLS, REF_TOP, [["C", 80.0], ["A", 100.0], ["B", 90.0]], _topk())
    assert result.passed, result.reason


def test_top_k_linha_errada_reprovada() -> None:
    result = compare(REF_TOP_COLS, REF_TOP, [["A", 100.0], ["B", 90.0], ["Z", 80.0]], _topk())
    assert not result.passed
    assert "linha 3" in result.reason
    assert "agente=['Z', 80.0]" in result.reason
    assert "titulo='C'" in result.reason


def test_top_k_colunas_renomeadas_e_reordenadas_aceitas() -> None:
    agent_rows = [["extra", 100.0, "A"], [90.0, "B", "extra"], [80.0, "C", "extra"]]
    result = compare(REF_TOP_COLS, REF_TOP, agent_rows, _topk())
    assert result.passed, result.reason


def test_top_k_value_column_fora_da_tolerancia_reprovado() -> None:
    result = compare(REF_TOP_COLS, REF_TOP, [["A", 101.5], ["B", 90.0], ["C", 80.0]], _topk())
    assert not result.passed


def test_top_k_value_column_dentro_da_tolerancia_aceito() -> None:
    result = compare(REF_TOP_COLS, REF_TOP, [["A", 100.5], ["B", 90.0], ["C", 80.0]], _topk())
    assert result.passed, result.reason


def test_top_k_menos_linhas_que_k_reprovado() -> None:
    result = compare(REF_TOP_COLS, REF_TOP, [["A", 100.0], ["B", 90.0]], _topk())
    assert not result.passed
    assert "ao menos 3" in result.reason


def test_top_k_com_menos_referencias_que_k() -> None:
    result = compare(REF_TOP_COLS, REF_TOP[:2], [["A", 100.0], ["B", 90.0]], _topk(k=10))
    assert result.passed, result.reason


# ---------------------------------------------------------------- compare: set


def test_set_igual_aceito_e_fora_de_ordem() -> None:
    spec = CompareSpec(mode="set", key_columns=("nome_genero",), value_column="qtd")
    ref = [["Action", 5], ["Drama", 3], ["Comedy", 1]]
    result = compare(["nome_genero", "qtd"], ref, [["Comedy", 1], ["Action", 5], ["Drama", 3]], spec)
    assert result.passed, result.reason


def test_set_linha_faltando_reprovado() -> None:
    spec = CompareSpec(mode="set", key_columns=("nome_genero",), value_column="qtd")
    ref = [["Action", 5], ["Drama", 3], ["Comedy", 1]]
    result = compare(["nome_genero", "qtd"], ref, [["Action", 5], ["Drama", 3]], spec)
    assert not result.passed
    assert "3" in result.reason


def test_set_valor_fora_da_tolerancia_reprovado() -> None:
    spec = CompareSpec(mode="set", key_columns=("nome_genero",), value_column="qtd")
    ref = [["Action", 5], ["Drama", 3]]
    result = compare(["nome_genero", "qtd"], ref, [["Action", 5], ["Drama", 3.2]], spec)
    assert not result.passed


# ---------------------------------------------------------------- compare: scalar


def test_scalar_ok() -> None:
    spec = CompareSpec(mode="scalar", key_columns=("nome_ator",), value_column="qtd")
    result = compare(["nome_ator", "qtd"], [["Eric Roberts", 82]], [["eric roberts", 82]], spec)
    assert result.passed, result.reason


def test_scalar_falha_por_valor() -> None:
    spec = CompareSpec(mode="scalar", key_columns=("nome_ator",), value_column="qtd")
    result = compare(["nome_ator", "qtd"], [["Eric Roberts", 82]], [["Eric Roberts", 50]], spec)
    assert not result.passed


def test_scalar_sem_linhas_do_agente_reprovado() -> None:
    spec = CompareSpec(mode="scalar", key_columns=("nome_ator",), value_column="qtd")
    result = compare(["nome_ator", "qtd"], [["Eric Roberts", 82]], [], spec)
    assert not result.passed


# ---------------------------------------------------------------- compare: chave composta


def test_chave_composta_dupla_aceita_em_ordem_diferente() -> None:
    spec = CompareSpec(
        mode="top_k",
        key_columns=("nome_ator", "nome_diretor"),
        order_column="qtd_filmes",
        k=1,
        value_column="qtd_filmes",
    )
    ref = [["Joe Anoa'i", "Kevin Dunn", 37], ["Colby Lopez", "Kevin Dunn", 32]]
    result = compare(["nome_ator", "nome_diretor", "qtd_filmes"], ref, [["Kevin Dunn", "Joe Anoa'i", 37]], spec)
    assert result.passed, result.reason


def test_chave_composta_valor_errado_reprovado() -> None:
    spec = CompareSpec(
        mode="top_k",
        key_columns=("nome_ator", "nome_diretor"),
        order_column="qtd_filmes",
        k=1,
        value_column="qtd_filmes",
    )
    ref = [["Joe Anoa'i", "Kevin Dunn", 37], ["Colby Lopez", "Kevin Dunn", 32]]
    result = compare(["nome_ator", "nome_diretor", "qtd_filmes"], ref, [["Joe Anoa'i", "Kevin Dunn", 10]], spec)
    assert not result.passed


# ---------------------------------------------------------------- golden.yaml real


def test_golden_yaml_real_tem_14_perguntas_do_enunciado() -> None:
    entries = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert isinstance(entries, list)
    assert len(entries) == 14
    ids = [entry["id"] for entry in entries]
    assert len(set(ids)) == 14
    assert all(isinstance(item_id, str) and item_id for item_id in ids)
    assert [entry["question"] for entry in entries] == QUESTIONS


def test_golden_yaml_campos_obrigatorios_por_modo() -> None:
    entries = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    for entry in entries:
        assert entry["category"]
        assert entry["reference_sql"].strip()
        spec = CompareSpec.from_mapping(entry["compare"])
        assert spec.key_columns
        if spec.mode == "top_k":
            assert spec.order_column
            assert spec.k and spec.k >= 1


# ---------------------------------------------------------------- fluxo HTTP (MockTransport)


def _golden_item(item_id: str) -> dict:
    return {
        "id": item_id,
        "category": "Gêneros e Produtoras",
        "question": "Quantidade de filmes por gênero",
        "reference_sql": "SELECT nome_genero FROM dim_genres ORDER BY nome_genero",
        "compare": {"mode": "set", "key_columns": ["nome_genero"]},
    }


def _write_golden(path: Path, count: int) -> Path:
    path.write_text(yaml.safe_dump([_golden_item(f"g{i}") for i in range(1, count + 1)]), encoding="utf-8")
    return path


def _ask_body(rows: list[list[object]], *, llm_calls: int = 2) -> dict:
    return {
        "answer": "resposta",
        "sql": "SELECT nome_genero FROM dim_genres",
        "columns": ["nome_genero"],
        "rows": rows,
        "row_count": len(rows),
        "truncated": False,
        "assumptions": [],
        "model_used": "test/model:free",
        "cached": False,
        "latency_ms": 12,
        "llm_calls": llm_calls,
    }


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")


def test_quota_insuficiente_aborta_sem_chamar_ask(mini_db_path: Path, tmp_path: Path) -> None:
    golden = _write_golden(tmp_path / "golden.yaml", 2)
    asks: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/quota":
            return httpx.Response(200, json={"used": 49, "limit": 50, "remaining": 1})
        asks.append(request.url.path)
        return httpx.Response(200, json=_ask_body([["Action"], ["Drama"], ["Science Fiction"]]))

    with _client(handler) as client:
        code = main(["--golden", str(golden), "--db", str(mini_db_path), "--out", str(tmp_path)], client=client)

    assert code == 2
    assert asks == []
    assert list(tmp_path.glob("*.json")) == []


def test_429_interrompe_o_loop(mini_db_path: Path, tmp_path: Path) -> None:
    golden = _write_golden(tmp_path / "golden.yaml", 3)
    ask_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal ask_calls
        if request.url.path == "/api/v1/quota":
            return httpx.Response(200, json={"used": 0, "limit": 50, "remaining": 50})
        ask_calls += 1
        if ask_calls == 2:
            return httpx.Response(429, json={"error": "quota_exceeded", "detail": "cota diária esgotada"})
        return httpx.Response(200, json=_ask_body([["Action"], ["Drama"], ["Science Fiction"]]))

    with _client(handler) as client:
        code = main(["--golden", str(golden), "--db", str(mini_db_path), "--out", str(tmp_path)], client=client)

    assert ask_calls == 2  # a terceira pergunta não foi chamada
    assert code == 1
    report = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert report["stopped_on_429"] is True
    assert report["totals"] == {"total": 2, "passed": 1, "llm_calls": 2}
    assert report["results"][1]["status"] == 429


def test_relatorio_gerado_com_totais_corretos(mini_db_path: Path, tmp_path: Path) -> None:
    golden = _write_golden(tmp_path / "golden.yaml", 2)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/quota":
            return httpx.Response(200, json={"used": 0, "limit": 50, "remaining": 50})
        return httpx.Response(200, json=_ask_body([["Action"], ["Drama"], ["Science Fiction"]], llm_calls=2))

    with _client(handler) as client:
        code = main(["--golden", str(golden), "--db", str(mini_db_path), "--out", str(tmp_path)], client=client)

    assert code == 0
    json_path = next(tmp_path.glob("*.json"))
    md_path = next(tmp_path.glob("*.md"))
    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["totals"] == {"total": 2, "passed": 2, "llm_calls": 4}
    assert all(result["passed"] for result in report["results"])
    markdown = md_path.read_text(encoding="utf-8")
    assert "| id | categoria | passou |" in markdown
    assert "Acertos: 2/2" in markdown


def test_dry_run_roda_referencias_sem_llm(mini_db_path: Path, tmp_path: Path) -> None:
    golden = _write_golden(tmp_path / "golden.yaml", 2)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - não deve ser chamado
        raise AssertionError("dry-run não deve fazer HTTP")

    with _client(handler) as client:
        code = main(
            ["--dry-run", "--golden", str(golden), "--db", str(mini_db_path), "--out", str(tmp_path)],
            client=client,
        )

    assert code == 0
    assert list(tmp_path.glob("*.json")) == []


def test_load_golden_valida_campos_obrigatorios(tmp_path: Path) -> None:
    from evals.run_eval import load_golden

    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump([{"id": "x", "category": "c", "question": "q"}]), encoding="utf-8")
    with pytest.raises(SystemExit):
        load_golden(bad)


def test_golden_item_dataclass_tem_defaults() -> None:
    item = GoldenItem(
        id="x",
        category="c",
        question="q",
        reference_sql="SELECT 1",
        compare=CompareSpec(mode="scalar", key_columns=("a",)),
    )
    assert item.columns == [] and item.rows == [] and item.elapsed_s == 0.0
