"""Groq chat client (OpenAI-compatible) with retry and model fallback.

- Every call asks for JSON output and returns the raw JSON string.
- On HTTP 429 (rate limit) we wait briefly and retry once; if it still fails we switch to the
  smaller fallback model (openai/gpt-oss-20b), unless the caller disabled fallback
  (the eval does this, so its numbers always come from the model we claim).
- `record_prompts()` lets the eval capture every prompt sent, for the PII leak check.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

from app.config import get_settings

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# gpt-oss models reason before answering, and those hidden tokens count against max_tokens.
# Low effort keeps latency and token use down; the extra budget stops empty answers.
REASONING_MODELS = ("openai/gpt-oss",)
REASONING_TOKEN_BUDGET = 1024

_recorded: list[str] | None = None


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    content: str
    model: str


@lru_cache
def get_client() -> OpenAI:
    settings = get_settings()
    if not settings.groq_api_key:
        raise LLMError("GROQ_API_KEY is not set")
    # max_retries=0: we handle retries ourselves so fallback behaviour is predictable.
    return OpenAI(api_key=settings.groq_api_key, base_url=GROQ_BASE_URL, max_retries=0, timeout=30)


@contextmanager
def record_prompts() -> Iterator[list[str]]:
    """Collect the text of every message sent to the LLM inside this block."""
    global _recorded
    _recorded = []
    try:
        yield _recorded
    finally:
        _recorded = None


def _retry_after(exc: RateLimitError, default: float = 5.0) -> float:
    try:
        return float(exc.response.headers.get("retry-after", default))
    except (AttributeError, TypeError, ValueError):
        return default


def chat_json(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 800,
    allow_fallback: bool = True,
) -> LLMResult:
    settings = get_settings()
    primary = model or settings.groq_model
    if _recorded is not None:
        _recorded.extend(m["content"] for m in messages)

    attempts = [primary, primary]
    if allow_fallback and settings.groq_fallback_model != primary:
        attempts.append(settings.groq_fallback_model)

    last_error: Exception | None = None
    for i, current in enumerate(attempts):
        reasoning = current.startswith(REASONING_MODELS)
        try:
            response = get_client().chat.completions.create(
                model=current,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens + (REASONING_TOKEN_BUDGET if reasoning else 0),
                response_format={"type": "json_object"},
                extra_body={"reasoning_effort": "low"} if reasoning else None,
            )
            content = response.choices[0].message.content or ""
            if not content.strip():  # e.g. the token budget was used up by reasoning
                last_error = LLMError(f"{current} returned an empty message")
                continue
            return LLMResult(content=content, model=current)
        except RateLimitError as exc:
            last_error = exc
            if i == 0:  # first 429: wait (capped) and try the same model again
                time.sleep(min(_retry_after(exc), 20.0))
        except (APIConnectionError, APITimeoutError) as exc:
            last_error = exc
            time.sleep(1.0)
    raise LLMError(f"LLM call failed after {len(attempts)} attempts: {last_error}")
