from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Route(StrEnum):
    """Conversational routing decisions."""

    CONTINUE = "CONTINUE"
    COLLECT_IDENTITY = "COLLECT_IDENTITY"
    COMPLETE = "COMPLETE"
    ESCALATE = "ESCALATE"


class TurnRequest(BaseModel):
    """Input contract for POST /turn."""

    conversation_id: str = Field(
        ...,
        description="Unique identifier for the telephony session / call.",
    )
    text: str = Field(
        ...,
        description="User speech transcript for the current turn.",
    )

    @field_validator("conversation_id", "text")
    @classmethod
    def reject_blank_strings(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or whitespace only")
        return stripped


class TurnResponse(BaseModel):
    """Output contract for POST /turn."""

    turn_id: str = Field(
        ...,
        description="Unique identifier for this turn execution.",
    )
    route: Route = Field(
        ...,
        description="Next conversational route.",
    )
    text: str = Field(
        ...,
        description="Conversational response text for TTS.",
    )


class HealthResponse(BaseModel):
    """Output contract for GET /health."""

    status: str = "ok"
    version: str = "0.2.0"
