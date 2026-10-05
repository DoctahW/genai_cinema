import hashlib

from pydantic import BaseModel


class ColumnDoc(BaseModel):
    """Documentação de uma coluna da camada Gold."""

    name: str
    type: str
    description: str


class TableDoc(BaseModel):
    """Documentação de uma tabela da camada Gold."""

    name: str
    description: str
    columns: list[ColumnDoc]


TABLE_DOCS: list[TableDoc] = [
    TableDoc(
        name="fact_movies_performance",
        description="Métricas financeiras, popularidade e notas de cada filme.",
        columns=[
            ColumnDoc(
                name="sk_movie_id",
                type="VARCHAR(64)",
                description="Chave do filme (hash; nunca exibir ao usuário).",
            ),
            ColumnDoc(
                name="orcamento_usd",
                type="NUMERIC(18, 2)",
                description="Orçamento em USD; pode ser NULL.",
            ),
            ColumnDoc(
                name="receita_usd",
                type="NUMERIC(18, 2)",
                description="Receita em USD; NULL na maioria dos filmes — exigir receita_usd IS NOT NULL.",
            ),
            ColumnDoc(
                name="lucro_usd",
                type="NUMERIC(18, 2)",
                description="Lucro em USD; nunca NULL (sem receita vira -orçamento ou 0) — exige receita.",
            ),
            ColumnDoc(
                name="orcamento_brl",
                type="NUMERIC(18, 2)",
                description="Orçamento já convertido para reais; não converter de novo.",
            ),
            ColumnDoc(
                name="receita_brl",
                type="NUMERIC(18, 2)",
                description="Receita já convertida para reais; não converter de novo.",
            ),
            ColumnDoc(
                name="lucro_brl",
                type="NUMERIC(18, 2)",
                description="Lucro em reais já convertido; nunca NULL, mesmo cuidado do lucro_usd.",
            ),
            ColumnDoc(
                name="popularidade",
                type="DOUBLE",
                description="Índice de popularidade do TMDB.",
            ),
            ColumnDoc(
                name="nota_tmdb",
                type="DOUBLE",
                description="Nota TMDB de 0 a 10; 0 com qtd_tmdb=0 significa sem votos.",
            ),
            ColumnDoc(
                name="qtd_tmdb",
                type="INTEGER",
                description="Quantidade de votos TMDB; exigir qtd_tmdb > 0 para usar a nota TMDB.",
            ),
            ColumnDoc(
                name="nota_imdb",
                type="DOUBLE",
                description="Nota IMDb de 0 a 10; pode ser NULL (sem dado), então exigir nota_imdb IS NOT NULL.",
            ),
            ColumnDoc(
                name="qtd_imdb",
                type="INTEGER",
                description="Quantidade de votos IMDb.",
            ),
        ],
    ),
    TableDoc(
        name="dim_movies",
        description="Cadastro dos filmes: identidade, lançamento, idioma e sinopse.",
        columns=[
            ColumnDoc(
                name="sk_movie_id",
                type="VARCHAR(64)",
                description="Chave do filme (hash; única em todas as tabelas; nunca exibir ao usuário).",
            ),
            ColumnDoc(
                name="id_filme",
                type="VARCHAR(50)",
                description="Identificador do filme na fonte TMDB.",
            ),
            ColumnDoc(
                name="titulo",
                type="VARCHAR(500)",
                description="Título do filme; sempre trazer nas respostas.",
            ),
            ColumnDoc(
                name="data_lancamento",
                type="DATE",
                description="Data de lançamento (AAAA-MM-DD); pode ser NULL.",
            ),
            ColumnDoc(
                name="ano_lancamento",
                type="INTEGER",
                description="Ano de lançamento (2016 a 2029); usar em filtros de período.",
            ),
            ColumnDoc(
                name="duracao_minutos",
                type="INTEGER",
                description="Duração do filme em minutos.",
            ),
            ColumnDoc(
                name="idioma_original",
                type="VARCHAR(10)",
                description="Código do idioma original (ex.: en, pt).",
            ),
            ColumnDoc(
                name="status_filme",
                type="VARCHAR(50)",
                description="Situação do filme: 'Lançado', 'Em Produção', 'Planejado' ou 'Pós-Produção'.",
            ),
            ColumnDoc(
                name="sinopse",
                type="VARCHAR(4000)",
                description="Sinopse do filme em português.",
            ),
            ColumnDoc(
                name="url_poster",
                type="VARCHAR(2048)",
                description="URL da imagem do pôster.",
            ),
            ColumnDoc(
                name="url_backdrop",
                type="VARCHAR(2048)",
                description="URL da imagem de fundo.",
            ),
        ],
    ),
    TableDoc(
        name="dim_genres",
        description="Dimensão de gêneros, com nomes em inglês.",
        columns=[
            ColumnDoc(
                name="sk_genre_id",
                type="VARCHAR(64)",
                description="Chave do gênero (hash; nunca exibir ao usuário).",
            ),
            ColumnDoc(
                name="nome_genero",
                type="VARCHAR(50)",
                description="Gênero em inglês (19 valores exatos; ver seção de tradução PT→EN).",
            ),
        ],
    ),
    TableDoc(
        name="dim_people",
        description="Dimensão de pessoas, uma linha por (nome, tipo_pessoa).",
        columns=[
            ColumnDoc(
                name="sk_person_id",
                type="VARCHAR(64)",
                description="Chave da pessoa (hash; nunca exibir ao usuário).",
            ),
            ColumnDoc(
                name="nome_pessoa",
                type="VARCHAR(255)",
                description="Nome da pessoa.",
            ),
            ColumnDoc(
                name="tipo_pessoa",
                type="VARCHAR(20)",
                description="Papel: 'Ator', 'Diretor' ou 'Roteirista'; a mesma pessoa tem ids diferentes por papel.",
            ),
        ],
    ),
    TableDoc(
        name="dim_companies",
        description="Dimensão de produtoras.",
        columns=[
            ColumnDoc(
                name="sk_company_id",
                type="VARCHAR(64)",
                description="Chave da produtora (hash; nunca exibir ao usuário).",
            ),
            ColumnDoc(
                name="nome_produtora",
                type="VARCHAR(255)",
                description="Nome da produtora.",
            ),
        ],
    ),
    TableDoc(
        name="dim_reviews",
        description="Avaliações de usuários agregadas por filme (1:1 com o filme).",
        columns=[
            ColumnDoc(
                name="sk_review_id",
                type="VARCHAR(64)",
                description="Chave do agregado de avaliações (hash; nunca exibir ao usuário).",
            ),
            ColumnDoc(
                name="sk_movie_id",
                type="VARCHAR(64)",
                description="Filme avaliado (hash; nunca exibir ao usuário).",
            ),
            ColumnDoc(
                name="qtd_avaliacoes_usuarios",
                type="INTEGER",
                description="Quantidade de avaliações de usuários; usar em 'mais avaliados'.",
            ),
            ColumnDoc(
                name="nota_media_usuarios",
                type="DOUBLE",
                description="Nota média dos usuários (0 a 10); é a nota dos usuários.",
            ),
        ],
    ),
    TableDoc(
        name="movie_reviews",
        description="Texto de cada avaliação individual de usuário.",
        columns=[
            ColumnDoc(
                name="id",
                type="INTEGER",
                description="Chave sequencial da avaliação.",
            ),
            ColumnDoc(
                name="sk_movie_review_id",
                type="VARCHAR(64)",
                description="Chave da avaliação individual (hash; nunca exibir ao usuário).",
            ),
            ColumnDoc(
                name="sk_movie_id",
                type="VARCHAR(64)",
                description="Filme avaliado (hash; nunca exibir ao usuário).",
            ),
            ColumnDoc(
                name="name",
                type="VARCHAR(120)",
                description="Nome de quem avaliou.",
            ),
            ColumnDoc(
                name="rating",
                type="DOUBLE",
                description="Nota da avaliação individual (0 a 10).",
            ),
            ColumnDoc(
                name="text",
                type="VARCHAR(4000)",
                description="Texto da avaliação.",
            ),
            ColumnDoc(
                name="created_at",
                type="DATETIME",
                description="Data e hora da avaliação.",
            ),
        ],
    ),
    TableDoc(
        name="bridge_movie_genre",
        description="Ponte filme–gênero.",
        columns=[
            ColumnDoc(
                name="sk_movie_id",
                type="VARCHAR(64)",
                description="Filme (hash; ligar a dim_movies; nunca exibir ao usuário).",
            ),
            ColumnDoc(
                name="sk_genre_id",
                type="VARCHAR(64)",
                description="Gênero (hash; ligar a dim_genres; nunca exibir ao usuário).",
            ),
        ],
    ),
    TableDoc(
        name="bridge_movie_person",
        description="Ponte filme–pessoa (elenco e equipe).",
        columns=[
            ColumnDoc(
                name="sk_movie_id",
                type="VARCHAR(64)",
                description="Filme (hash; ligar a dim_movies; nunca exibir ao usuário).",
            ),
            ColumnDoc(
                name="sk_person_id",
                type="VARCHAR(64)",
                description="Pessoa (hash; ligar a dim_people; nunca exibir ao usuário).",
            ),
        ],
    ),
    TableDoc(
        name="bridge_movie_company",
        description="Ponte filme–produtora.",
        columns=[
            ColumnDoc(
                name="sk_movie_id",
                type="VARCHAR(64)",
                description="Filme (hash; ligar a dim_movies; nunca exibir ao usuário).",
            ),
            ColumnDoc(
                name="sk_company_id",
                type="VARCHAR(64)",
                description="Produtora (hash; ligar a dim_companies; nunca exibir ao usuário).",
            ),
        ],
    ),
]

