"""Retrieval: find the 5 chunks that best answer a question.

Three modes, so the eval can compare them:
  vector         semantic search only (pgvector cosine distance, HNSW index)
  hybrid         vector top-20 + full-text top-20, merged with Reciprocal Rank Fusion
  hybrid+rerank  hybrid, then a cross-encoder re-scores the merged list and we keep the top 5

Why hybrid? Vector search understands meaning ("part-time job" ~ "Nebenjob") but can miss
exact terms such as "§ 16b AufenthG" or "Rundfunkbeitrag". Full-text search is the opposite.
RRF combines both rankings without having to calibrate their very different score scales.

Finally a sufficiency check decides whether the best chunk is good enough to answer at all;
if not, we refuse instead of letting the LLM guess.
"""

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.rag.embed import embed_query

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

Mode = Literal["vector", "hybrid", "hybrid+rerank"]
MODES: tuple[Mode, ...] = ("vector", "hybrid", "hybrid+rerank")

CANDIDATES_PER_LIST = 20
TOP_K = 5
RRF_K = 60  # standard constant from the RRF paper; dampens the weight of the very top ranks


@dataclass(frozen=True)
class Candidate:
    chunk_id: int
    url: str
    title: str
    heading_path: str
    text: str
    lang: str
    fetched_at: datetime | None
    vector_sim: float | None = None  # cosine similarity, 1 = identical
    rrf_score: float | None = None
    rerank_score: float | None = None  # cross-encoder relevance (logit, higher = better)


@dataclass
class RetrievalResult:
    query: str
    mode: Mode
    chunks: list[Candidate]  # final top-k, best first
    best_score: float  # the score the sufficiency check used
    sufficient: bool
    queries_used: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- search ---

_SELECT = """
    SELECT c.id, s.url, coalesce(s.title, ''), coalesce(c.heading_path, ''), c.text,
           coalesce(c.lang, ''), s.fetched_at{extra}
    FROM chunks c JOIN sources s ON s.id = c.source_id
"""


def _row_to_candidate(row: tuple, vector_sim: float | None = None) -> Candidate:
    return Candidate(*row[:7], vector_sim=vector_sim)


def vector_search(session: Session, query: str, k: int = CANDIDATES_PER_LIST) -> list[Candidate]:
    """Nearest neighbours by cosine distance (`<=>`). Similarity = 1 - distance."""
    qvec = str(embed_query(query))
    sql = (
        _SELECT.format(extra=", 1 - (c.embedding <=> CAST(:q AS vector)) AS sim")
        + """
        WHERE c.embedding IS NOT NULL
        ORDER BY c.embedding <=> CAST(:q AS vector)
        LIMIT :k
    """
    )
    rows = session.execute(text(sql), {"q": qvec, "k": k}).all()
    return [_row_to_candidate(r, vector_sim=float(r[7])) for r in rows]


# Small EN + DE stopword list: with OR-matching, words like "the" or "ich" would match everything.
STOPWORDS = set(
    """a an and are as at be can do does for from have how i if in is it me my of on or
    should the to what when where which who why will with you your
    am auf aus bei bin bis das dass dem den der des die du ein eine einen einer es für
    hat ich ihr im ist kann mein meine mit muss nach nicht oder sich sie sind und von
    was wie wenn wer wir wo zu zum zur""".split()
)


def to_or_tsquery(query: str) -> str:
    """Turn a natural question into an OR tsquery: 'work & hours' would be too strict."""
    words = re.findall(r"[\wäöüß§]+", query.lower())
    terms = [w for w in words if w not in STOPWORDS and len(w) > 1]
    return " | ".join(dict.fromkeys(terms))  # dedupe, keep order


def fulltext_search(session: Session, query: str, k: int = CANDIDATES_PER_LIST) -> list[Candidate]:
    tsquery = to_or_tsquery(query)
    if not tsquery:
        return []
    sql = (
        _SELECT.format(extra="")
        + """
        WHERE c.tsv @@ to_tsquery('simple', :q)
        ORDER BY ts_rank_cd(c.tsv, to_tsquery('simple', :q)) DESC
        LIMIT :k
    """
    )
    rows = session.execute(text(sql), {"q": tsquery, "k": k}).all()
    return [_row_to_candidate(r) for r in rows]


