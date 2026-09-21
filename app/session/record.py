"""Durable session contract for the Thin Firestore Session Repository.

Version 2 separates the semantic planes ADR-0010 requires without fusing
them: the conversational plan, the identity authorization with its absolute
TTL, the per-operation confirmation challenge and dispatch guard, and the
truth of the external operation. The record stays small, closed and
PII-free: only these fields reach Firestore, and raw DTMF, transcripts,
tools, tool schemas, SDK clients and LangGraph internals never belong here.

Version 1 documents migrate in memory, fail-closed, on the next legitimate
save; nothing here rewrites stored documents in bulk.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.session.actions import Action
from app.session.memory import (
    ExperimentalProcedureState,
    ExperimentalSuspendedProcedure,
    ExperimentalTurnPair,
)

__all__ = [
    "Action",
    "AuthorizedDispatch",
    "ConfirmationChallenge",
    "ConversationGoal",
    "DeliveryStatus",
    "ExternalOperation",
    "IdentityState",
    "OperationStatus",
    "SessionRecord",
    "session_record_from_document",
    "session_record_to_document",
]

SCHEMA_VERSION: Literal[2] = 2

IDENTITY_TTL = timedelta(minutes=30)

MAX_CALLER_IDENTITY_FAILURES = 3


class OperationStatus(StrEnum):
    """Durable truth of an external operation; only the boundary produces it."""

    PENDING = "pending"
    UNKNOWN = "unknown"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class DeliveryStatus(StrEnum):
    """Delivery truth of a reset; a separate fact from the reset result."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class ConversationGoal(BaseModel):
    """What the caller wants; independent of any authorization or dispatch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Action
    revision: int = Field(ge=0)


class IdentityState(BaseModel):
    """Identity plane: the validated-at authorization plus caller failures.

    The authorization is valid only for the current call and strictly before
    ``validated_at`` plus the absolute 30-minute TTL. Raw document, date of
    birth and DTMF never live here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    validated_at: AwareDatetime | None = None
    caller_failures: int = Field(default=0, ge=0)

    def expires_at(self) -> datetime | None:
        """Absolute expiry instant, or None when identity was never validated."""
        if self.validated_at is None:
            return None
        return self.validated_at + IDENTITY_TTL

    def is_valid_at(self, now: datetime) -> bool:
        """True only strictly before the absolute expiry; the boundary expires."""
        expires_at = self.expires_at()
        return expires_at is not None and now < expires_at

    def requires_handoff(self) -> bool:
        """True once caller-caused failures exhausted the accepted attempts."""
        return self.caller_failures >= MAX_CALLER_IDENTITY_FAILURES


class ConfirmationChallenge(BaseModel):
    """Active HITL challenge bound to one action, goal revision and identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    challenge_id: str = Field(min_length=1)
    action: Action
    goal_revision: int = Field(ge=0)
    identity_validated_at: AwareDatetime
    issued_at: AwareDatetime


class AuthorizedDispatch(BaseModel):
    """Durable guard persisted before any side effect may be delivered."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1)
    action: Action
    goal_revision: int = Field(ge=0)
    challenge_id: str = Field(min_length=1)
    authorized_at: AwareDatetime


class ExternalOperation(BaseModel):
    """Truth of the external operation; only boundary events change it.

    ``last_progress_feedback_at`` and ``progress_feedback_index`` are the
    minimal technical metadata the anti-silence policy persists while an
    operation is pending: when the caller was last given progress feedback
    and how many progress phrases were already used. They carry no business
    meaning and never prove a result.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1)
    action: Action
    status: OperationStatus = OperationStatus.PENDING
    delivery: DeliveryStatus | None = None
    last_progress_feedback_at: AwareDatetime | None = None
    progress_feedback_index: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _delivery_only_applies_to_reset(self) -> Self:
        if self.delivery is not None and self.action is not Action.RESET_PASSWORD:
            raise ValueError("delivery status only applies to RESET_PASSWORD")
        return self

    def is_active(self) -> bool:
        """True while the operation can still produce an external result."""
        return self.status in {OperationStatus.PENDING, OperationStatus.UNKNOWN}


class SessionRecord(BaseModel):
    """Small semantic session state; the closed document whitelist.

    The three ``experimental_*`` planes belong to Exp 0009 only: they stay
    ``None``/empty unless an explicit experimental opt-in populated them for
    a synthetic session, and documents without them keep the exact v2 shape.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = SCHEMA_VERSION
    conversation_id: str = Field(min_length=1)
    turn_count: int = Field(ge=0)
    revision: int = Field(ge=0)
    goal: ConversationGoal | None
    identity: IdentityState
    confirmation: ConfirmationChallenge | None
    dispatch: AuthorizedDispatch | None
    external_operation: ExternalOperation | None
    experimental_procedure: ExperimentalProcedureState | None = None
    experimental_suspended: ExperimentalSuspendedProcedure | None = None
    experimental_window: tuple[ExperimentalTurnPair, ...] = ()
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @classmethod
    def new(cls, conversation_id: str, *, now: datetime) -> Self:
        """Create the semantic record for a conversation without durable state."""
        return cls(
            conversation_id=conversation_id,
            turn_count=0,
            revision=0,
            goal=None,
            identity=IdentityState(),
            confirmation=None,
            dispatch=None,
            external_operation=None,
            created_at=now,
            updated_at=now,
        )

    def identity_is_valid(self, now: datetime) -> bool:
        """True while the identity authorization is inside its absolute TTL."""
        return self.identity.is_valid_at(now)


