"""CLI de avaliação: roda o SQL de referência localmente e compara com as respostas da API.

Uso:
    uv run python -m evals.run_eval --dry-run
    uv run python -m evals.run_eval [--only id1,id2] [--base-url URL] [--db DB] [--golden YAML] [--out DIR] [--force]

Sem ``--dry-run`` o runner consulta a cota e faz uma chamada por pergunta ao endpoint ``/api/v1/ask``
(uma rodada completa gasta ~2 chamadas por pergunta). Nenhuma importação de ``app.*``: fala com a API
somente por HTTP.
"""

import argparse
import json
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from evals.compare import CompareSpec, compare

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DB = Path("data/cinerocket.db")
DEFAULT_GOLDEN = Path("evals/golden.yaml")
DEFAULT_OUT = Path("evals/reports")
ASK_TIMEOUT_S = 180.0
CALLS_PER_QUESTION = 2

_REQUIRED_FIELDS = ("id", "category", "question", "reference_sql", "compare")


@dataclass
class GoldenItem:
    """Pergunta do golden set, com o resultado de referência preenchido em tempo de execução."""

    id: str
    category: str
    question: str
    reference_sql: str
    compare: CompareSpec
    notes: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    elapsed_s: float = 0.0


@dataclass
class AskRecord:
    """Resposta crua de ``POST /api/v1/ask`` (status 0 = falha de transporte)."""

    status: int
    body: dict[str, Any]

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@dataclass
class EvalRecord:
    """Resultado da avaliação de uma pergunta."""

    id: str
    category: str
    question: str
    passed: bool
    reason: str
    status: int
    llm_calls: int = 0
    model_used: str | None = None
    cached: bool | None = None
    latency_ms: int | None = None
    error: str | None = None


class QuotaInsufficient(RuntimeError):
    """Cota insuficiente para rodar as perguntas selecionadas."""


def load_golden(path: Path) -> list[GoldenItem]:
    """Carrega e valida o golden set; levanta ``SystemExit`` com mensagem clara em caso de erro."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"golden set não encontrado: {path}") from None
    except yaml.YAMLError as exc:
        raise SystemExit(f"YAML inválido em {path}: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise SystemExit(f"golden set deve ser uma lista não vazia: {path}")
    items: list[GoldenItem] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        where = f"item {index + 1}"
        if not isinstance(entry, dict):
            raise SystemExit(f"{where}: cada item deve ser um mapa")
        for name in _REQUIRED_FIELDS:
            if entry.get(name) in (None, ""):
                raise SystemExit(f"{where}: campo obrigatório ausente ou vazio: {name}")
        item_id = entry["id"]
        if not isinstance(item_id, str) or not item_id:
            raise SystemExit(f"{where}: id deve ser texto não vazio")
        if item_id in seen:
            raise SystemExit(f"{where}: id duplicado: {item_id}")
        seen.add(item_id)
        try:
            spec = CompareSpec.from_mapping(entry["compare"])
        except ValueError as exc:
            raise SystemExit(f"{where} ({item_id}): {exc}") from exc
        items.append(
            GoldenItem(
                id=item_id,
                category=str(entry["category"]),
                question=str(entry["question"]),
                reference_sql=str(entry["reference_sql"]),
                compare=spec,
                notes=str(entry.get("notes") or ""),
            )
        )
    return items


def connect_reference(db_path: Path) -> sqlite3.Connection:
    """Abre o banco em modo somente leitura (``mode=ro`` + ``query_only``)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    return conn


def run_reference(conn: sqlite3.Connection, item: GoldenItem) -> None:
    """Executa o SQL de referência e guarda colunas, linhas e tempo na pergunta."""
    started = time.perf_counter()
    cursor = conn.execute(item.reference_sql)
    item.columns = [description[0] for description in cursor.description or []]
    item.rows = [list(row) for row in cursor.fetchall()]
    item.elapsed_s = time.perf_counter() - started


def validate_reference_columns(item: GoldenItem) -> None:
    """Confere que as colunas exigidas pelo ``compare`` existem no resultado da referência."""
    required = list(item.compare.key_columns)
    required.extend(column for column in (item.compare.order_column, item.compare.value_column) if column)
    missing = [column for column in required if column not in item.columns]
    if missing:
        raise SystemExit(f"{item.id}: colunas ausentes no SQL de referência: {sorted(set(missing))}")


