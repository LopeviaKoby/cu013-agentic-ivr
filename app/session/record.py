"""Durable session contract for the Thin Firestore Session Repository.

The record is small, semantic and closed: only these fields may reach
Firestore. Raw DTMF values, tools, tool schemas, SDK clients and LangGraph
internals never belong here.
"""

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

SCHEMA_VERSION: Literal[1] = 1


class Action(StrEnum):
    """Account actions authorized for the first slice."""

    RESET_PASSWORD = "RESET_PASSWORD"
    UNLOCK_ACCOUNT = "UNLOCK_ACCOUNT"


class OperationStatus(StrEnum):
    """Durable lifecycle of an authorized external operation."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class PendingOperation(BaseModel):
    """Durable trace of an operation authorized around an external side effect."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1)
    action: Action
    status: OperationStatus = OperationStatus.PENDING


class SessionRecord(BaseModel):
    """Small semantic session state; the closed document whitelist."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = SCHEMA_VERSION
    conversation_id: str = Field(min_length=1)
    turn_count: int = Field(ge=0)
    revision: int = Field(ge=0)
    identity_validated: bool
    requested_action: Action | None
    pending_operation: PendingOperation | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @classmethod
    def new(cls, conversation_id: str, *, now: datetime) -> Self:
        """Create the semantic record for a conversation without durable state."""
        return cls(
            conversation_id=conversation_id,
            turn_count=0,
            revision=0,
            identity_validated=False,
            requested_action=None,
            pending_operation=None,
            created_at=now,
            updated_at=now,
        )


def session_record_to_document(record: SessionRecord) -> dict[str, object]:
    """Map a record to the exact, closed Firestore document whitelist."""
    pending_operation = record.pending_operation
    return {
        "schema_version": record.schema_version,
        "conversation_id": record.conversation_id,
        "turn_count": record.turn_count,
        "revision": record.revision,
        "identity_validated": record.identity_validated,
        "requested_action": (
            record.requested_action.value if record.requested_action is not None else None
        ),
        "pending_operation": (
            {
                "operation_id": pending_operation.operation_id,
                "action": pending_operation.action.value,
                "status": pending_operation.status.value,
            }
            if pending_operation is not None
            else None
        ),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def session_record_from_document(document: Mapping[str, object]) -> SessionRecord:
    """Validate a stored document against the closed durable contract."""
    return SessionRecord.model_validate(dict(document))
