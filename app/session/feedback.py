"""Narrow waiting-feedback composer seam and its deterministic validation.

The composer is a separate, narrow capability: it receives a closed PII-safe
projection of the pending operation and may produce only one short spoken
message. It can never decide the next step, mutate business state, authorize,
dispatch or touch identity. The runtime validates and persists only
admissible text; a timeout, invalid output or inadmissible text yields
``message=null`` with business state untouched.
"""

import re
import unicodedata
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.session.actions import Action
from app.session.text import normalize_message

__all__ = [
    "MAX_FEEDBACK_MESSAGE_CHARS",
    "FeedbackObservationKind",
    "FeedbackOperationState",
    "NullPollingFeedbackComposer",
    "PollingFeedbackComposer",
    "PollingFeedbackRequest",
    "validate_feedback_message",
]


class FeedbackOperationState(StrEnum):
    """Wire projection of the operation while polling is still open."""

    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"


class FeedbackObservationKind(StrEnum):
    """Closed observation kinds the composer may be told about."""

    PENDING = "PENDING"
    UNRECOGNIZED = "UNRECOGNIZED"
    ERROR = "ERROR"


class PollingFeedbackRequest(BaseModel):
    """Closed PII-safe composer input; nothing else may ever be sent.

    It excludes transcript, caller/assistant textual memory, document, entry
    date, identity identifiers or timestamps, ``operation_id``, RD bodies,
    raw unknown statuses, password, email and spontaneous PII.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Action
    goal_revision: int = Field(ge=0)
    confirmation_obtained: bool
    operation_state: FeedbackOperationState
    observation_kind: FeedbackObservationKind
    poll_sequence: int = Field(gt=0)
    observations_used: int = Field(ge=0)
    observation_limit: int = Field(gt=0)
    previous_messages: tuple[str, ...] = Field(default=(), max_length=2)


class PollingFeedbackComposer(Protocol):
    """One narrow capability: a message, or nothing."""

    async def compose(self, request: PollingFeedbackRequest) -> str | None: ...


class NullPollingFeedbackComposer:
    """No composer wired: the runtime simply speaks nothing while polling."""

    async def compose(self, request: PollingFeedbackRequest) -> str | None:
        return None


MAX_FEEDBACK_MESSAGE_CHARS = 240

_PROHIBITED_PATTERNS = (
    re.compile(r"%"),
    re.compile(r"\b\d+\s*(?:min|mins|minuto|minutos|seg|segundo|segundos|hora|horas)\b"),
    re.compile(
        r"\b(?:rd|ad|tivit|orchestrator|cally|xcally|sendmail|firestore|backend|api|servidor)\b"
    ),
    re.compile(
        r"\b(?:confirmad[oa]s?|exitos[oa]s?|completad[oa]s?|terminad[oa]s?|finalizad[oa]s?|"
        r"termin(?:a|an|ar|ara|aran|aron|o|ando)|fallad[oa]s?|fallo|falló|enviad[oa]s?|"
        r"entregad[oa]s?|list[oa]s?|casi)\b"
    ),
)


def _fold(text: str) -> str:
    """Casefold and strip accents so prohibited patterns cannot be evaded."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def validate_feedback_message(value: str | None) -> str | None:
    """Normalize and accept only a short, PII-safe, non-committal message."""
    normalized = normalize_message(value)
    if normalized is None or not normalized:
        return None
    if len(normalized) > MAX_FEEDBACK_MESSAGE_CHARS:
        return None
    folded = _fold(normalized)
    if any(pattern.search(folded) for pattern in _PROHIBITED_PATTERNS):
        return None
    return normalized