def fetch_quota(client: httpx.Client, base_url: str) -> dict[str, Any]:
    """GET ``/api/v1/quota``; levanta ``httpx.HTTPError`` em falha."""
    response = client.get(f"{base_url.rstrip('/')}/api/v1/quota")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise QuotaInsufficient(f"resposta inesperada de /api/v1/quota: {data!r}")
    return data


def ensure_quota(client: httpx.Client, base_url: str, n_questions: int, *, force: bool) -> dict[str, Any]:
    """Aborta se a cota restante não cobre 2 chamadas por pergunta (salvo ``--force``)."""
    quota = fetch_quota(client, base_url)
    remaining = quota.get("remaining")
    needed = CALLS_PER_QUESTION * n_questions
    if not force and isinstance(remaining, int) and not isinstance(remaining, bool) and remaining < needed:
        raise QuotaInsufficient(
            f"cota restante {remaining} < {needed} (2 chamadas × {n_questions} perguntas); use --force para ignorar"
        )
    return quota


def ask_question(client: httpx.Client, base_url: str, question: str) -> AskRecord:
    """POST ``/api/v1/ask`` sem retry; falha de transporte vira status 0."""
    try:
        response = client.post(f"{base_url.rstrip('/')}/api/v1/ask", json={"question": question}, timeout=ASK_TIMEOUT_S)
    except httpx.HTTPError as exc:
        return AskRecord(status=0, body={"error": "http_error", "detail": str(exc)})
    try:
        body = response.json()
    except ValueError:
        body = {"error": "invalid_json", "detail": response.text[:500]}
    if not isinstance(body, dict):
        body = {"error": "invalid_body", "detail": repr(body)[:500]}
    return AskRecord(status=response.status_code, body=body)


def _record_from_success(item: GoldenItem, record: AskRecord) -> EvalRecord:
    agent_rows = record.body.get("rows")
    if not isinstance(agent_rows, list):
        agent_rows = []
    result = compare(item.columns, item.rows, agent_rows, item.compare)
    return EvalRecord(
        id=item.id,
        category=item.category,
        question=item.question,
        passed=result.passed,
        reason=result.reason,
        status=record.status,
        llm_calls=int(record.body.get("llm_calls") or 0),
        model_used=record.body.get("model_used"),
        cached=record.body.get("cached"),
        latency_ms=record.body.get("latency_ms"),
    )


def _record_from_error(item: GoldenItem, record: AskRecord) -> EvalRecord:
    detail = record.body.get("detail") or record.body.get("error") or "erro sem detalhe"
    prefix = f"HTTP {record.status}" if record.status else "falha de transporte"
    return EvalRecord(
        id=item.id,
        category=item.category,
        question=item.question,
        passed=False,
        reason=f"{prefix}: {detail}",
        status=record.status,
        error=str(detail),
    )


def run_http(
    client: httpx.Client, base_url: str, items: Sequence[GoldenItem], *, force: bool = False
) -> tuple[list[EvalRecord], dict[str, Any]]:
    """Verifica a cota e avalia as perguntas via HTTP; 429 interrompe o loop imediatamente."""
    quota = ensure_quota(client, base_url, len(items), force=force)
    records: list[EvalRecord] = []
    stopped_on_429 = False
    for item in items:
        record = ask_question(client, base_url, item.question)
        if record.status == 429:
            records.append(_record_from_error(item, record))
            stopped_on_429 = True
            break
        records.append(_record_from_success(item, record) if record.ok else _record_from_error(item, record))
    meta = {"quota": quota, "stopped_on_429": stopped_on_429}
    return records, meta


