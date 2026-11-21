-- BriefKlar schema. Idempotent: safe to run more than once.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sources (
    id           SERIAL PRIMARY KEY,
    url          TEXT NOT NULL UNIQUE,
    title        TEXT,
    lang         TEXT,
    fetched_at   TIMESTAMPTZ,
    content_hash TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    id           SERIAL PRIMARY KEY,
    source_id    INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    heading_path TEXT,
    text         TEXT NOT NULL,
    lang         TEXT,
    embedding    vector(384),
    -- 'simple' config: no stemming, works for English and German alike.
    tsv          tsvector GENERATED ALWAYS AS (
                     to_tsvector('simple', coalesce(heading_path, '') || ' ' || text)
                 ) STORED,
    UNIQUE (source_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS chunks_tsv_gin
    ON chunks USING gin (tsv);
