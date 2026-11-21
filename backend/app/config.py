"""App settings, read from environment variables (or a .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://briefklar:briefklar@localhost:5432/briefklar"

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_fallback_model: str = "llama-3.1-8b-instant"

    embed_model: str = "intfloat/multilingual-e5-small"
    embed_dim: int = 384
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_enabled: bool = True
    query_rewrite: bool = False
    min_score: float = 0.0

    # Comma-separated list, e.g. "http://localhost:3000,https://briefklar.vercel.app"
    cors_origins: str = "http://localhost:3000"

    langfuse_enabled: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
