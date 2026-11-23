import json
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import llm
from app.agent import graph as agent_graph
from app.db import get_session
from app.letter import extract as extract_mod
from app.letter.calendar import make_ics
from app.letter.extract import LetterFields, extract_fields
from app.letter.mask import mask
from app.main import app, letter_limiter
from app.rag import answer as answer_mod
from app.rag.retrieve import Candidate, RetrievalResult

LETTER = """Stadt Musterstadt – Ausländerbehörde
Aktenzeichen: ABH-2026-04711

Frau Sofia Fiktiva
geb. 12.03.2001
Lindenweg 4
12345 Musterstadt

Sehr geehrte Frau Fiktiva,
bitte zahlen Sie 93,00 Euro bis zum 15.12.2026 auf DE02 1203 0000 0000 2020 51.
Rückfragen: sofia.fiktiva@example.com oder 0151 23456789, Steuer-ID: 12345678901."""

FIELDS = {
    "sender": "Stadt Musterstadt – Ausländerbehörde",
    "letter_type": "Aufforderung",
    "letter_date": "2026-11-14",
    "deadline": "2026-12-15",
    "amount_eur": 93.0,
    "required_actions": ["Pay 93 euros by 15.12.2026"],
    "summary_plain_english": "The immigration office asks you to pay a fee of 93 euros.",
}


# ---------------------------------------------------------------- masking ---


@pytest.mark.parametrize(
    "secret",
    [
        "Sofia Fiktiva",
        "Fiktiva",
        "12.03.2001",
        "Lindenweg 4",
        "ABH-2026-04711",
        "DE02 1203 0000 0000 2020 51",
        "sofia.fiktiva@example.com",
        "0151 23456789",
        "12345678901",
    ],
)
def test_every_pii_pattern_is_masked(secret: str) -> None:
    assert secret not in mask(LETTER).text


def test_masking_keeps_dates_amounts_and_normal_words() -> None:
    text = mask(LETTER).text
    for keep in ["15.12.2026", "93,00 Euro", "Ausländerbehörde", "Sehr geehrte Frau", "Rückfragen"]:
        assert keep in text
    assert mask("Die Frist endet am 01.12.2026. Bitte zahlen Sie 55,08 Euro.").mapping == {}


def test_repeated_surname_reuses_the_same_placeholder() -> None:
    result = mask("Frau Sofia Fiktiva\n\nSehr geehrte Frau Fiktiva,")
    assert result.text.count("[NAME_1]") == 2 and "[NAME_2]" not in result.text


# ---------------------------------------------------------------- fields ---


def test_letter_fields_accept_german_formats() -> None:
    f = LetterFields.model_validate(
        {**FIELDS, "letter_date": "14.11.2026", "deadline": "15.12.2026", "amount_eur": "1.093,50"}
    )
    assert f.deadline == date(2026, 12, 15) and f.amount_eur == 1093.5


def test_letter_fields_reject_deadline_before_letter_date_and_bad_amount() -> None:
    with pytest.raises(ValidationError, match="before letter_date"):
        LetterFields.model_validate({**FIELDS, "deadline": "2026-11-01"})
    with pytest.raises(ValidationError, match="amount_eur"):
        LetterFields.model_validate({**FIELDS, "amount_eur": "ninety"})


def test_extract_retries_once_with_the_validation_error(monkeypatch) -> None:
    replies = [json.dumps({**FIELDS, "deadline": "2026-11-01"}), json.dumps(FIELDS)]
    seen: list[list[dict]] = []

    def fake_chat(messages, **kwargs):
        seen.append(messages)
        return llm.LLMResult(content=replies[len(seen) - 1], model="m")

    monkeypatch.setattr(extract_mod, "chat_json", fake_chat)
    fields = extract_fields("masked letter")
    assert fields.deadline == date(2026, 12, 15) and len(seen) == 2
    assert "before letter_date" in seen[1][-1]["content"]  # the error was shown to the model


# ---------------------------------------------------------------- calendar ---


def test_ics_has_all_day_event_and_two_reminders() -> None:
    ics = make_ics(date(2026, 12, 15), "Deadline: Aufforderung", "Pay 93 euros")
    assert "DTSTART;VALUE=DATE:20261215" in ics
    assert "TRIGGER:-P1W" in ics and "TRIGGER:-P1D" in ics


# ---------------------------------------------------------------- agent + API ---


def chunk(cid: int) -> Candidate:
    return Candidate(cid, f"https://x.de/{cid}", "T", "H", f"text {cid}", "de", None, 0.9)


