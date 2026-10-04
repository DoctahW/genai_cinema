CREATE TABLE alembic_version (
	version_num VARCHAR(32) NOT NULL, 
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
CREATE TABLE dim_companies (
	sk_company_id VARCHAR(64) NOT NULL, 
	nome_produtora VARCHAR(255) NOT NULL, 
	CONSTRAINT pk_dim_companies PRIMARY KEY (sk_company_id), 
	CONSTRAINT uq_dim_companies_nome_produtora UNIQUE (nome_produtora)
);
CREATE TABLE dim_genres (
	sk_genre_id VARCHAR(64) NOT NULL, 
	nome_genero VARCHAR(50) NOT NULL, 
	CONSTRAINT pk_dim_genres PRIMARY KEY (sk_genre_id), 
	CONSTRAINT uq_dim_genres_nome_genero UNIQUE (nome_genero)
);
CREATE TABLE dim_movies (
	sk_movie_id VARCHAR(64) NOT NULL, 
	id_filme VARCHAR(50) NOT NULL, 
	titulo VARCHAR(500) NOT NULL, 
	data_lancamento DATE, 
	ano_lancamento INTEGER, 
	duracao_minutos INTEGER, 
	idioma_original VARCHAR(10), 
	status_filme VARCHAR(50), 
	sinopse VARCHAR(4000), 
	url_poster VARCHAR(2048), 
	url_backdrop VARCHAR(2048), 
	CONSTRAINT pk_dim_movies PRIMARY KEY (sk_movie_id)
);
CREATE TABLE dim_people (
	sk_person_id VARCHAR(64) NOT NULL, 
	nome_pessoa VARCHAR(255) NOT NULL, 
	tipo_pessoa VARCHAR(20) NOT NULL, 
	CONSTRAINT pk_dim_people PRIMARY KEY (sk_person_id), 
	CONSTRAINT ck_dim_people_tipo_pessoa_valido CHECK (tipo_pessoa IN ('Ator', 'Diretor', 'Roteirista')), 
	CONSTRAINT uq_dim_people_nome_pessoa_tipo_pessoa UNIQUE (nome_pessoa, tipo_pessoa)
);
CREATE TABLE bridge_movie_company (
	sk_movie_id VARCHAR(64) NOT NULL, 
	sk_company_id VARCHAR(64) NOT NULL, 
	CONSTRAINT pk_bridge_movie_company PRIMARY KEY (sk_movie_id, sk_company_id), 
	CONSTRAINT fk_bridge_movie_company_sk_movie_id_dim_movies FOREIGN KEY(sk_movie_id) REFERENCES dim_movies (sk_movie_id) ON DELETE CASCADE, 
	CONSTRAINT fk_bridge_movie_company_sk_company_id_dim_companies FOREIGN KEY(sk_company_id) REFERENCES dim_companies (sk_company_id) ON DELETE CASCADE
);
CREATE TABLE bridge_movie_genre (
	sk_movie_id VARCHAR(64) NOT NULL, 
	sk_genre_id VARCHAR(64) NOT NULL, 
	CONSTRAINT pk_bridge_movie_genre PRIMARY KEY (sk_movie_id, sk_genre_id), 
	CONSTRAINT fk_bridge_movie_genre_sk_movie_id_dim_movies FOREIGN KEY(sk_movie_id) REFERENCES dim_movies (sk_movie_id) ON DELETE CASCADE, 
	CONSTRAINT fk_bridge_movie_genre_sk_genre_id_dim_genres FOREIGN KEY(sk_genre_id) REFERENCES dim_genres (sk_genre_id) ON DELETE CASCADE
);
CREATE TABLE bridge_movie_person (
	sk_movie_id VARCHAR(64) NOT NULL, 
	sk_person_id VARCHAR(64) NOT NULL, 
	CONSTRAINT pk_bridge_movie_person PRIMARY KEY (sk_movie_id, sk_person_id), 
	CONSTRAINT fk_bridge_movie_person_sk_movie_id_dim_movies FOREIGN KEY(sk_movie_id) REFERENCES dim_movies (sk_movie_id) ON DELETE CASCADE, 
	CONSTRAINT fk_bridge_movie_person_sk_person_id_dim_people FOREIGN KEY(sk_person_id) REFERENCES dim_people (sk_person_id) ON DELETE CASCADE
);
CREATE TABLE dim_reviews (
	sk_review_id VARCHAR(64) NOT NULL, 
	sk_movie_id VARCHAR(64) NOT NULL, 
	qtd_avaliacoes_usuarios INTEGER NOT NULL, 
	nota_media_usuarios DOUBLE, 
	CONSTRAINT pk_dim_reviews PRIMARY KEY (sk_review_id), 
	CONSTRAINT uq_dim_reviews_sk_movie_id UNIQUE (sk_movie_id), 
	CONSTRAINT fk_dim_reviews_sk_movie_id_dim_movies FOREIGN KEY(sk_movie_id) REFERENCES dim_movies (sk_movie_id) ON DELETE CASCADE
);
CREATE TABLE fact_movies_performance (
	sk_movie_id VARCHAR(64) NOT NULL, 
	orcamento_usd NUMERIC(18, 2), 
	receita_usd NUMERIC(18, 2), 
	lucro_usd NUMERIC(18, 2) NOT NULL, 
	orcamento_brl NUMERIC(18, 2), 
	receita_brl NUMERIC(18, 2), 
	lucro_brl NUMERIC(18, 2) NOT NULL, 
	popularidade DOUBLE, 
	nota_tmdb DOUBLE, 
	qtd_tmdb INTEGER, 
	nota_imdb DOUBLE, 
	qtd_imdb INTEGER, 
	CONSTRAINT pk_fact_movies_performance PRIMARY KEY (sk_movie_id), 
	CONSTRAINT fk_fact_movies_performance_sk_movie_id_dim_movies FOREIGN KEY(sk_movie_id) REFERENCES dim_movies (sk_movie_id) ON DELETE CASCADE
);
CREATE TABLE movie_reviews (
	id INTEGER NOT NULL, 
	sk_movie_review_id VARCHAR(64) NOT NULL, 
	sk_movie_id VARCHAR(64) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	rating DOUBLE NOT NULL, 
	text VARCHAR(4000) NOT NULL, 
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
	CONSTRAINT pk_movie_reviews PRIMARY KEY (id), 
	CONSTRAINT ck_movie_reviews_rating_range CHECK (rating >= 0 AND rating <= 10), 
	CONSTRAINT fk_movie_reviews_sk_movie_id_dim_movies FOREIGN KEY(sk_movie_id) REFERENCES dim_movies (sk_movie_id) ON DELETE CASCADE
);
CREATE INDEX ix_dim_movies_ano_lancamento ON dim_movies (ano_lancamento);
CREATE UNIQUE INDEX ix_dim_movies_id_filme ON dim_movies (id_filme);
CREATE INDEX ix_dim_movies_titulo ON dim_movies (titulo);
CREATE INDEX ix_dim_people_nome_pessoa ON dim_people (nome_pessoa);
CREATE INDEX ix_bridge_movie_person_sk_person_id ON bridge_movie_person (sk_person_id);
CREATE INDEX ix_movie_reviews_sk_movie_id ON movie_reviews (sk_movie_id);
CREATE UNIQUE INDEX ix_movie_reviews_sk_movie_review_id ON movie_reviews (sk_movie_review_id);