def build_report(records: Sequence[EvalRecord], meta: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Monta o relatório serializável com totais de acertos e chamadas ao LLM."""
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": base_url,
        "quota": meta.get("quota"),
        "stopped_on_429": bool(meta.get("stopped_on_429")),
        "totals": {
            "total": len(records),
            "passed": sum(1 for record in records if record.passed),
            "llm_calls": sum(record.llm_calls for record in records),
        },
        "results": [
            {
                "id": record.id,
                "category": record.category,
                "question": record.question,
                "passed": record.passed,
                "reason": record.reason,
                "status": record.status,
                "llm_calls": record.llm_calls,
                "model_used": record.model_used,
                "cached": record.cached,
                "latency_ms": record.latency_ms,
                "error": record.error,
            }
            for record in records
        ],
    }


def _cell(value: Any) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    """Renderiza o relatório como tabela Markdown."""
    totals = report["totals"]
    lines = [
        "# Relatório de avaliação (SPEC-10)",
        "",
        f"- Gerado em: {report['generated_at']}",
        f"- API: {report['base_url']}",
        f"- Acertos: {totals['passed']}/{totals['total']}",
        f"- Chamadas ao LLM: {totals['llm_calls']}",
        f"- Interrompido por 429: {'sim' if report['stopped_on_429'] else 'não'}",
        "",
        "| id | categoria | passou | motivo | llm_calls | model_used | cached | latency_ms |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for result in report["results"]:
        lines.append(
            "| {id} | {category} | {passed} | {reason} | {llm_calls} | {model} | {cached} | {latency} |".format(
                id=_cell(result["id"]),
                category=_cell(result["category"]),
                passed="sim" if result["passed"] else "não",
                reason=_cell(result["reason"]),
                llm_calls=_cell(result["llm_calls"]),
                model=_cell(result["model_used"]),
                cached=_cell(result["cached"]),
                latency=_cell(result["latency_ms"]),
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_report(out_dir: Path, report: dict[str, Any], timestamp: datetime) -> tuple[Path, Path]:
    """Grava o relatório como ``YYYYmmdd-HHMMSS.json`` e ``.md``; devolve os caminhos."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = timestamp.strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def _select_items(items: list[GoldenItem], only: str | None) -> list[GoldenItem]:
    if not only:
        return items
    wanted = {part.strip() for part in only.split(",") if part.strip()}
    selected = [item for item in items if item.id in wanted]
    missing = wanted - {item.id for item in selected}
    if missing:
        raise SystemExit(f"--only citou ids inexistentes: {sorted(missing)}")
    if not selected:
        raise SystemExit("--only não selecionou nenhuma pergunta")
    return selected


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Avaliação do agente Text-to-SQL (SPEC-10)")
    parser.add_argument("--only", help="lista de ids separados por vírgula")
    parser.add_argument("--dry-run", action="store_true", help="só roda o SQL de referência, sem LLM")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="URL base da API")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="caminho do banco SQLite (somente leitura)")
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN), help="caminho do golden set YAML")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="diretório dos relatórios")
    parser.add_argument("--force", action="store_true", help="ignora a checagem de cota")
    return parser


def main(argv: Sequence[str] | None = None, client: httpx.Client | None = None) -> int:
    """Ponto de entrada da CLI; ``client`` permite injetar um ``httpx.Client`` (testes)."""
    args = _build_parser().parse_args(argv)
    items = _select_items(load_golden(Path(args.golden)), args.only)

    db_path = Path(args.db)
    try:
        conn = connect_reference(db_path)
    except sqlite3.Error as exc:
        print(f"erro ao abrir o banco {db_path}: {exc}")
        return 1
    try:
        for item in items:
            try:
                run_reference(conn, item)
            except sqlite3.Error as exc:
                print(f"{item.id}: erro ao rodar o SQL de referência: {exc}")
                return 1
            validate_reference_columns(item)
    finally:
        conn.close()

    if args.dry_run:
        for item in items:
            print(f"{item.id} [{item.category}]: {len(item.rows)} linhas em {item.elapsed_s:.2f}s")
            for row in item.rows[:3]:
                print(f"    {row}")
        print(f"\n{len(items)} consulta(s) de referência executadas (nenhuma chamada ao LLM).")
        return 0

    owns_client = client is None
    http_client = client if client is not None else httpx.Client(timeout=ASK_TIMEOUT_S)
    try:
        records, meta = run_http(http_client, args.base_url, items, force=args.force)
    except QuotaInsufficient as exc:
        print(f"cota insuficiente: {exc}")
        return 2
    except httpx.HTTPError as exc:
        print(f"falha ao consultar a API: {exc}")
        return 1
    finally:
        if owns_client:
            http_client.close()

    report = build_report(records, meta, args.base_url)
    json_path, md_path = write_report(Path(args.out), report, datetime.now())
    totals = report["totals"]
    print(f"acertos: {totals['passed']}/{totals['total']} | chamadas ao LLM: {totals['llm_calls']}")
    if meta["stopped_on_429"]:
        print("loop interrompido por 429 (cota esgotada)")
    for record in records:
        print(f"  {'OK ' if record.passed else 'FALHA'} {record.id}: {record.reason}")
    print(f"relatório: {json_path} e {md_path}")
    return 0 if totals["passed"] == totals["total"] and not meta["stopped_on_429"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