# ---------------------------------------------------------------- fusion ---


def rrf_merge(ranked_lists: list[list[Candidate]], k: int = RRF_K) -> list[Candidate]:
    """Reciprocal Rank Fusion: score(d) = sum over lists of 1 / (k + rank of d in that list).

    Only ranks matter, not raw scores, so cosine similarities and ts_rank values can be
    combined without normalising them. A chunk found by both searches gets two contributions.
    """
    scores: dict[int, float] = {}
    best: dict[int, Candidate] = {}
    for ranked in ranked_lists:
        for rank, cand in enumerate(ranked, start=1):
            scores[cand.chunk_id] = scores.get(cand.chunk_id, 0.0) + 1.0 / (k + rank)
            # keep the version that carries a vector similarity, if any list had one
            if cand.chunk_id not in best or (
                best[cand.chunk_id].vector_sim is None and cand.vector_sim is not None
            ):
                best[cand.chunk_id] = cand
    ordered = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    return [replace(best[cid], rrf_score=scores[cid]) for cid in ordered]


# ---------------------------------------------------------------- re-rank ---


@lru_cache
def get_reranker() -> "CrossEncoder":
    from sentence_transformers import CrossEncoder

    return CrossEncoder(get_settings().reranker_model, device="cpu", max_length=512)


def rerank(query: str, candidates: list[Candidate], top_k: int = TOP_K) -> list[Candidate]:
    """A cross-encoder reads (question, chunk) together, so it judges relevance much better
    than comparing two separate embeddings. It is slower, so we only run it on ~30 candidates.
    """
    if not candidates:
        return []
    pairs = [(query, f"{c.heading_path}\n{c.text}") for c in candidates]
    # mmarco-mMiniLMv2 returns raw logits (about -7 .. +11 on our data), not probabilities.
    # Only the ranking and the MIN_SCORE threshold use them, so no calibration is needed.
    scores = get_reranker().predict(pairs)
    scored = [replace(c, rerank_score=float(s)) for c, s in zip(candidates, scores, strict=True)]
    return sorted(scored, key=lambda c: c.rerank_score or 0.0, reverse=True)[:top_k]


# ---------------------------------------------------------------- pipeline ---


def is_sufficient(best_score: float, threshold: float) -> bool:
    return best_score >= threshold


def retrieve(
    session: Session,
    query: str,
    mode: Mode = "hybrid+rerank",
    extra_queries: list[str] | None = None,
    top_k: int = TOP_K,
) -> RetrievalResult:
    """Run one retrieval mode. `extra_queries` come from the optional query rewrite."""
    settings = get_settings()
    queries = [query, *(extra_queries or [])]

    if mode == "vector":
        lists = [vector_search(session, q) for q in queries]
        merged = rrf_merge(lists) if len(lists) > 1 else lists[0]
        top = merged[:top_k]
        best = max((c.vector_sim or 0.0 for c in top), default=0.0)
        threshold = settings.min_vector_sim
    else:
        lists = []
        for q in queries:
            lists.append(vector_search(session, q))
            lists.append(fulltext_search(session, q))
        merged = rrf_merge(lists)
        if mode == "hybrid+rerank" and settings.reranker_enabled:
            top = rerank(query, merged[: CANDIDATES_PER_LIST + 10], top_k)
            best = (top[0].rerank_score or 0.0) if top else 0.0
            threshold = settings.min_score
        else:
            top = merged[:top_k]
            best = max((c.vector_sim or 0.0 for c in top), default=0.0)
            threshold = settings.min_vector_sim

    return RetrievalResult(
        query=query,
        mode=mode,
        chunks=top,
        best_score=best,
        sufficient=bool(top) and is_sufficient(best, threshold),
        queries_used=queries,
    )
