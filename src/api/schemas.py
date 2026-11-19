"""Pydantic v2 request and response schemas for the HTTP API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_SQL_LENGTH = 8_000


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ChallengeSummaryResponse(BaseModel):
    code: str
    module: str
    title: str
    description: str
    difficulty: int


class SubmitSolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roblox_user_id: int = Field(gt=0)
    sql: str = Field(min_length=1, max_length=MAX_SQL_LENGTH)


class SubmitSolutionResponse(BaseModel):
    passed: bool
    execution_ms: int | None
    message: str
    columns: list[str] = Field(default_factory=list)
    preview_rows: list[list[str]] = Field(default_factory=list)


class CompletedChallengeResponse(BaseModel):
    code: str
    completed_at: datetime
    best_ms: int


class PlayerProgressResponse(BaseModel):
    roblox_user_id: int
    completed: list[CompletedChallengeResponse]


class ErrorResponse(BaseModel):
    detail: str
