import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import RateLimitError

from app import llm
from app.db import get_session
from app.main import app, ask_limiter
from app.rag import answer as answer_mod
from app.rag import pipeline
from app.rag.answer import LLMAnswer, check_citations, generate_answer
from app.rag.retrieve import Candidate, RetrievalResult, is_sufficient, rrf_merge, to_or_tsquery


def cand(cid: int, sim: float | None = None) -> Candidate:
    return Candidate(cid, f"https://x.de/{cid}", "T", "H", f"text {cid}", "en", None, sim)


# ---------------------------------------------------------------- retrieval ---


def test_rrf_merge_rewards_chunks_found_by_both_lists() -> None:
    vector = [cand(1, 0.9), cand(2, 0.8), cand(3, 0.7)]
    fulltext = [cand(3), cand(4), cand(1)]
    merged = rrf_merge([vector, fulltext], k=60)
    ids = [c.chunk_id for c in merged]
    # 1 is rank 1 + rank 3, 3 is rank 3 + rank 1 -> tie on top; both beat single-list hits
    assert set(ids[:2]) == {1, 3}
    assert ids[2:] == [2, 4]
    assert merged[0].rrf_score == pytest.approx(1 / 61 + 1 / 63)
    # the vector similarity is kept even if the full-text copy came first
    assert next(c for c in merged if c.chunk_id == 3).vector_sim == 0.7


def test_threshold_refuses_below_min_score() -> None:
    assert is_sufficient(0.42, threshold=0.4)
    assert not is_sufficient(0.12, threshold=0.4)


def test_or_tsquery_drops_stopwords() -> None:
    assert to_or_tsquery("How many hours can I work as a Werkstudent?") == (
        "many | hours | work | werkstudent"
    )


# ---------------------------------------------------------------- citations ---


def test_citation_check_accepts_valid_answer() -> None:
    a = LLMAnswer(answer="You may work 20 hours a week [1][2].", citations=[1, 2])
    assert check_citations(a, n_sources=5) == []


def test_citation_check_catches_missing_and_invented_numbers() -> None:
    no_cite = LLMAnswer(answer="You may work 20 hours.", citations=[])
    assert check_citations(no_cite, 5)
    unlisted = LLMAnswer(answer="Fact [2].", citations=[1])
    assert any("not listed" in p for p in check_citations(unlisted, 5))
    invented = LLMAnswer(answer="Fact [7].", citations=[7])
    assert any("do not exist" in p for p in check_citations(invented, 5))


def test_generate_answer_regenerates_once_then_refuses(monkeypatch) -> None:
    bad = json.dumps({"answer": "No sources here.", "citations": [], "confidence": "high"})
    calls: list[int] = []

    def fake_chat(messages, **kwargs):
        calls.append(1)
        return llm.LLMResult(content=bad, model="m")

    monkeypatch.setattr(answer_mod, "chat_json", fake_chat)
    outcome = generate_answer("q?", "en", [cand(1)])
    assert outcome.answer is None and len(calls) == 2
    assert outcome.failure and outcome.failure.startswith("citation_check")


# ---------------------------------------------------------------- llm ---


def test_llm_falls_back_to_small_model_on_429(monkeypatch) -> None:
    used: list[str] = []
    response = httpx.Response(429, request=httpx.Request("POST", "https://x"))

    def create(model, **kwargs):
        used.append(model)
        if model == "big":
            raise RateLimitError("rate limited", response=response, body=None)
        msg = SimpleNamespace(content='{"ok": true}')
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, "get_client", lambda: client)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    settings = SimpleNamespace(groq_model="big", groq_fallback_model="small")
    monkeypatch.setattr(llm, "get_settings", lambda: settings)

    result = llm.chat_json([{"role": "user", "content": "hi"}])
    assert result.model == "small" and used == ["big", "big", "small"]
    with pytest.raises(llm.LLMError):
        llm.chat_json([{"role": "user", "content": "hi"}], allow_fallback=False)


# ---------------------------------------------------------------- /ask ---


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_session] = lambda: None
    ask_limiter._counts.clear()
    chunks = [cand(1, 0.91), cand(2, 0.85)]

    def fake_retrieve(session, query, mode, extra_queries=None):
        return RetrievalResult(query, mode, chunks, best_score=0.91, sufficient=True)

    def fake_chat(messages, **kwargs):
        body = {
            "answer": "Students may work 140 full days a year [1].",
            "citations": [1],
            "next_steps": ["Ask your Ausländerbehörde"],
            "confidence": "high",
        }
        return llm.LLMResult(content=json.dumps(body), model="m")

    monkeypatch.setattr(pipeline, "retrieve", fake_retrieve)
    monkeypatch.setattr(answer_mod, "chat_json", fake_chat)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_ask_returns_cited_answer_and_disclaimer(client) -> None:
    r = client.post("/ask", json={"question": "How many days can I work?", "lang": "en"})
    assert r.status_code == 200
    data = r.json()
    assert data["refused"] is False
    assert data["citations"] == [1]
    assert data["sources"][0]["url"] == "https://x.de/1"
    assert "not legal advice" in data["disclaimer"]


def test_ask_refuses_when_retrieval_is_insufficient(client, monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline,
        "retrieve",
        lambda s, q, mode, extra_queries=None: RetrievalResult(
            q, mode, [cand(9, 0.3)], best_score=0.3, sufficient=False
        ),
    )
    data = client.post("/ask", json={"question": "Price of a Bratwurst in Berlin?"}).json()
    assert data["refused"] is True
    assert data["sources"][0]["url"] == "https://x.de/9"  # still points to an official page


def test_ask_validates_input_and_rate_limits(client) -> None:
    assert client.post("/ask", json={"question": "x" * 501}).status_code == 422
    ask_limiter._counts.clear()
    codes = [client.post("/ask", json={"question": "Work hours?"}).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429


def test_reasoning_model_gets_low_effort_and_empty_reply_is_retried(monkeypatch) -> None:
    calls: list[dict] = []

    def create(model, **kwargs):
        calls.append({"model": model, **kwargs})
        text = "" if len(calls) == 1 else '{"ok": true}'  # first reply empty, then fine
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, "get_client", lambda: client)
    settings = SimpleNamespace(groq_model="openai/gpt-oss-120b", groq_fallback_model="x")
    monkeypatch.setattr(llm, "get_settings", lambda: settings)

    result = llm.chat_json(
        [{"role": "user", "content": "hi"}], max_tokens=100, allow_fallback=False
    )
    assert result.content == '{"ok": true}' and len(calls) == 2
    assert calls[0]["extra_body"] == {"reasoning_effort": "low"}
    assert calls[0]["max_tokens"] == 100 + llm.REASONING_TOKEN_BUDGET
