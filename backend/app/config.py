"""App settings, read from environment variables (or a .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://briefklar:briefklar@localhost:5432/briefklar"

    groq_api_key: str = ""
    # Groq shut down llama-3.3-70b-versatile / llama-3.1-8b-instant on 16.08.2026 and recommends
    # these replacements. The fallback model is also used for query rewrite and the eval judge.
    groq_model: str = "openai/gpt-oss-120b"
    groq_fallback_model: str = "openai/gpt-oss-20b"

    embed_model: str = "intfloat/multilingual-e5-small"
    embed_dim: int = 384
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"  # ~470 MB, multilingual
    reranker_enabled: bool = True
    query_rewrite: bool = False
    retrieval_mode: str = "hybrid+rerank"  # vector | hybrid | hybrid+rerank
    # Sufficiency thresholds, tuned on the eval set (see eval/run_eval.py --tune).
    # -1.0 tuned on the eval set (22.11.2026): keeps all answerable questions with a relevant
    # chunk and refuses 8/10 unanswerable ones. See eval/NOTES.md.
    min_score: float = -1.0  # best re-ranker logit
    # e5 cosine similarities are squeezed into ~0.82-0.91 for relevant AND unrelated questions,
    # so no vector threshold separates them; refusals rely on the re-ranker.
    min_vector_sim: float = 0.0  # best cosine similarity, used when no re-ranker runs

    # Comma-separated list, e.g. "http://localhost:3000,https://briefklar.vercel.app"
    cors_origins: str = "http://localhost:3000"

    langfuse_enabled: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
