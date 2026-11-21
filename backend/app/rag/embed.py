"""Embedding helpers for intfloat/multilingual-e5-small (384 dimensions, runs on CPU).

e5 models are trained with prefixes: documents get "passage: ", search queries get "query: ".
Leaving the prefixes out noticeably lowers retrieval quality.
"""

from functools import lru_cache
from typing import TYPE_CHECKING

from app.config import get_settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


@lru_cache
def get_model() -> "SentenceTransformer":
    # Imported lazily so the API and tests start without loading PyTorch.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(get_settings().embed_model, device="cpu")


def embed_passages(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    vectors = get_model().encode(
        [f"passage: {t}" for t in texts],
        batch_size=batch_size,
        normalize_embeddings=True,  # unit length, so cosine similarity = dot product
        show_progress_bar=len(texts) > batch_size,
    )
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    vector = get_model().encode(f"query: {text}", normalize_embeddings=True)
    return vector.tolist()
