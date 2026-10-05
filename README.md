<div align="center">

# CineData Analytics — Agente Text-to-SQL

[Rodando](#rodando) • [Como usar](docs/USO.md) • [Arquitetura](docs/ARQUITETURA.md) • [Estado atual](#estado-atual) • [Estrutura](#estrutura-do-projeto) • [Contribuir](#contribuir)

![Em desenvolvimento](https://img.shields.io/badge/status-em%20desenvolvimento-orange?style=flat-square)
![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![PydanticAI](https://img.shields.io/badge/PydanticAI-E92063?style=flat-square&logo=pydantic&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white)

</div>

---

### Sumário
- [Introdução](#introdução)
- [Estado atual](#estado-atual)
- [Stack](#stack)
- [Rodando](#rodando)
- [Como usar a API](docs/USO.md) — rotas, exemplos `curl`, erros e avaliação
- [Arquitetura e regras de negócio](docs/ARQUITETURA.md) — camadas, decisões e fórmulas
- [Estrutura do projeto](#estrutura-do-projeto)
- [Contribuir](#contribuir)


# Introdução

Agente que responde perguntas em português do Brasil sobre o catálogo de filmes
da CineData Analytics. Ele gera e executa SQL **somente leitura** sobre a camada
Gold (`cinerocket.db`, SQLite) e é exposto como módulo backend **FastAPI**, com o
Swagger em `/docs` fazendo o papel de interface.

Este README documenta o que **existe e funciona agora**, não a visão final do produto.

Para usar a API (rotas, exemplos `curl`, códigos de erro e avaliação), veja
[Como usar a API](docs/USO.md). Para as decisões de projeto e as regras de
negócio aplicadas no SQL, veja [Arquitetura](docs/ARQUITETURA.md).


# Estado atual

O que já está implementado e testado:

- **Agente Text-to-SQL (PydanticAI)**: uma única ferramenta, `run_sql`. O alvo
  são 2 chamadas ao LLM por pergunta (gerar o SQL e redigir a resposta), com
  teto em `AGENT_REQUEST_LIMIT` quando o SQL precisa ser corrigido. O modelo
  recebe no máximo 50 linhas; o resultado completo vai na resposta da API.
- **Contexto semântico fixo**: o prompt de sistema traz o esquema das 10
  tabelas, com descrição de cada coluna, e as regras de negócio do banco
  (receita nula, margem, notas sem voto, gêneros em inglês, últimos N anos,
  dupla ator–diretor). É montado uma vez só, na subida da aplicação.
- **SQL em camadas de defesa**: banco aberto em `mode=ro` com
  `PRAGMA query_only=ON` e `ATTACH` bloqueado, validação com `sqlglot` (uma
  instrução `SELECT`/`UNION`, só as 10 tabelas da Gold), `LIMIT` imposto e
  tempo máximo por consulta. Um SQL recusado volta ao LLM para ele corrigir.
- **Fallback entre modelos e cota**: os modelos de `LLM_MODELS` formam uma
  cadeia. Um 429 de provedor lotado passa para o próximo modelo; um 429 de
  cota diária para na hora e responde com o horário de reset (21h BRT). Nunca
  repete a chamada no mesmo modelo.
- **Cache de respostas**: a mesma pergunta (sem diferenciar maiúsculas,
  acentos e espaços) volta do cache com `cached=true` e 0 chamadas ao LLM.
  Erros não entram no cache.
- **API FastAPI**: `/api/v1/ask`, `/api/v1/sql` (SQL direto, sem LLM),
  `/api/v1/schema`, `/api/v1/quota` e `/health`, com erros no formato
  `{error, detail}`.
- **Log estruturado**: cada pergunta gera uma linha JSON com pergunta, SQL,
  modelo, chamadas ao LLM, latência, cache e erro.
- **Golden set**: as 14 perguntas do enunciado com SQL de referência escrito à
  mão, e um runner que compara as respostas da API com a referência.

O que **ainda não existe**:

- Uma rodada completa da avaliação com o prompt final. A primeira rodada deu
  **8/14**; depois dos ajustes, todas as 14 perguntas acertaram em pelo menos
  uma rodada, mas só 6 delas foram verificadas com o prompt final
  ([detalhes](docs/USO.md#resultado)).
- Memória de conversa, gráfico sugerido (`chart_spec`), busca semântica nas
  sinopses e interface de chat (os opcionais do plano).
- CI e git hooks: nada roda `ruff` ou `pytest` automaticamente.

Limitações conhecidas:

- A cota grátis do OpenRouter é de 50 chamadas por dia, e **falhas também
  contam**. O contador zera à meia-noite UTC (21h BRT).
- Os modelos `:free` variam muito em qualidade de tool calling: podem gerar
  SQL inválido ou ignorar regras. O retry e o fallback reduzem o problema, mas
  não o eliminam.
- Lucro e margem só existem para 1.630 filmes (os que têm receita e orçamento).

# Stack

- [Python 3.12](https://www.python.org/) gerenciado com [uv](https://docs.astral.sh/uv/)
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) e [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [PydanticAI](https://ai.pydantic.dev/) (`FallbackModel`, `FunctionModel` nos testes) falando com o [OpenRouter](https://openrouter.ai/) no padrão OpenAI
- [sqlglot](https://sqlglot.com/) para validar o SQL e [SQLite](https://www.sqlite.org/) somente leitura
- [httpx](https://www.python-httpx.org/) e [PyYAML](https://pyyaml.org/) na avaliação
- [pytest](https://docs.pytest.org/) e [Ruff](https://docs.astral.sh/ruff/)

# Rodando

**Pré-requisitos:** [uv](https://docs.astral.sh/uv/) (ele instala o Python 3.12
fixado em `.python-version`), uma chave do [OpenRouter](https://openrouter.ai/keys)
e o banco `cinerocket.db` da pasta compartilhada da atividade (554 MB
descompactado; se vier como `cinerocket (1).db`, renomeie).

```sh
uv sync
mkdir -p data && mv /caminho/do/cinerocket.db data/cinerocket.db
uv run python scripts/prepare_db.py   # índices auxiliares + ANALYZE, uma vez só
cp .env.example .env                  # preencha OPENROUTER_API_KEY
uv run uvicorn app.main:app --reload
```

Depois abra `http://127.0.0.1:8000/docs`.

Sem a chave ou sem o arquivo do banco, a API não sobe e diz o que falta
(`OPENROUTER_API_KEY ausente: ...` ou `DB_PATH: ... arquivo do banco não encontrado`).
É configuração faltando, não bug.

> [!IMPORTANT]
> Cada pergunta em `/api/v1/ask` gasta cerca de 2 chamadas da cota grátis,
> e as chamadas que falham também contam. Para conferir algo **sem gastar
> cota**, use os caminhos que não chamam o LLM:
> ```sh
> uv run pytest                               # testes sem rede e sem LLM
> uv run python -m evals.run_eval --dry-run   # roda só o SQL de referência
> ```
> e a rota `POST /api/v1/sql`. `GET /api/v1/quota` mostra quanto resta no dia.

Outros comandos úteis:

- `uv run pytest`: roda os testes. Eles criam um SQLite mínimo com o mesmo DDL
  do banco real, então não dependem do arquivo de 554 MB nem de rede.
- `uv run ruff format .` e `uv run ruff check .`: formatação e lint.
- `uv run python -m evals.run_eval`: rodada completa da avaliação (API no ar,
  ≈ 28 chamadas, no máximo uma por dia). Aborta antes de começar se a cota não
  der para todas as perguntas, a menos que se use `--force`.
- `uv run python -m evals.run_eval --only <id1>,<id2>`: repete só as perguntas
  que falharam.
- `uv run python scripts/prepare_db.py --db <caminho>`: prepara um banco em
  outro caminho. É idempotente e não altera dados.

# Estrutura do projeto

```
genai_cinema/
├── app/
│   ├── api/            # Rotas, schemas de request/response e mapeamento de erros
│   ├── agent/          # Prompt, cadeia de modelos e cota, agente, cache e serviço de perguntas
│   ├── db/             # Conexão somente leitura com timeout e guardrail de SQL
│   ├── config.py       # Settings (pydantic-settings) lidos do .env
│   └── main.py         # App factory e lifespan
├── scripts/
│   └── prepare_db.py   # Índices auxiliares + ANALYZE
├── evals/              # Golden set (14 perguntas), comparador e runner
├── tests/              # pytest; fixtures/schema.sql é o DDL real do banco
├── docs/               # Uso da API e arquitetura
└── data/               # cinerocket.db (fora do Git)
```

As camadas seguem `app/db` → `app/agent` → `app/api`, e nenhuma camada de
baixo importa de uma de cima: `db` não conhece LLM nem HTTP, e `agent` não
conhece HTTP.

# Contribuir

- Nunca commitamos direto na `main`. Todo trabalho vai em branches.
- Commits são atômicos (um por mudança lógica), no formato Conventional Commits.
- Rode `uv run ruff format .`, `uv run ruff check .` e `uv run pytest` antes
  de abrir um PR. Nenhum hook ou CI faz isso por você.
- Testes nunca chamam o LLM nem a rede: use `FunctionModel` para o agente e
  `httpx.MockTransport` para o OpenRouter.
- A rodada completa da avaliação gasta ≈ 28 chamadas: no máximo uma por dia.
  Nas outras, use `--only` só com as perguntas que falharam.
