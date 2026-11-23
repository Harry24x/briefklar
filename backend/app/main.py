"""FastAPI entry point."""

import logging
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.agent.graph import run_agent
from app.config import get_settings
from app.db import get_session
from app.letter.calendar import make_ics
from app.letter.extract import ExtractionError, LetterFields, extract_fields
from app.letter.mask import mask
from app.llm import LLMError
from app.rag.pipeline import ask
from app.ratelimit import DailyLimiter, enforce
from app.schemas import AskRequest, AskResponse, HealthResponse, LetterRequest, LetterResponse

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
letter_limiter = DailyLimiter(limit=5)


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


@app.post("/letter", response_model=LetterResponse)
def letter_endpoint(
    body: LetterRequest, request: Request, session: Annotated[Session, Depends(get_session)]
) -> LetterResponse:
    """Explain a pasted letter. The raw text is masked first and never logged or stored."""
    enforce(letter_limiter, request)
    masked = mask(body.text)
    try:
        fields = extract_fields(masked.text)
    except (ExtractionError, LLMError) as exc:
        logger.warning("letter extraction failed")  # no letter content in logs
        raise HTTPException(
            status_code=502, detail="Could not read this letter. Please try again."
        ) from exc
    state = run_agent(session, fields=fields, lang="en")
    logger.info("letter tools=%s refused=%s", state.get("tool_log"), state["response"].refused)
    return LetterResponse(
        fields=fields,
        explanation=state["response"],
        ics_available=fields.deadline is not None,
        masked_items=masked.counts,
    )


@app.post("/letter/ics")
def letter_ics(fields: LetterFields) -> Response:
    if fields.deadline is None:
        raise HTTPException(status_code=422, detail="This letter has no deadline.")
    ics = make_ics(
        fields.deadline, f"Deadline: {fields.letter_type}", "; ".join(fields.required_actions)
    )
    return Response(
        content=ics,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="briefklar-deadline.ics"'},
    )
