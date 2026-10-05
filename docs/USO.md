# Como usar a API

[Voltar ao README](../README.md)

### Sumário
- [Configuração](#configuração)
- [Rotas](#rotas)
- [Exemplos](#exemplos)
- [Erros](#erros)
- [Avaliação](#avaliação)


# Configuração

As variáveis são lidas do `.env` por `pydantic-settings` (`app/config.py`); o
modelo está em `.env.example`.

| Variável | Padrão | Efeito |
|---|---|---|
| `OPENROUTER_API_KEY` | — (obrigatória) | Chave do OpenRouter, usada pelos modelos e pela consulta de cota. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Base da API no padrão OpenAI. |
| `LLM_MODELS` | `nvidia/nemotron-3.5-lightning:free,google/gemma-4-26b-a4b-it:free,openrouter/free` | Modelos em ordem de preferência, separados por vírgula; formam a cadeia de fallback. |
| `DB_PATH` | `data/cinerocket.db` | Caminho do banco Gold; o arquivo precisa existir. |
| `SQL_TIMEOUT_S` | `20` | Tempo máximo de cada consulta, em segundos. Ao estourar: `QueryTimeout` (504). A consulta mais pesada do golden set (dupla ator–diretor) leva cerca de 6,5 s. |
| `SQL_MAX_ROWS` | `200` | Máximo de linhas devolvidas; acima disso o resultado é cortado e marcado `truncated`. |
| `AGENT_REQUEST_LIMIT` | `4` | Teto de chamadas ao LLM por pergunta. Acima dele: 422. |
| `CACHE_PATH` | `.cache/answers.db` | SQLite do cache de respostas. |
| `CACHE_TTL_S` | `86400` | Validade do cache, em segundos; `0` desliga o cache. |
| `LOG_LEVEL` | `INFO` | Nível de log. Cada `/ask` gera uma linha JSON no logger `app.ask`. |


# Rotas

| Método | Rota | Função |
|---|---|---|
| `POST` | `/api/v1/ask` | `{"question": str}` (3 a 500 caracteres) → resposta do agente com os dados consultados. |
| `POST` | `/api/v1/sql` | Executa SQL direto, passando pelo guardrail, sem LLM. Serve para depurar e para a avaliação. |
| `GET` | `/api/v1/schema` | Tabelas da camada Gold com colunas e descrições. |
| `GET` | `/api/v1/quota` | Repassa a cota diária de modelos gratuitos do OpenRouter. |
| `GET` | `/health` | Banco acessível e configuração carregada. |

O Swagger em `/docs` traz as 14 perguntas do enunciado como exemplos do `/ask`.


# Exemplos

Pergunta ao agente (gasta cota):

```sh
curl -s http://127.0.0.1:8000/api/v1/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "Top 10 filmes com maior receita em R$"}'
```

Formato da resposta:

```json
{
  "answer": "O filme com maior receita em reais é Avatar: The Way Of Water (R$ 12,39 bilhões), seguido de ...",
  "sql": "SELECT m.titulo, f.receita_brl FROM fact_movies_performance AS f JOIN dim_movies AS m ON m.sk_movie_id = f.sk_movie_id WHERE f.receita_brl IS NOT NULL ORDER BY f.receita_brl DESC LIMIT 10",
  "columns": ["titulo", "receita_brl"],
  "rows": [["Avatar: The Way Of Water", 12390136500.54], ["Avengers: Endgame", 11094720000]],
  "row_count": 10,
  "truncated": false,
  "assumptions": ["Receita em R$ lida direto de receita_brl (já convertida)."],
  "model_used": "nvidia/nemotron-3.5-lightning:free",
  "cached": false,
  "latency_ms": 8421.3,
  "llm_calls": 2
}
```

`sql` é a consulta que de fato rodou, depois do guardrail. `model_used` é o
modelo da cadeia que respondeu. Numa pergunta repetida, `cached` vem `true` e
`llm_calls` vem `0`.

SQL direto, sem LLM (o guardrail impõe o `LIMIT` quando ele falta):

```sh
curl -s http://127.0.0.1:8000/api/v1/sql \
  -H 'Content-Type: application/json' \
  -d '{"sql": "SELECT titulo, ano_lancamento FROM dim_movies ORDER BY ano_lancamento DESC"}'
```

Esquema documentado, cota e saúde:

```sh
curl -s http://127.0.0.1:8000/api/v1/schema
curl -s http://127.0.0.1:8000/api/v1/quota
# {"used": 3, "limit": 50, "remaining": 47, "reset_at_brt": "21:00"}
curl -s http://127.0.0.1:8000/health
# {"status": "ok", "database": "ok", "models": ["nvidia/nemotron-3.5-lightning:free", "..."]}
```


# Erros

Os erros de domínio usam sempre o corpo `{"error": "<NomeDaExcecao>", "detail": "<mensagem em PT-BR>"}`.

| Status | Quando |
|---|---|
| `400` | `SQLValidationError`: o guardrail recusou o SQL (comando de escrita, tabela fora da Gold, várias instruções). |
| `422` | `UsageLimitExceeded`: a pergunta passou do teto de chamadas ao LLM. A validação do corpo da requisição também usa 422, no formato padrão do FastAPI. |
| `429` | `QuotaExceeded`: cota diária esgotada. O `detail` cita o reset às 21h BRT, e a resposta traz `Retry-After`. |
| `502` | `UnexpectedModelBehavior`, erro do provedor (inclui chave recusada, 401/403) ou falha ao consultar `/api/v1/quota`. |
| `503` | `ModelsUnavailable`: todos os modelos da cadeia falharam. O `/health` também responde 503 quando o banco está inacessível. |
| `504` | `QueryTimeout`: a consulta passou de `SQL_TIMEOUT_S`. |


# Avaliação

O golden set (`evals/golden.yaml`) tem as 14 perguntas do enunciado, cada uma
com `reference_sql` escrito à mão e a regra de comparação (`top_k`, `set` ou
`scalar`). O runner roda o SQL de referência localmente e compara com as
respostas da API pelo conteúdo, não pelo nome das colunas.

```sh
# 0 chamadas ao LLM: só executa o SQL de referência
uv run python -m evals.run_eval --dry-run

# rodada completa, com a API no ar: ≈ 2 chamadas por pergunta, ≈ 28 no total
uv run python -m evals.run_eval

# só as perguntas que falharam
uv run python -m evals.run_eval --only fin_top10_receita_brl,cast_dupla_ator_diretor
```

Os relatórios (`.json` e `.md`) ficam em `evals/reports/`, com acerto e
chamadas usadas por pergunta. Antes de começar, o runner confere a cota e
aborta se ela não der 2 chamadas por pergunta (`--force` pula essa checagem).
Um 429 de cota interrompe a rodada na hora.

### Resultado

Rodada completa de 05/10/2026 ([relatório](../evals/reports/20261005-144948.md)): **8/14 acertos**,
todas as respostas vieram de `nvidia/nemotron-3.5-lightning:free` (o fallback não precisou entrar).

| Categoria | Acertos |
|---|---|
| Bilheteria e Finanças | 2/3 |
| Popularidade e Engajamento | 0/3 |
| Elenco e Equipe | 2/3 |
| Gêneros e Produtoras | 2/3 |
| Avaliações dos Usuários | 2/2 |

O relatório soma 24 chamadas, mas só conta as respostas com sucesso. As 3 perguntas que estouraram o
limite gastaram 4 chamadas cada, e a cota do dia (`/api/v1/quota`) registrou cerca de 36.

Por que as 6 falharam:

| Pergunta | Causa |
|---|---|
| Os 5 filmes mais populares; divergência TMDB × IMDb; nota IMDb por ano | O modelo procurou `popularidade` e as notas em `dim_movies`, tentou ler o esquema do sistema (recusado pelo guardrail) e estourou `AGENT_REQUEST_LIMIT` (422). |
| Lucro médio por gênero | Usou `lucro_brl` sem a pergunta pedir reais. |
| Diretores com maior nota média | Usou a nota dos usuários (`nota_media_usuarios`) em vez da IMDb. |
| Produtora com maior lucro total | Filtrou por `status_filme` em vez de `receita_usd IS NOT NULL` e trouxe o `sk_company_id`. |

### Ajustes e novas rodadas

Cada rodada abaixo usou `--only` nas perguntas que ainda falhavam. O que mudou entre elas:

- **Prompt:**
  - em que tabela ficam popularidade e notas;
  - USD como moeda padrão e lucro sempre com `receita_usd IS NOT NULL`;
  - o filtro `orcamento_usd > 0` vale só para margem;
  - "nota" = IMDb;
  - um padrão de consulta para lucro agregado;
  - nenhuma consulta de verificação e nenhuma coluna `sk_*` no `SELECT`.
- **Ferramenta `run_sql`:** quando o SQLite responde `no such column`, o erro devolvido ao modelo diz em
  que tabela a coluna fica, ou sugere a coluna certa se o nome veio com erro de digitação (`note_tmdb`
  → `nota_tmdb`).
- **Fallback:** uma resposta malformada do provedor passa para o próximo modelo.
- **Golden set:** a referência de "nota IMDb por ano" passou a filtrar `status_filme = 'Lançado'`, a
  mesma regra de status do prompt. O modelo já filtrava assim, e há cerca de 1.150 filmes ainda não
  lançados com nota IMDb em 2023 e 2024.

| Rodada | Relatório | Acertos | Passaram |
|---|---|---|---|
| 1 (completa) | [144948](../evals/reports/20261005-144948.md) | 8/14 | as 8 que não aparecem na tabela de falhas |
| 2 | [150646](../evals/reports/20261005-150646.md) | 2/6 | lucro médio por gênero, 5 mais populares |
| 3 | [151337](../evals/reports/20261005-151337.md) | 2/4 | nota IMDb por ano, diretores com maior nota |
| 4 (prompt final) | [151706](../evals/reports/20261005-151706.md) | 2/2 | divergência TMDB × IMDb, produtora com maior lucro |
| 5 (prompt final) | [151951](../evals/reports/20261005-151951.md) | 4/4 | top 10 receita, maior margem, gênero com maior margem, dupla ator–diretor |

**Todas as 14 perguntas acertaram em pelo menos uma rodada.** Com o prompt final foram verificadas 6
(rodadas 4 e 5), com 2 a 3 chamadas por pergunta. As outras 8 acertaram com versões anteriores do
prompt e ainda não foram repetidas com a versão final. Para fechar com uma rodada completa
(cerca de 32 chamadas):

```sh
uv run python -m evals.run_eval
```
