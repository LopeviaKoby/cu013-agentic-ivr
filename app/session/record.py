"""Durable session contract for the Thin Firestore Session Repository.

Version 5 separates the semantic planes ADR-0010 requires without fusing
them: the conversational plan, the identity authorization with its absolute
TTL, the per-operation confirmation challenge and dispatch guard, the truth
of the external operation, the bounded polling plane (sequence receipts and
validated waiting feedback), the password-presentation lifecycle (playback
fact plus the non-sensitive caller-finished flag) and the consecutive
voice-retry counter the pre-turn bootstrap needs. The record stays small,
closed and PII-free: only these fields reach Firestore, and raw DTMF,
transcripts, raw RD bodies, unknown raw statuses, documents, entry dates,
email addresses, temporary passwords, tools, tool schemas, SDK clients and
LangGraph internals never belong here.

Versions 1, 2, 3 and 4 migrate in memory, fail-closed, on the next legitimate
save; nothing here rewrites stored documents in bulk. A document is rejected
when a field it carries cannot be translated honestly into the current
planes instead of being silently dropped. The legacy presentation email
fields stay readable but are never part of a new decision or event.
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
    "DEFAULT_OBSERVATION_LIMIT",
    "MAX_FEEDBACK_MESSAGES",
    "Action",
    "AuthorizedDispatch",
    "ConfirmationChallenge",
    "ConversationGoal",
    "DeliveryStatus",
    "EmailAcceptance",
    "EmailDelivery",
    "ExternalOperation",
    "IdentityState",
    "OperationStatus",
    "PasswordPresentation",
    "PlaybackVoice",
    "PollReceipt",
    "PollingState",
    "SessionRecord",
    "session_record_from_document",
    "session_record_to_document",
]

SCHEMA_VERSION: Literal[5] = 5

IDENTITY_TTL = timedelta(minutes=30)

MAX_CALLER_IDENTITY_FAILURES = 3

# Poll budget: at most nine GET observations per external operation. The
# runtime counts only new, non-replay observations; a replay never consumes
# budget and a dispatch error never consumes GET budget.
DEFAULT_OBSERVATION_LIMIT = 9

# At most two composer-generated waiting messages are ever persisted.
MAX_FEEDBACK_MESSAGES = 2


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


class PollReceipt(BaseModel):
    """One consumed polling observation; the raw external value never lands.

    ``fingerprint`` is the SHA-256 of the closed observation kind (plus the
    technical error fields when the observation was an error), so an unknown
    RD literal can be deduplicated without ever being persisted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(gt=0)
    fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class PollingState(BaseModel):
    """Bounded polling plane for one external operation under next-step-v1.

    It persists only what the sequence/dedupe/budget rules and the waiting
    feedback require: when polling started, the observation limit, one receipt
    per consumed observation, when the composer was last attempted and the
    validated feedback messages already spoken. Transcripts, RD bodies, raw
    unknown statuses, documents, dates, email and passwords never live here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1)
    started_at: AwareDatetime
    observation_limit: int = Field(gt=0)
    receipts: tuple[PollReceipt, ...] = ()
    last_feedback_attempt_at: AwareDatetime | None = None
    feedback_messages: tuple[str, ...] = Field(default=(), max_length=MAX_FEEDBACK_MESSAGES)

    @property
    def observations_used(self) -> int:
        """New observations consumed so far; replays never count."""
        return len(self.receipts)

    def budget_exhausted(self) -> bool:
        """True once the observation limit was reached."""
        return self.observations_used >= self.observation_limit


class PlaybackVoice(StrEnum):
    """How the password playback ended, as reported by XCALLY.

    ``PLAYBACK_RETURNED`` means the playback was returned to the boundary;
    ``PRESENTATION_FAILED_BEFORE_PLAYBACK`` means the presentation did not
    reach playback. Both are facts about the voice presentation only and
    never change the reset result or any email fact.
    """

    PLAYBACK_RETURNED = "PLAYBACK_RETURNED"
    PRESENTATION_FAILED_BEFORE_PLAYBACK = "PRESENTATION_FAILED_BEFORE_PLAYBACK"


class EmailAcceptance(StrEnum):
    """Legacy email-acceptance fact; no longer part of the active semantics."""

    UNKNOWN = "UNKNOWN"


class EmailDelivery(StrEnum):
    """Legacy email-delivery fact; no longer part of the active semantics."""

    UNKNOWN = "UNKNOWN"


class PasswordPresentation(BaseModel):
    """Voice password-presentation lifecycle of a confirmed reset.

    The password itself never enters the backend: this plane records only the
    closed playback fact XCALLY reports plus the non-sensitive
    ``caller_finished`` flag the semantic model decides. It is a separate fact
    from the reset result. The legacy email fields stay optional so records
    written before schema v5 keep loading; no new decision reads them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1)
    action: Action = Action.RESET_PASSWORD
    goal_revision: int = Field(ge=0)
    voice: PlaybackVoice
    caller_finished: bool = False
    email_requested: int | None = Field(default=None, ge=0, le=1)
    email_acceptance: EmailAcceptance | None = None
    email_delivery: EmailDelivery | None = None
    presented_at: AwareDatetime

    @model_validator(mode="after")
    def _presentation_only_applies_to_reset(self) -> Self:
        if self.action is not Action.RESET_PASSWORD:
            raise ValueError("password presentation only applies to RESET_PASSWORD")
        return self


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

    ``polling`` and ``password_presentation`` are the next-step-v1 planes;
    they stay ``None`` until the corresponding v1 events populate them.
    ``voice_retry_count`` is the consecutive voice-failure counter the v1
    pre-turn bootstrap owns; it resets to zero only after a valid persisted
    ``/turns``. The three ``experimental_*`` planes belong to Exp 0009 only:
    they stay ``None``/empty unless an explicit experimental opt-in populated
    them for a synthetic session.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[5] = SCHEMA_VERSION
    conversation_id: str = Field(min_length=1)
    turn_count: int = Field(ge=0)
    revision: int = Field(ge=0)
    goal: ConversationGoal | None
    identity: IdentityState
    confirmation: ConfirmationChallenge | None
    dispatch: AuthorizedDispatch | None
    external_operation: ExternalOperation | None
    polling: PollingState | None = None
    password_presentation: PasswordPresentation | None = None
    voice_retry_count: int = Field(default=0, ge=0)
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


