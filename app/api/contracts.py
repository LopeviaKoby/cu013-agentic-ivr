"""Typed external HTTP contract consumed by Cally Square.

This module defines the only request and response shapes the boundary
accepts and emits. Raw DTMF may exist inside the IDENTITY_DATA request
model and nowhere else: it is never logged, persisted or echoed.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.conversation.engine import Route


class TranscriptTurn(BaseModel):
    """ASR transcript turn; only the transcript itself is required."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transcript: str = Field(min_length=1)
    asr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    channel: Literal["voice"] = "voice"


class IdentityDataSlots(BaseModel):
    """Raw DTMF slots; transient boundary data only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(min_length=1)


class IdentityDataTurn(BaseModel):
    """Observed IDENTITY_DATA event carrying raw DTMF."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["IDENTITY_DATA"]
    slots: IdentityDataSlots
    channel: Literal["voice"] = "voice"


TurnRequest = TranscriptTurn | IdentityDataTurn


class TurnResponse(BaseModel):
    """Fields Cally Square consumes plus the internal turn correlation id."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str
    route: Route
    turn_id: str = Field(min_length=1)


class ErrorCode(StrEnum):
    """Stable boundary error taxonomy."""

    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    DEPENDENCY_TIMEOUT = "dependency_timeout"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    INTERNAL = "internal"


class ErrorBody(BaseModel):
    """Safe error payload: a code and a static message, never request data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ErrorCode
    message: str


class ErrorResponse(BaseModel):
    """Boundary error envelope; the final XCALLY error shape is still open."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error: ErrorBody
