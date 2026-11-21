"""Pydantic request/response models. /ask and /letter models are added in later milestones."""

from pydantic import BaseModel

DISCLAIMER = "General information from official sources, not legal advice."


class HealthResponse(BaseModel):
    status: str