class _LegacySessionRecordV2(BaseModel):
    """Version 2 durable contract, validated with the closed v2 whitelist.

    Every v2 field is translated 1:1 into v3: the operation delivery fact is
    a real v2 fact and v3 keeps it in the same plane, so no stored value is
    dropped or reinterpreted. A v2 document carrying anything the closed v2
    whitelist does not define fails validation instead of being migrated.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = 2
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


class _LegacySessionRecordV3(BaseModel):
    """Version 3 durable contract, validated with the closed v3 whitelist.

    Every v3 field exists in v4 unchanged, so the migration only adds the
    voice-retry counter at zero; the polling and password-presentation planes
    keep their exact stored values.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[3] = 3
    conversation_id: str = Field(min_length=1)
    turn_count: int = Field(ge=0)
    revision: int = Field(ge=0)
    goal: ConversationGoal | None
    identity: IdentityState
    confirmation: ConfirmationChallenge | None
    dispatch: AuthorizedDispatch | None
    external_operation: ExternalOperation | None
    polling: PollingState | None = None
    password_presentation: PasswordPresentation | None = None
    experimental_procedure: ExperimentalProcedureState | None = None
    experimental_suspended: ExperimentalSuspendedProcedure | None = None
    experimental_window: tuple[ExperimentalTurnPair, ...] = ()
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


def _migrate_v2(document: Mapping[str, object]) -> SessionRecord:
    """Migrate a version 2 document fail-closed into the v3 contract.

    The translation is honest by construction: every v2 plane exists in v3
    unchanged, and the two new v3 planes start empty because a v2 document
    never observed a v1 poll sequence or a password presentation. The
    ``external_operation.delivery`` fact keeps its exact meaning and is not
    reinterpreted as a presentation fact. A v2 document with a field the
    closed v2 whitelist does not define is rejected instead of migrated.
    """
    legacy = _LegacySessionRecordV2.model_validate(dict(document))
    return SessionRecord(
        conversation_id=legacy.conversation_id,
        turn_count=legacy.turn_count,
        revision=legacy.revision,
        goal=legacy.goal,
        identity=legacy.identity,
        confirmation=legacy.confirmation,
        dispatch=legacy.dispatch,
        external_operation=legacy.external_operation,
        polling=None,
        password_presentation=None,
        experimental_procedure=legacy.experimental_procedure,
        experimental_suspended=legacy.experimental_suspended,
        experimental_window=legacy.experimental_window,
        created_at=legacy.created_at,
        updated_at=legacy.updated_at,
    )