GENRE_TRANSLATIONS: list[tuple[str, str]] = [
    ("Ação", "Action"),
    ("Aventura", "Adventure"),
    ("Animação", "Animation"),
    ("Comédia", "Comedy"),
    ("Crime", "Crime"),
    ("Documentário", "Documentary"),
    ("Drama", "Drama"),
    ("Família", "Family"),
    ("Fantasia", "Fantasy"),
    ("História", "History"),
    ("Terror", "Horror"),
    ("Música", "Music"),
    ("Mistério", "Mystery"),
    ("Romance", "Romance"),
    ("Ficção científica", "Science Fiction"),
    ("Suspense", "Thriller"),
    ("Filme para TV", "Tv Movie"),
    ("Guerra", "War"),
    ("Faroeste", "Western"),
]

STATUS_VALUES: list[str] = ["Lançado", "Em Produção", "Planejado", "Pós-Produção"]


def _render_ddl() -> str:
    """Renderiza o DDL documentado, uma tabela por linha."""
    lines = []
    for table in TABLE_DOCS:
        columns = ", ".join(f"{column.name} {column.type} -- {column.description}" for column in table.columns)
        lines.append(f"{table.name}({columns})")
    return "\n".join(lines)


def build_system_prompt() -> str:
    """Monta o prompt de sistema determinístico do agente a partir de `TABLE_DOCS`."""
    genres = ", ".join(f"{pt}={en}" for pt, en in GENRE_TRANSLATIONS)
    statuses = ", ".join(f"'{status}'" for status in STATUS_VALUES)
    sections = [
        "Você é um analista de dados do catálogo CineData (camada Gold, SQLite somente leitura). "
        "Responda sempre em português do Brasil (PT-BR).",
        "# Esquema\n" + _render_ddl(),
        "# Junções\n"
        "Tudo liga por sk_movie_id, usando dim_movies como centro.\n"
        "- dim_movies tem só dados cadastrais (titulo, ano_lancamento, status_filme, idioma, duração). popularidade, "
        "nota_tmdb, qtd_tmdb, nota_imdb, qtd_imdb, orçamento, receita e lucro ficam em fact_movies_performance: "
        "junte f.sk_movie_id = m.sk_movie_id para trazer o titulo.\n"
        "- bridge_movie_genre → dim_genres por sk_genre_id.\n"
        "- bridge_movie_person → dim_people por sk_person_id.\n"
        "- bridge_movie_company → dim_companies por sk_company_id.\n"
        "- dim_reviews é 1:1 com o filme (agregada); movie_reviews guarda o texto de cada avaliação individual.",
        "# Regras de negócio\n"
        '- "Receita" = "Faturamento" = "Bilheteria" = colunas receita_*. Sem "R$" ou "reais" na pergunta, use '
        'SEMPRE as colunas _usd (receita, lucro, orçamento); com "R$" ou "reais", use as _brl (já convertidas — não '
        "converta).\n"
        "- Todo cálculo com lucro_* (soma, média, ranking, margem) exige WHERE receita_usd IS NOT NULL, mesmo que a "
        "pergunta não peça: sem receita, o lucro vem como -orçamento. Margem = lucro_usd * 1.0 / receita_usd (os "
        "valores monetários são inteiros no SQLite: sem o * 1.0 a divisão é inteira e dá 0) e exige também "
        "orcamento_usd > 0 (esse filtro de orçamento vale só para margem; lucro total ou médio usa apenas "
        "receita_usd IS NOT NULL). Declare a fórmula usada nas assumptions. Padrão para lucro agregado (troque a "
        "dimensão conforme a pergunta): SELECT m.ano_lancamento, SUM(f.lucro_usd) AS lucro_total_usd FROM "
        "fact_movies_performance f JOIN dim_movies m ON m.sk_movie_id = f.sk_movie_id WHERE f.receita_usd IS NOT "
        "NULL GROUP BY m.ano_lancamento ORDER BY lucro_total_usd DESC.\n"
        "- Notas TMDB exigem qtd_tmdb > 0 (nota_tmdb=0 com qtd_tmdb=0 significa sem votos). Notas IMDb exigem "
        'nota_imdb IS NOT NULL. Todas as notas vão de 0 a 10 e são comparáveis sem normalizar. "Nota" ou "nota '
        'média" sem qualificação (ex.: "diretores com maior nota média") = f.nota_imdb; use '
        "dim_reviews.nota_media_usuarios só quando a pergunta falar de usuários. Declare a nota usada nas "
        "assumptions.\n"
        "- \"Últimos N anos\" = ano_lancamento >= CAST(strftime('%Y','now') AS INT) - N AND status_filme='Lançado'.\n"
        "- Dupla ator–diretor: dim_people tem uma linha por (nome, tipo_pessoa) e a mesma pessoa pode aparecer como "
        "Ator e Diretor com ids diferentes. Junte ator (tipo_pessoa='Ator') e diretor (tipo_pessoa='Diretor') pelo "
        'mesmo sk_movie_id em bridge_movie_person e exclua nome_ator = nome_diretor. "Mínimo de N filmes" = '
        "HAVING COUNT(DISTINCT sk_movie_id) >= N. Use esta estrutura (é a mais rápida): SELECT a.nome_pessoa AS "
        "nome_ator, d.nome_pessoa AS nome_diretor, COUNT(DISTINCT ba.sk_movie_id) AS qtd_filmes FROM dim_people a "
        "JOIN bridge_movie_person ba ON ba.sk_person_id = a.sk_person_id JOIN bridge_movie_person bd ON "
        "bd.sk_movie_id = ba.sk_movie_id JOIN dim_people d ON d.sk_person_id = bd.sk_person_id WHERE "
        "a.tipo_pessoa = 'Ator' AND d.tipo_pessoa = 'Diretor' AND a.nome_pessoa <> d.nome_pessoa "
        "GROUP BY a.nome_pessoa, d.nome_pessoa ORDER BY qtd_filmes DESC.\n"
        "- Mais avaliados = dim_reviews.qtd_avaliacoes_usuarios; nota dos usuários = dim_reviews.nota_media_usuarios.\n"
        "- Sempre traga titulo (ou nome) e nunca coloque colunas sk_* no SELECT. Ordene e limite rankings (ex.: top "
        "10) quando a pergunta pedir.",
        "# Tradução de gêneros (PT → EN, valores exatos do banco)\n" + genres,
        "# Valores de status (exatos)\n"
        + statuses
        + ". Há anos de 2016 a 2029 e filmes futuros: para períodos, filtre status_filme='Lançado'.",
        "# Regras de SQL\n"
        "- Use apenas SELECT/WITH no dialeto SQLite, uma única instrução e apenas as 10 tabelas listadas acima.\n"
        "- Resultados volumosos são cortados: a ferramenta devolve no máximo ~50 linhas e um campo truncated.",
        "# Como responder\n"
        "- Chame run_sql UMA vez com a consulta final: não faça consultas de teste ou de verificação e não consulte "
        "tabelas de sistema — o esquema completo já está aqui.\n"
        "- Se a ferramenta devolver erro, corrija a consulta e tente de novo.\n"
        "- Perguntas fora do catálogo de filmes: recuse educadamente SEM chamar a ferramenta (sql nulo).\n"
        "- Nunca invente números que não vieram da consulta.\n"
        "- Resposta final em PT-BR, objetiva, citando os principais itens pelo nome e seus valores (não só "
        "descreva a consulta).\n"
        "- Preencha sql com a consulta usada e assumptions com as premissas (filtros aplicados, moeda, fórmula).",
    ]
    return "\n\n".join(sections)


PROMPT_VERSION: str = hashlib.sha256(build_system_prompt().encode()).hexdigest()[:12]