@pytest.fixture
def fake_rag(monkeypatch):
    prompts: list[str] = []

    def fake_retrieve(session, query, mode, extra_queries=None):
        return RetrievalResult(query, mode, [chunk(1), chunk(2)], best_score=4.0, sufficient=True)

    def fake_chat(messages, **kwargs):
        prompts.extend(m["content"] for m in messages)
        body = {
            "answer": "Fees for a residence permit are set by law [1].",
            "citations": [1],
            "next_steps": [],
            "confidence": "medium",
        }
        return llm.LLMResult(content=json.dumps(body), model="m")

    def broken_planner(state):
        raise llm.LLMError("planner down")

    monkeypatch.setattr(agent_graph, "retrieve", fake_retrieve)
    monkeypatch.setattr(agent_graph, "ask_planner", broken_planner)
    monkeypatch.setattr(answer_mod, "chat_json", fake_chat)
    return prompts


def test_agent_falls_back_to_fixed_plan_and_makes_calendar(fake_rag) -> None:
    fields = LetterFields.model_validate(FIELDS)
    state = agent_graph.run_agent(None, fields=fields, lang="en")  # type: ignore[arg-type]
    assert state["kind"] == "letter"
    assert any(t.startswith("search_official_sources") for t in state["tool_log"])
    assert any(t.startswith("make_calendar_event") for t in state["tool_log"])
    assert "20261215" in (state["calendar_ics"] or "")
    assert state["response"].refused is False and state["response"].citations == [1]


def test_letter_endpoint_masks_before_any_llm_call(fake_rag, monkeypatch) -> None:
    extract_prompts: list[str] = []

    def fake_extract_chat(messages, **kwargs):
        extract_prompts.extend(m["content"] for m in messages)
        return llm.LLMResult(content=json.dumps(FIELDS), model="m")

    monkeypatch.setattr(extract_mod, "chat_json", fake_extract_chat)
    app.dependency_overrides[get_session] = lambda: None
    letter_limiter._counts.clear()
    try:
        r = TestClient(app).post("/letter", json={"text": LETTER})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert data["ics_available"] is True and data["masked_items"]["NAME"] == 1
    all_prompts = " ".join(extract_prompts + fake_rag)
    for secret in ["Fiktiva", "Lindenweg", "DE02 1203", "example.com", "12345678901"]:
        assert secret not in all_prompts


def test_letter_ics_endpoint_returns_calendar_file() -> None:
    r = TestClient(app).post("/letter/ics", json=FIELDS)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "attachment" in r.headers["content-disposition"]


def test_agent_follows_valid_planner_and_ignores_invalid_steps(fake_rag, monkeypatch) -> None:
    plan = iter(
        [
            {"tool": "finish", "args": {}},  # invalid: no search yet -> fixed plan instead
            {"tool": "search_official_sources", "args": {"query": "Gebühr Aufenthaltserlaubnis"}},
            {"tool": "make_calendar_event", "args": {"deadline": "1999-01-01"}},  # date ignored
            {"tool": "finish", "args": {}},
        ]
    )
    monkeypatch.setattr(agent_graph, "ask_planner", lambda state: next(plan))
    fields = LetterFields.model_validate(FIELDS)
    state = agent_graph.run_agent(None, fields=fields, lang="en")  # type: ignore[arg-type]
    tool_names = [entry.split("(")[0].strip() for entry in state["tool_log"]]
    assert tool_names == [
        "planner fallback",  # "finish" before any search was rejected -> fixed plan searched
        "search_official_sources",
        "search_official_sources",  # the planner's own search
        "make_calendar_event",
    ]
    assert "20261215" in state["calendar_ics"]  # deadline from the validated fields, not 1999
    assert len(state["searches"]) <= agent_graph.MAX_SEARCHES


def test_letter_always_gets_calendar_even_if_planner_finishes_early(fake_rag, monkeypatch) -> None:
    plan = iter(
        [
            {"tool": "search_official_sources", "args": {"query": "Gebühr"}},
            {"tool": "finish", "args": {}},
        ]
    )
    monkeypatch.setattr(agent_graph, "ask_planner", lambda state: next(plan))
    state = agent_graph.run_agent(None, fields=LetterFields.model_validate(FIELDS), lang="en")  # type: ignore[arg-type]
    assert "20261215" in (state["calendar_ics"] or "")
    assert state["tool_log"][-1] == "make_calendar_event(2026-12-15, safety net)"


def test_planner_cannot_repeat_the_same_search() -> None:
    done = SimpleNamespace(query="Gebühr Frist", sufficient=True, best_score=1.0)
    state = {"searches": [done], "fields": None, "calendar_ics": None}
    decision = {"tool": "search_official_sources", "args": {"query": " gebühr frist "}}
    assert not agent_graph.valid_decision(decision, state)  # type: ignore[arg-type]
