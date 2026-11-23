"""Pydantic request/response models for the API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DISCLAIMER = "General information from official sources, not legal advice."


class HealthResponse(BaseModel):
    status: str


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    lang: Literal["en", "de"] | None = None


class SourceRef(BaseModel):
    n: int  # the [n] number used in the answer
    url: str
    title: str
    heading: str
    fetched_at: datetime | None  # shown as "source checked on"


class AskResponse(BaseModel):
    answer: str
    citations: list[int]
    sources: list[SourceRef]
    next_steps: list[str]
    confidence: Literal["low", "medium", "high"]
    refused: bool
    disclaimer: str = DISCLAIMER


class LetterRequest(BaseModel):
    text: str = Field(min_length=20, max_length=8000)


class LetterResponse(BaseModel):
    fields: "LetterFields"
    explanation: AskResponse
    ics_available: bool
    masked_items: dict[str, int]  # how many items of each kind were masked, e.g. {"NAME": 1}


from app.letter.extract import LetterFields  # noqa: E402  (avoid a circular import)

LetterResponse.model_rebuild()