class _LegacyPendingOperationV1(BaseModel):
    """Version 1 durable operation trace; only the fields it really stored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1)
    action: Action
    status: Literal["pending", "confirmed", "failed"]


class _LegacySessionRecordV1(BaseModel):
    """Version 1 durable contract, validated with the closed v1 whitelist."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    conversation_id: str = Field(min_length=1)
    turn_count: int = Field(ge=0)
    revision: int = Field(ge=0)
    identity_validated: bool
    requested_action: Action | None
    pending_operation: _LegacyPendingOperationV1 | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


def _migrate_v1(document: Mapping[str, object]) -> SessionRecord:
    """Migrate a version 1 document fail-closed.

    Version 1 has no ``validated_at``, so a legacy ``identity_validated``
    boolean cannot demonstrate the absolute 30-minute TTL: it never becomes
    a valid authorization. A legacy ``requested_action`` becomes at most a
    conversation goal; a legacy pending operation preserves only the truth
    the old schema actually recorded. No confirmation, dispatch or external
    result is ever inferred.
    """
    legacy = _LegacySessionRecordV1.model_validate(dict(document))
    goal = (
        ConversationGoal(action=legacy.requested_action, revision=1)
        if legacy.requested_action is not None
        else None
    )
    operation = (
        ExternalOperation(
            operation_id=legacy.pending_operation.operation_id,
            action=legacy.pending_operation.action,
            status=OperationStatus(legacy.pending_operation.status),
        )
        if legacy.pending_operation is not None
        else None
    )
    return SessionRecord(
        conversation_id=legacy.conversation_id,
        turn_count=legacy.turn_count,
        revision=legacy.revision,
        goal=goal,
        identity=IdentityState(),
        confirmation=None,
        dispatch=None,
        external_operation=operation,
        created_at=legacy.created_at,
        updated_at=legacy.updated_at,
    )


def session_record_to_document(record: SessionRecord) -> dict[str, object]:
    """Map a record to the exact, closed Firestore document whitelist.

    The v2 keys are always present. The experimental Exp 0009 keys are added
    only when active, so documents without the experimental planes keep the
    exact historical v2 shape. Stored v2 documents whose operation predates
    the anti-silence metadata still validate: both fields default.
    """
    goal = record.goal
    confirmation = record.confirmation
    dispatch = record.dispatch
    operation = record.external_operation
    document: dict[str, object] = {
        "schema_version": record.schema_version,
        "conversation_id": record.conversation_id,
        "turn_count": record.turn_count,
        "revision": record.revision,
        "goal": (
            {"action": goal.action.value, "revision": goal.revision} if goal is not None else None
        ),
        "identity": {
            "validated_at": record.identity.validated_at,
            "caller_failures": record.identity.caller_failures,
        },
        "confirmation": (
            {
                "challenge_id": confirmation.challenge_id,
                "action": confirmation.action.value,
                "goal_revision": confirmation.goal_revision,
                "identity_validated_at": confirmation.identity_validated_at,
                "issued_at": confirmation.issued_at,
            }
            if confirmation is not None
            else None
        ),
        "dispatch": (
            {
                "operation_id": dispatch.operation_id,
                "action": dispatch.action.value,
                "goal_revision": dispatch.goal_revision,
                "challenge_id": dispatch.challenge_id,
                "authorized_at": dispatch.authorized_at,
            }
            if dispatch is not None
            else None
        ),
        "external_operation": (
            {
                "operation_id": operation.operation_id,
                "action": operation.action.value,
                "status": operation.status.value,
                "delivery": operation.delivery.value if operation.delivery is not None else None,
                "last_progress_feedback_at": operation.last_progress_feedback_at,
                "progress_feedback_index": operation.progress_feedback_index,
            }
            if operation is not None
            else None
        ),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    procedure = record.experimental_procedure
    suspended = record.experimental_suspended
    window = record.experimental_window
    if procedure is not None or suspended is not None or len(window) > 0:
        # mode="python" keeps datetimes native, like the rest of the document.
        document["experimental_procedure"] = (
            procedure.model_dump(mode="python") if procedure is not None else None
        )
        document["experimental_suspended"] = (
            suspended.model_dump(mode="python") if suspended is not None else None
        )
        document["experimental_window"] = [pair.model_dump(mode="python") for pair in window]
    return document


def session_record_from_document(document: Mapping[str, object]) -> SessionRecord:
    """Validate a stored document; version 1 migrates in memory, fail-closed."""
    version = document.get("schema_version")
    if version == 1:
        return _migrate_v1(document)
    if version == SCHEMA_VERSION:
        return SessionRecord.model_validate(dict(document))
    raise ValueError("unsupported durable schema version")
