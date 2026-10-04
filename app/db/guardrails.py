import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

GOLD_TABLES: frozenset[str] = frozenset(
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

# Nós que caracterizam escrita/DDL/controle; qualquer um na árvore invalida a consulta.
_BLOCKED_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Pragma,
    exp.Attach,
    exp.Detach,
    exp.Command,
)
_ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = (exp.Select, exp.Union)
# Separadores vazios criados por comentários após o ';' não são instruções.
_IGNORED_STATEMENTS: tuple[type[exp.Expression], ...] = (exp.Semicolon,)


class SQLValidationError(ValueError):
    """SQL recusado pelo guardrail; a mensagem (PT-BR) é devolvida ao LLM para correção."""


def validate_sql(sql: str, *, max_rows: int) -> str:
    text = (sql or "").strip()
    if not text:
        raise SQLValidationError("SQL vazio: envie uma consulta SELECT sobre as tabelas da camada Gold.")

    try:
        statements = sqlglot.parse(text, read="sqlite")
    except (ParseError, TokenError) as exc:
        raise SQLValidationError(f"SQL inválido: {_first_line(exc)}") from exc

    parsed = [stmt for stmt in statements if stmt is not None and not isinstance(stmt, _IGNORED_STATEMENTS)]
    if len(parsed) != 1:
        raise SQLValidationError(f"Envie exatamente uma instrução SQL (recebidas {len(parsed)}).")

    root = parsed[0]
    if not isinstance(root, _ALLOWED_ROOTS):
        raise SQLValidationError(
            f"Somente consultas SELECT/UNION são permitidas; recebido '{type(root).__name__.upper()}'."
        )

    _reject_blocked_nodes(root)
    _reject_unknown_tables(root)

    if root.args.get("limit") is None:
        root = root.limit(max_rows + 1)
    # Regenera do AST validado: o que executa é exatamente o que foi checado.
    return root.sql(dialect="sqlite")


def _reject_blocked_nodes(root: exp.Expression) -> None:
    for node in root.walk():
        if isinstance(node, _BLOCKED_NODES):
            raise SQLValidationError(
                f"Comando '{type(node).__name__.upper()}' não é permitido: este agente apenas lê dados."
            )


def _reject_unknown_tables(root: exp.Expression) -> None:
    cte_names = {cte.alias.lower() for cte in root.find_all(exp.CTE) if cte.alias}
    for table in root.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            # Ex.: pragma_table_info('dim_movies') ou outra função de tabela no FROM.
            raise SQLValidationError("Funções de tabela (ex.: pragma_table_info) no FROM não são permitidas.")
        if table.db or table.catalog:
            qualified = table.sql(dialect="sqlite")
            raise SQLValidationError(f"Tabela qualificada '{qualified}' não é permitida; use só o nome da tabela.")
        name = table.name.lower()
        if name not in GOLD_TABLES and name not in cte_names:
            raise SQLValidationError(f"Tabela '{table.name}' não pertence à camada Gold permitida.")


def _first_line(exc: BaseException) -> str:
    message = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return message if len(message) <= 200 else message[:197] + "..."