def _migrate_v3(document: Mapping[str, object]) -> SessionRecord:
    """Migrate a version 3 document fail-closed into the current contract.

    The translation is honest by construction: every v3 plane exists in v5
    unchanged, and the fields added later start at their neutral values because
    a v3 document never observed a voice-retry cycle or a caller-finished
    presentation. A v3 document with a field the closed v3 whitelist does not
    define is rejected instead of migrated.
    """
    legacy = _LegacySessionRecordV3.model_validate(dict(document))
    return SessionRecord(
        conversation_id=legacy.conversation_id,
        turn_count=legacy.turn_count,
        revision=legacy.revision,
        goal=legacy.goal,
        identity=legacy.identity,
        confirmation=legacy.confirmation,
        dispatch=legacy.dispatch,
        external_operation=legacy.external_operation,
        polling=legacy.polling,
        password_presentation=legacy.password_presentation,
        voice_retry_count=0,
        experimental_procedure=legacy.experimental_procedure,
        experimental_suspended=legacy.experimental_suspended,
        experimental_window=legacy.experimental_window,
        created_at=legacy.created_at,
        updated_at=legacy.updated_at,
    )


def _migrate_v4(document: Mapping[str, object]) -> SessionRecord:
    """Migrate a version 4 document fail-closed into the v5 contract.

    Every v4 plane exists in v5 unchanged; the only additions are the neutral
    ``password_presentation.caller_finished`` flag and the optional legacy email
    fields, so a v4 document is validated against the current closed model with
    its schema version promoted. No stored fact is reinterpreted and no
    presentation is invented; extra fields still fail validation.
    """
    promoted = dict(document)
    promoted["schema_version"] = SCHEMA_VERSION
    return SessionRecord.model_validate(promoted)


def session_record_to_document(record: SessionRecord) -> dict[str, object]:
    """Map a record to the exact, closed Firestore document whitelist.

    The v3 keys, including the ``polling`` and ``password_presentation``
    planes, are always present. The experimental Exp 0009 keys are added only
    when active. Stored documents whose operation predates the anti-silence
    metadata still validate: those fields default.
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
        "polling": (
            {
                "operation_id": record.polling.operation_id,
                "started_at": record.polling.started_at,
                "observation_limit": record.polling.observation_limit,
                "receipts": [
                    {"sequence": receipt.sequence, "fingerprint": receipt.fingerprint}
                    for receipt in record.polling.receipts
                ],
                "last_feedback_attempt_at": record.polling.last_feedback_attempt_at,
                "feedback_messages": list(record.polling.feedback_messages),
            }
            if record.polling is not None
            else None
        ),
        "password_presentation": (
            {
                "operation_id": record.password_presentation.operation_id,
                "action": record.password_presentation.action.value,
                "goal_revision": record.password_presentation.goal_revision,
                "voice": record.password_presentation.voice.value,
                "caller_finished": record.password_presentation.caller_finished,
                "email_requested": record.password_presentation.email_requested,
                "email_acceptance": (
                    record.password_presentation.email_acceptance.value
                    if record.password_presentation.email_acceptance is not None
                    else None
                ),
                "email_delivery": (
                    record.password_presentation.email_delivery.value
                    if record.password_presentation.email_delivery is not None
                    else None
                ),
                "presented_at": record.password_presentation.presented_at,
            }
            if record.password_presentation is not None
            else None
        ),
        "voice_retry_count": record.voice_retry_count,
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
    """Validate a stored document; versions 1-4 migrate in memory, fail-closed."""
    version = document.get("schema_version")
    if version == 1:
        return _migrate_v1(document)
    if version == 2:
        return _migrate_v2(document)
    if version == 3:
        return _migrate_v3(document)
    if version == 4:
        return _migrate_v4(document)
    if version == SCHEMA_VERSION:
        return SessionRecord.model_validate(dict(document))
    raise ValueError("unsupported durable schema version")
