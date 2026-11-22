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
