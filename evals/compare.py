"""Comparação pura entre o resultado de referência e as linhas devolvidas pelo agente (SPEC-10).

A correspondência é por CONTEÚDO: o agente pode nomear as colunas como quiser. Uma linha do agente casa
com uma linha de referência quando todos os valores de ``key_columns`` da referência aparecem entre as
células daquela linha; havendo ``value_column``, algum número da linha precisa estar dentro da tolerância
relativa de 1%.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MODES = frozenset({"top_k", "set", "scalar"})
RELATIVE_TOLERANCE = 0.01


@dataclass(frozen=True)
class CompareSpec:
    mode: str
    key_columns: tuple[str, ...]
    order_column: str | None = None
    k: int | None = None
    value_column: str | None = None

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "CompareSpec":
        """Valida e converte o bloco ``compare`` do YAML; mensagem de erro em PT-BR."""
        if not isinstance(mapping, Mapping):
            raise ValueError("compare deve ser um mapa com pelo menos mode e key_columns")
        mode = mapping.get("mode")
        if mode not in MODES:
            raise ValueError(f"mode inválido: {mode!r} (esperado um de {sorted(MODES)})")
        raw_keys = mapping.get("key_columns")
        if not isinstance(raw_keys, list) or not raw_keys or not all(isinstance(c, str) and c for c in raw_keys):
            raise ValueError("key_columns deve ser uma lista não vazia de nomes de colunas")
        key_columns = tuple(raw_keys)
        order_column = mapping.get("order_column")
        k = mapping.get("k")
        if mode == "top_k":
            if not isinstance(order_column, str) or not order_column:
                raise ValueError("mode top_k exige order_column")
            if not isinstance(k, int) or isinstance(k, bool) or k < 1:
                raise ValueError("mode top_k exige k inteiro >= 1")
        else:
            if order_column is not None and not isinstance(order_column, str):
                raise ValueError("order_column deve ser texto")
            if k is not None and (not isinstance(k, int) or isinstance(k, bool) or k < 1):
                raise ValueError("k deve ser inteiro >= 1")
        value_column = mapping.get("value_column")
        if value_column is not None and (not isinstance(value_column, str) or not value_column):
            raise ValueError("value_column deve ser texto não vazio quando informado")
        return cls(
            mode=mode,
            key_columns=key_columns,
            order_column=order_column,
            k=k,
            value_column=value_column,
        )


@dataclass(frozen=True)
class CompareResult:
    passed: bool
    reason: str


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _norm_text(value: Any) -> str:
    return str(value).casefold().strip()


def _cell_equals(left: Any, right: Any) -> bool:
    """Igualdade de célula para as chaves: numérica entre números, textual (casefold/strip) no resto."""
    if _is_number(left) and _is_number(right):
        return float(left) == float(right)
    if _is_number(left) or _is_number(right):
        try:
            return float(left) == float(right)
        except (TypeError, ValueError):
            return False
    return _norm_text(left) == _norm_text(right)


def _num_close(left: Any, right: Any) -> bool:
    """Tolerância relativa de 1% entre dois números."""
    if not (_is_number(left) and _is_number(right)):
        return False
    a, b = float(left), float(right)
    if a == b:
        return True
    return abs(a - b) <= RELATIVE_TOLERANCE * max(abs(a), abs(b))


def _row_matches(ref_row: Mapping[str, Any], agent_row: Sequence[Any], spec: CompareSpec) -> bool:
    for key in spec.key_columns:
        ref_value = ref_row.get(key)
        if not any(_cell_equals(ref_value, cell) for cell in agent_row):
            return False
    if spec.value_column is not None:
        ref_value = ref_row.get(spec.value_column)
        if _is_number(ref_value) and not any(_num_close(ref_value, cell) for cell in agent_row):
            return False
    return True


def _match_rows(
    agent_rows: Sequence[Sequence[Any]], acceptable: Sequence[Mapping[str, Any]], spec: CompareSpec
) -> list[int | None]:
    """Emparelhamento máximo (Kuhn) das linhas do agente com linhas aceitáveis distintas da referência."""
    match_ref: list[int | None] = [None] * len(acceptable)

    def augment(agent_idx: int, visited: list[bool]) -> bool:
        for ref_idx, ref_row in enumerate(acceptable):
            if visited[ref_idx] or not _row_matches(ref_row, agent_rows[agent_idx], spec):
                continue
            visited[ref_idx] = True
            current = match_ref[ref_idx]
            if current is None or augment(current, visited):
                match_ref[ref_idx] = agent_idx
                return True
        return False

    for agent_idx in range(len(agent_rows)):
        augment(agent_idx, [False] * len(acceptable))
    result: list[int | None] = [None] * len(agent_rows)
    for ref_idx, agent_idx in enumerate(match_ref):
        if agent_idx is not None:
            result[agent_idx] = ref_idx
    return result


def _describe(ref_row: Mapping[str, Any], spec: CompareSpec) -> str:
    parts = [f"{key}={ref_row.get(key)!r}" for key in spec.key_columns]
    if spec.value_column is not None:
        parts.append(f"{spec.value_column}={ref_row.get(spec.value_column)!r}")
    return ", ".join(parts)


def _order_value(ref_row: Mapping[str, Any], order_column: str) -> float:
    value = ref_row.get(order_column)
    return float(value) if _is_number(value) else float("-inf")


def _compare_top_k(
    ref_records: list[dict[str, Any]], agent_rows: Sequence[Sequence[Any]], spec: CompareSpec
) -> CompareResult:
    order_column = spec.order_column
    assert order_column is not None
    k = spec.k or 0
    ref_sorted = sorted(ref_records, key=lambda row: _order_value(row, order_column), reverse=True)
    required = min(k, len(ref_sorted))
    if required == 0:
        return CompareResult(False, "referência vazia: nada a comparar")
    if len(agent_rows) < required:
        return CompareResult(
            False,
            f"agente devolveu {len(agent_rows)} linha(s); esperado ao menos {required} (k={k})",
        )
    kth_value = _order_value(ref_sorted[required - 1], order_column)
    acceptable = [row for row in ref_sorted if _order_value(row, order_column) >= kth_value]
    matching = _match_rows(list(agent_rows[:required]), acceptable, spec)
    if None in matching:
        idx = matching.index(None)
        expected = "; ".join(_describe(row, spec) for row in acceptable[: (spec.k or required)])
        return CompareResult(
            False,
            f"linha {idx + 1} do agente não casa com nenhuma linha aceitável do top {required}: "
            f"agente={list(agent_rows[idx])!r}; esperado: {expected}",
        )
    scope = f"top {k}" if len(ref_sorted) >= k else f"todas as {required} linhas da referência"
    return CompareResult(True, f"{required} linha(s) do agente conferem com {scope}")


def _compare_set(
    ref_records: list[dict[str, Any]], agent_rows: Sequence[Sequence[Any]], spec: CompareSpec
) -> CompareResult:
    if len(agent_rows) != len(ref_records):
        return CompareResult(
            False,
            f"agente devolveu {len(agent_rows)} linha(s); a referência tem {len(ref_records)}",
        )
    for index, ref_row in enumerate(ref_records):
        if not any(_row_matches(ref_row, agent_row, spec) for agent_row in agent_rows):
            return CompareResult(
                False,
                f"linha {index + 1} da referência não encontrada na resposta do agente: {_describe(ref_row, spec)}",
            )
    return CompareResult(True, f"{len(ref_records)} linha(s) conferem com a referência")


def _compare_scalar(
    ref_records: list[dict[str, Any]], agent_rows: Sequence[Sequence[Any]], spec: CompareSpec
) -> CompareResult:
    if len(ref_records) != 1:
        return CompareResult(False, f"referência deveria ter 1 linha, tem {len(ref_records)}")
    if not agent_rows:
        return CompareResult(False, "agente não devolveu linhas")
    if not _row_matches(ref_records[0], agent_rows[0], spec):
        return CompareResult(
            False,
            f"primeira linha do agente não casa com a referência: {_describe(ref_records[0], spec)}",
        )
    return CompareResult(True, "primeira linha do agente casa com a referência")


def compare(
    ref_columns: Sequence[str],
    ref_rows: Sequence[Sequence[Any]],
    agent_rows: Sequence[Sequence[Any]],
    spec: CompareSpec,
) -> CompareResult:
    """Compara o resultado de referência com as linhas do agente conforme ``spec``."""
    missing = [
        column
        for column in (*spec.key_columns, spec.order_column, spec.value_column)
        if column is not None and column not in ref_columns
    ]
    if missing:
        return CompareResult(False, f"colunas ausentes na referência: {sorted(set(missing))}")
    ref_records = [dict(zip(ref_columns, row, strict=False)) for row in ref_rows]
    if spec.mode == "top_k":
        return _compare_top_k(ref_records, agent_rows, spec)
    if spec.mode == "set":
        return _compare_set(ref_records, agent_rows, spec)
    return _compare_scalar(ref_records, agent_rows, spec)
