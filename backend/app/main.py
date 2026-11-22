"""FastAPI entry point."""

import logging
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.rag.pipeline import ask
from app.ratelimit import DailyLimiter, enforce
from app.schemas import AskRequest, AskResponse, HealthResponse

# Never log request bodies: they can contain personal data from letters.
logger = logging.getLogger("briefklar")
settings = get_settings()

app = FastAPI(
    title="BriefKlar API",
    description="Explains German official letters and rules with official sources.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

ask_limiter = DailyLimiter(limit=20)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/ask", response_model=AskResponse)
def ask_endpoint(
    body: AskRequest, request: Request, session: Annotated[Session, Depends(get_session)]
) -> AskResponse:
    enforce(ask_limiter, request)
    trace = ask(session, body.question, body.lang)
    logger.info(
        "ask mode=%s refused=%s best=%.3f",
        trace.retrieval.mode,
        trace.response.refused,
        trace.retrieval.best_score,
    )
    return trace.response
