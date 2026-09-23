"""Technical XCALLY → CU013 integration boundary for account operations.

This module owns the second HTTP contract: after Cally Square captures and
validates identity, or after it executes an authorized order against
Orchestrator/TIVIT/AD, it posts a small PII-safe technical event here. The
runtime reconciles external truth, keeps conversation legality and returns a
tiny directive so TEST can decide TTS, polling or return to the conversation.

Two closed request vocabularies share one domain transition:

- the legacy vocabulary (no poll sequence, fixed progress rotation) keeps the
  legacy serializer byte-compatible;
- the next-step vocabulary (strict poll sequence, bounded observation budget,
  password presentation, capture exhaustion) feeds the next-step-v1 adapter.

Invariants:

- no transcript enters here and the conversational model is never called;
  the only model call this endpoint may make is one narrow waiting-feedback
  composition, and only when the runtime itself decides feedback is due;
- raw DTMF, document, entry date, password, email and RD payloads are not
  part of either contract and the closed request models reject unknown fields;
- CU013 never calls RD/AD and never persists an RD response body;
- one durable external operation per conversation; terminal states are not
  reopened and an uncertain dispatch is never repeated automatically;
- event messages are runtime-owned, PII-safe and grounded in the state the
  durable record actually holds.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.session.actions import Action
from app.session.feedback import (
    FeedbackObservationKind,
    FeedbackOperationState,
    NullPollingFeedbackComposer,
    PollingFeedbackComposer,
    PollingFeedbackRequest,
    validate_feedback_message,
)
from app.session.metrics import NullTurnMetrics, TurnMetrics
from app.session.outcome import NextStep
from app.session.polling import (
    ObservationKind,
    SequenceDecision,
    append_receipt,
    classify_sequence,
    new_polling_state,
    observation_fingerprint,
)
from app.session.record import (
    MAX_CALLER_IDENTITY_FAILURES,
    MAX_FEEDBACK_MESSAGES,
    AuthorizedDispatch,
    ConfirmationChallenge,
    ConversationGoal,
    EmailAcceptance,
    EmailDelivery,
    ExternalOperation,
    IdentityState,
    OperationStatus,
    PasswordPresentation,
    PlaybackVoice,
    PollingState,
    SessionRecord,
)
from app.session.repository import SessionRepository
from app.session.turns import ESCALATION_MESSAGE, ExternalActionCommand

IDENTITY_VALID_MESSAGE = "Gracias. Tu identidad quedó validada. ¿Deseas continuar con la solicitud?"
IDENTITY_INVALID_MESSAGE = "No pude validar tus datos. Por favor, inténtalo de nuevo."
IDENTITY_TECHNICAL_FAILURE_MESSAGE = (
    "No pude completar la validación en este momento. Por favor, inténtalo de nuevo."
)

UNLOCK_CONFIRMATION_MESSAGE = (
    "Gracias. Tu identidad quedó validada. ¿Confirmas que desbloqueemos tu cuenta?"
)
RESET_CONFIRMATION_MESSAGE = (
    "Gracias. Tu identidad quedó validada. ¿Confirmas que restablezcamos tu contraseña?"
)

UNLOCK_COMPLETED_MESSAGE = "El desbloqueo fue confirmado correctamente."

RESET_CONFIRMED_MESSAGE = (
    "El restablecimiento fue confirmado. La entrega de la contraseña todavía no está confirmada."
)

OPERATION_FAILED_MESSAGE = "No pudimos completar la operación."

# Owner decision (2026-09-23): at most three retries after the initial capture
# attempt. The durable counter counts consecutive capture failures, so the
# fourth failure transfers; a valid persisted /turns resets it to zero.
MAX_VOICE_CAPTURE_FAILURES = 4

VOICE_TRANSFER_MESSAGE = "No pudimos escuchar tu respuesta. Te comunico con una persona."

POLL_EXHAUSTED_MESSAGE = (
    "No pudimos confirmar el resultado de la operación. Te comunico con una persona."
)

# Waiting-feedback cadence: coherent with the observed LATAM wait of about ten
# seconds between polls. It is independent from the observation budget and from
# any deadline, and the final value is accepted only after E2E evidence; it is
# not an SLO.
POLLING_FEEDBACK_INTERVAL = timedelta(seconds=10)

# Legacy anti-silence rotation: kept only for the legacy contract, which
# carries no poll sequence and therefore cannot deduplicate observations.
PROGRESS_FEEDBACK_INTERVAL = POLLING_FEEDBACK_INTERVAL
PROGRESS_MESSAGES: tuple[str, ...] = (
    "Sigo procesando tu solicitud. Gracias por esperar.",
    "La solicitud continúa en proceso. Te avisaré cuando tenga un resultado.",
    "Todavía estoy esperando la confirmación. Gracias por permanecer en la llamada.",
)


class IdentityValidationOutcome(StrEnum):
    """Identity-validation result XCALLY reports after its own capture."""

    VALID = "VALID"
    INVALID = "INVALID"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"


class VoiceInputFailureReason(StrEnum):
    """Why the voice channel produced no usable answer; never a transcript."""

    NO_SPEECH = "NO_SPEECH"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    TIMEOUT = "TIMEOUT"


VOICE_RETRY_MESSAGES: dict[VoiceInputFailureReason, str] = {
    VoiceInputFailureReason.NO_SPEECH: (
        "No alcancé a escuchar tu respuesta. ¿Puedes repetirla, por favor?"
    ),
    VoiceInputFailureReason.LOW_CONFIDENCE: (
        "No te escuché con claridad. ¿Puedes repetirlo, por favor?"
    ),
    VoiceInputFailureReason.TIMEOUT: (
        "No recibí tu respuesta a tiempo. ¿Puedes repetirla, por favor?"
    ),
}


class IdentityInputFailureReason(StrEnum):
    """Why the identity capture phase ended without a validation attempt."""

    CAPTURE_EXHAUSTED = "CAPTURE_EXHAUSTED"


class AccountActionStatus(StrEnum):
    """Literals observed from RD/TIVIT; any other value stays UNRECOGNIZED."""

    NONE = "NONE"
    SUCESSO = "SUCESSO"
    CPF_NAO_ENCONTRADO = "CPF_NAO_ENCONTRADO"
    ERRO_NA_VALIDACAO = "ERRO_NA_VALIDACAO"
    FALHA_AD = "FALHA_AD"
    USUARIO_DESABILITADO = "USUARIO_DESABILITADO"
    USUARIO_EXPIRADO = "USUARIO_EXPIRADO"


ACTION_FAILURE_STATUSES: frozenset[AccountActionStatus] = frozenset(
    {
        AccountActionStatus.CPF_NAO_ENCONTRADO,
        AccountActionStatus.ERRO_NA_VALIDACAO,
        AccountActionStatus.FALHA_AD,
        AccountActionStatus.USUARIO_DESABILITADO,
        AccountActionStatus.USUARIO_EXPIRADO,
    }
)


class ActionErrorPhase(StrEnum):
    """Which external phase failed; the response semantics differ."""

    DISPATCH = "DISPATCH"
    POLL = "POLL"


class ActionErrorKind(StrEnum):
    """Minimal technical error taxonomy for the external call."""

    TIMEOUT = "TIMEOUT"
    HTTP_ERROR = "HTTP_ERROR"
    INVALID_BODY = "INVALID_BODY"
    UNAVAILABLE = "UNAVAILABLE"


class IntegrationDirective(StrEnum):
    """Legacy wire vocabulary kept only for the legacy serializer."""

    NOOP = "NOOP"
    RETRY_SPEECH = "RETRY_SPEECH"
    COLLECT_IDENTITY = "COLLECT_IDENTITY"
    POLL_RD = "POLL_RD"
    RESUME_CONVERSATION = "RESUME_CONVERSATION"
    COMPLETE = "COMPLETE"
    ESCALATE = "ESCALATE"


class IntegrationOperationState(StrEnum):
    """Wire projection of the durable operation status, not a second machine."""

    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


_WIRE_OPERATION_STATES: dict[OperationStatus, IntegrationOperationState] = {
    OperationStatus.PENDING: IntegrationOperationState.PENDING,
    OperationStatus.UNKNOWN: IntegrationOperationState.UNKNOWN,
    OperationStatus.CONFIRMED: IntegrationOperationState.SUCCEEDED,
    OperationStatus.FAILED: IntegrationOperationState.FAILED,
}


def project_operation_state(
    operation: ExternalOperation | None,
) -> IntegrationOperationState | None:
    """Project one canonical status onto the technical wire vocabulary."""
    if operation is None:
        return None
    return _WIRE_OPERATION_STATES[operation.status]


class IdentityValidationResultEvent(BaseModel):
    """PII-safe identity outcome; raw identity values never travel here.

    ``validation_reference`` is optional transport metadata: the runtime
    accepts it for correlation, never persists it and never logs it, so an
    unaccredited reference cannot leak into durable state or telemetry.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["IDENTITY_VALIDATION_RESULT"]
    outcome: IdentityValidationOutcome
    validation_reference: str | None = Field(default=None, max_length=256)


class VoiceInputFailureEvent(BaseModel):
    """ASR/TTS channel failure the current TEST flow never reports today."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["VOICE_INPUT_FAILURE"]
    reason: VoiceInputFailureReason


class IdentityInputFailureEvent(BaseModel):
    """Next-step-v1 only: the identity capture phase ended without an attempt.

    It is not an INVALID result, consumes no caller attempt, keeps the goal and
    never touches the external operation; the runtime transfers.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["IDENTITY_INPUT_FAILURE"]
    reason: Literal["CAPTURE_EXHAUSTED"]


class AccountActionStatusEvent(BaseModel):
    """Legacy sanitized RD status; the RD body never reaches this boundary.

    ``status`` accepts any literal and resolves to the closed external enum
    or to an internal UNRECOGNIZED treatment; a new RD status must not break
    the channel nor invent semantics.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["ACCOUNT_ACTION_STATUS"]
    operation_id: str = Field(min_length=1)
    action: Action
    goal_revision: int = Field(ge=0)
    status: str = Field(min_length=1, max_length=64)


class AccountActionErrorEvent(BaseModel):
    """Legacy technical failure of the external call; never the RD error body."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["ACCOUNT_ACTION_ERROR"]
    operation_id: str = Field(min_length=1)
    action: Action
    goal_revision: int = Field(ge=0)
    phase: ActionErrorPhase
    error_kind: ActionErrorKind
    http_status: int | None = None


class AccountActionStatusV1Event(BaseModel):
    """Next-step-v1 observation with the strict poll sequence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["ACCOUNT_ACTION_STATUS"]
    operation_id: str = Field(min_length=1)
    action: Action
    goal_revision: int = Field(strict=True, ge=0)
    status: str = Field(min_length=1, max_length=64)
    poll_sequence: int = Field(strict=True, gt=0)


class AccountActionErrorV1Event(BaseModel):
    """Next-step-v1 error; a POLL error consumes one GET observation.

    A DISPATCH error carries no sequence and never consumes GET budget.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["ACCOUNT_ACTION_ERROR"]
    operation_id: str = Field(min_length=1)
    action: Action
    goal_revision: int = Field(strict=True, ge=0)
    phase: ActionErrorPhase
    error_kind: ActionErrorKind
    http_status: int | None = None
    poll_sequence: int | None = Field(default=None, strict=True, gt=0)

    @model_validator(mode="after")
    def _sequence_only_for_poll_errors(self) -> AccountActionErrorV1Event:
        if self.phase is ActionErrorPhase.POLL and self.poll_sequence is None:
            raise ValueError("a POLL error requires poll_sequence")
        if self.phase is ActionErrorPhase.DISPATCH and self.poll_sequence is not None:
            raise ValueError("a DISPATCH error must not carry poll_sequence")
        return self


class PasswordPresentationResultEvent(BaseModel):
    """Next-step-v1 password-presentation facts; the password never arrives.

    ``email_requested`` is a strict 0/1 integer. Acceptance and delivery start
    as UNKNOWN: no delivery claim is possible until real evidence exists.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["PASSWORD_PRESENTATION_RESULT"]
    operation_id: str = Field(min_length=1)
    action: Literal[Action.RESET_PASSWORD]
    goal_revision: int = Field(strict=True, ge=0)
    voice: Literal[PlaybackVoice.PLAYBACK_RETURNED]
    email_requested: int = Field(strict=True, ge=0, le=1)
    email_acceptance: Literal[EmailAcceptance.UNKNOWN]
    email_delivery: Literal[EmailDelivery.UNKNOWN]


IntegrationEvent = Annotated[
    IdentityValidationResultEvent
    | VoiceInputFailureEvent
    | AccountActionStatusEvent
    | AccountActionErrorEvent,
    Field(discriminator="event"),
]

NextStepIntegrationEvent = Annotated[
    IdentityValidationResultEvent
    | VoiceInputFailureEvent
    | IdentityInputFailureEvent
    | AccountActionStatusV1Event
    | AccountActionErrorV1Event
    | PasswordPresentationResultEvent,
    Field(discriminator="event"),
]


class IntegrationOutcome(BaseModel):
    """One domain outcome with both wire projections.

    ``directive`` is the legacy projection and ``next_step`` the canonical
    one; the same transition computes both, so no business logic is
    duplicated and neither adapter may invent state.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    directive: IntegrationDirective
    next_step: NextStep
    message: str | None = None
    operation_state: IntegrationOperationState | None = None
    command: ExternalActionCommand | None = None


class RejectionReason(StrEnum):
    """Closed rejection reasons; only these values are ever logged or raised.

    The public HTTP response keeps its own contractual taxonomy; this enum is
    the normalized internal vocabulary telemetry uses, so no payload value,
    operation id or free text can reach a log line through a rejection.
    """

    UNKNOWN_SESSION = "unknown_session"
    PRE_TURN_EVENT_NOT_ALLOWED = "pre_turn_event_not_allowed"
    OPERATION_MISSING = "operation_missing"
    OPERATION_MISMATCH = "operation_mismatch"
    ACTION_MISMATCH = "action_mismatch"
    DISPATCH_MISMATCH = "dispatch_mismatch"
    REVISION_MISMATCH = "revision_mismatch"
    ILLEGAL_TRANSITION = "illegal_transition"
    POLL_SEQUENCE_CONFLICT = "poll_sequence_conflict"
    PASSWORD_PRESENTATION_CONFLICT = "password_presentation_conflict"


class IntegrationEventRejected(Exception):
    """The event cannot be correlated with the durable session or operation.

    Only a closed reason travels; payload values never do.
    """

    def __init__(self, reason: RejectionReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def resolve_action_status(value: str) -> AccountActionStatus | None:
    """Resolve one external literal; unknown values stay unrecognized."""
    try:
        return AccountActionStatus(value)
    except ValueError:
        return None


def _advance_voice_retry(count: int) -> int:
    """Count one more consecutive capture failure, bounded by the policy."""
    return min(count + 1, MAX_VOICE_CAPTURE_FAILURES)


class IntegrationEventService:
    """Reconcile technical XCALLY events against the durable session truth.

    The service performs exactly one load and, only when the event actually
    changes durable state, one save. It never calls the conversational model;
    under next-step-v1 it may make exactly one narrow waiting-feedback
    composition when the runtime decides feedback is due.
    """

    def __init__(
        self,
        repository: SessionRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        metrics: TurnMetrics | None = None,
        composer: PollingFeedbackComposer | None = None,
    ) -> None:
        self._repository = repository
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        self._metrics: TurnMetrics = metrics or NullTurnMetrics()
        self._composer: PollingFeedbackComposer = composer or NullPollingFeedbackComposer()

    async def handle_event(
        self,
        conversation_id: str,
        event: IntegrationEvent | NextStepIntegrationEvent,
        *,
        bootstrap: bool = False,
    ) -> IntegrationOutcome:
        """Apply one technical event after correlating it with the session.

        ``bootstrap`` is the next-step-v1 policy: only a closed v1 voice
        failure may create a missing session. Existence is answered by
        ``load_existing`` so a durable pre-turn record is never confused with
        an absent one, and no other first event ever creates a document.
        """
        now = self._clock()
        existing = await self._repository.load_existing(conversation_id)
        if existing is None:
            if bootstrap and isinstance(event, VoiceInputFailureEvent):
                return await self._bootstrap_voice_failure(conversation_id, event, now=now)
            raise IntegrationEventRejected(RejectionReason.UNKNOWN_SESSION)
        if existing.turn_count == 0:
            if bootstrap and isinstance(event, VoiceInputFailureEvent):
                return await self._apply_pre_turn_voice_failure(existing, event, now=now)
            raise IntegrationEventRejected(RejectionReason.PRE_TURN_EVENT_NOT_ALLOWED)
        updated, outcome, changed = await self._apply(existing, event, now=now)
        if changed:
            await self._repository.save(updated)
        return outcome

    async def _bootstrap_voice_failure(
        self,
        conversation_id: str,
        event: VoiceInputFailureEvent,
        *,
        now: datetime,
    ) -> IntegrationOutcome:
        """Create the minimal pre-turn record for one v1 voice failure.

        The create is conditional: a record that appeared during the race is
        never overwritten, and the event is then applied to the real record.
        """
        record = SessionRecord.new(conversation_id, now=now).model_copy(
            update={"voice_retry_count": _advance_voice_retry(0)}
        )
        created = await self._repository.create_if_absent(record)
        if created:
            return self._voice_failure_outcome(record, event)
        existing = await self._repository.load_existing(conversation_id)
        if existing is None:
            raise IntegrationEventRejected(RejectionReason.UNKNOWN_SESSION)
        if existing.turn_count == 0:
            return await self._apply_pre_turn_voice_failure(existing, event, now=now)
        updated, outcome, changed = await self._apply(existing, event, now=now)
        if changed:
            await self._repository.save(updated)
        return outcome

    async def _apply_pre_turn_voice_failure(
        self,
        record: SessionRecord,
        event: VoiceInputFailureEvent,
        *,
        now: datetime,
    ) -> IntegrationOutcome:
        """Increment the consecutive voice-retry counter before the first turn."""
        updated = record.model_copy(
            update={
                "voice_retry_count": _advance_voice_retry(record.voice_retry_count),
                "updated_at": now,
            }
        )
        await self._repository.save(updated)
        return self._voice_failure_outcome(updated, event)

    async def _apply(
        self,
        record: SessionRecord,
        event: IntegrationEvent | NextStepIntegrationEvent,
        *,
        now: datetime,
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        if isinstance(event, IdentityValidationResultEvent):
            return self._apply_identity(record, event, now=now)
        if isinstance(event, VoiceInputFailureEvent):
            return self._apply_voice_failure(record, event, now=now)
        if isinstance(event, IdentityInputFailureEvent):
            return self._apply_identity_input_failure(record, event)
        if isinstance(event, PasswordPresentationResultEvent):
            return self._apply_password_presentation(record, event, now=now)
        if isinstance(event, AccountActionStatusV1Event):
            return await self._apply_action_status_v1(record, event, now=now)
        if isinstance(event, AccountActionErrorV1Event):
            return await self._apply_action_error_v1(record, event, now=now)
        return self._apply_action_event(record, event, now=now)

    # --- identity ---------------------------------------------------------

    def _apply_identity(
        self, record: SessionRecord, event: IdentityValidationResultEvent, *, now: datetime
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        """Apply one identity outcome; a technical failure consumes nothing."""
        identity = record.identity
        if event.outcome is IdentityValidationOutcome.VALID:
            validated = IdentityState(validated_at=now, caller_failures=identity.caller_failures)
            # A new validation invalidates any challenge bound to an older one
            # and, when a supported goal is pending, opens the next one bound
            # to the action, revision and identity now in force.
            confirmation = self._confirmation_for_valid_identity(record, now=now)
            updated = record.model_copy(
                update={"identity": validated, "confirmation": confirmation, "updated_at": now}
            )
            changed = validated != identity or record.confirmation != confirmation
            return (
                updated,
                IntegrationOutcome(
                    directive=IntegrationDirective.RESUME_CONVERSATION,
                    next_step=NextStep.LISTEN,
                    message=self._identity_valid_message(record, confirmation),
                    operation_state=project_operation_state(record.external_operation),
                ),
                changed,
            )
        if event.outcome is IdentityValidationOutcome.INVALID:
            failures = identity.caller_failures + 1
            updated = record.model_copy(
                update={
                    "identity": IdentityState(
                        validated_at=identity.validated_at, caller_failures=failures
                    ),
                    "updated_at": now,
                }
            )
            if failures >= MAX_CALLER_IDENTITY_FAILURES:
                return (
                    updated,
                    IntegrationOutcome(
                        directive=IntegrationDirective.ESCALATE,
                        next_step=NextStep.TRANSFER,
                        message=ESCALATION_MESSAGE,
                        operation_state=project_operation_state(record.external_operation),
                    ),
                    True,
                )
            return (
                updated,
                IntegrationOutcome(
                    directive=IntegrationDirective.COLLECT_IDENTITY,
                    next_step=NextStep.COLLECT_IDENTITY,
                    message=IDENTITY_INVALID_MESSAGE,
                    operation_state=project_operation_state(record.external_operation),
                ),
                True,
            )
        # TECHNICAL_FAILURE: no attempt is consumed, nothing is authorized and
        # no cause is invented; the identity phase simply stays open.
        return (
            record,
            IntegrationOutcome(
                directive=IntegrationDirective.COLLECT_IDENTITY,
                next_step=NextStep.COLLECT_IDENTITY,
                message=IDENTITY_TECHNICAL_FAILURE_MESSAGE,
                operation_state=project_operation_state(record.external_operation),
            ),
            False,
        )

    def _confirmation_for_valid_identity(
        self, record: SessionRecord, *, now: datetime
    ) -> ConfirmationChallenge | None:
        """Open the specific confirmation challenge a valid identity enables.

        The goal and its revision are conserved; no challenge is invented when
        there is no supported goal, when the caller exhausted the accepted
        identity attempts, or while another external operation is active.
        """
        goal = record.goal
        if goal is None or not self._goal_is_supported(goal):
            return None
        if record.identity.requires_handoff():
            return None
        operation = record.external_operation
        if operation is not None and operation.is_active():
            return None
        return ConfirmationChallenge(
            challenge_id=uuid4().hex,
            action=goal.action,
            goal_revision=goal.revision,
            identity_validated_at=now,
            issued_at=now,
        )

    def _goal_is_supported(self, goal: ConversationGoal) -> bool:
        """Only the accepted first slice may open a challenge."""
        return goal.action in {Action.RESET_PASSWORD, Action.UNLOCK_ACCOUNT}

    def _identity_valid_message(
        self, record: SessionRecord, confirmation: ConfirmationChallenge | None
    ) -> str:
        """Action-specific confirmation request, or the generic continuation."""
        if confirmation is None or record.goal is None:
            return IDENTITY_VALID_MESSAGE
        if record.goal.action is Action.UNLOCK_ACCOUNT:
            return UNLOCK_CONFIRMATION_MESSAGE
        return RESET_CONFIRMATION_MESSAGE

    def _apply_identity_input_failure(
        self, record: SessionRecord, event: IdentityInputFailureEvent
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        """Capture exhaustion is not INVALID: no attempt, no operation touch."""
        return (
            record,
            IntegrationOutcome(
                directive=IntegrationDirective.ESCALATE,
                next_step=NextStep.TRANSFER,
                message=ESCALATION_MESSAGE,
                operation_state=project_operation_state(record.external_operation),
            ),
            False,
        )

    def _apply_voice_failure(
        self, record: SessionRecord, event: VoiceInputFailureEvent, *, now: datetime
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        """A failed voice capture never authorizes and never consumes identity.

        SPEC: timeout, silence or insufficient ASR invalidates the confirmation
        attempt; identity stays valid and the caller is asked again without
        consuming identity attempts. Every received voice failure advances the
        consecutive voice-retry counter, which only a valid persisted turn
        resets.
        """
        updated = record.model_copy(
            update={
                "confirmation": None,
                "voice_retry_count": _advance_voice_retry(record.voice_retry_count),
                "updated_at": now,
            }
        )
        return (updated, self._voice_failure_outcome(updated, event), True)

    def _voice_failure_outcome(
        self, record: SessionRecord, event: VoiceInputFailureEvent
    ) -> IntegrationOutcome:
        """Deterministic retry prompt, or transfer once the attempts are spent.

        It never creates or changes business state, never consumes identity
        attempts and never calls the model.
        """
        if record.voice_retry_count >= MAX_VOICE_CAPTURE_FAILURES:
            return IntegrationOutcome(
                directive=IntegrationDirective.ESCALATE,
                next_step=NextStep.TRANSFER,
                message=VOICE_TRANSFER_MESSAGE,
                operation_state=project_operation_state(record.external_operation),
            )
        return IntegrationOutcome(
            directive=IntegrationDirective.RETRY_SPEECH,
            next_step=NextStep.LISTEN,
            message=VOICE_RETRY_MESSAGES[event.reason],
            operation_state=project_operation_state(record.external_operation),
        )

    # --- legacy action events --------------------------------------------

    def _apply_action_event(
        self,
        record: SessionRecord,
        event: AccountActionStatusEvent | AccountActionErrorEvent,
        *,
        now: datetime,
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        """Correlate one legacy action event; mismatches never mutate state."""
        operation, _ = self._correlate_action(record, event)
        if isinstance(event, AccountActionStatusEvent):
            return self._apply_action_status(record, operation, event, now=now)
        return self._apply_action_error(record, operation, event, now=now)

    def _correlate_action(
        self,
        record: SessionRecord,
        event: AccountActionStatusEvent
        | AccountActionErrorEvent
        | AccountActionStatusV1Event
        | AccountActionErrorV1Event,
    ) -> tuple[ExternalOperation, AuthorizedDispatch]:
        """Deterministic correlation shared by both action vocabularies."""
        operation = record.external_operation
        dispatch = record.dispatch
        if operation is None:
            raise IntegrationEventRejected(RejectionReason.OPERATION_MISSING)
        if operation.operation_id != event.operation_id:
            raise IntegrationEventRejected(RejectionReason.OPERATION_MISMATCH)
        if operation.action is not event.action:
            raise IntegrationEventRejected(RejectionReason.ACTION_MISMATCH)
        if dispatch is None or dispatch.operation_id != operation.operation_id:
            raise IntegrationEventRejected(RejectionReason.DISPATCH_MISMATCH)
        if dispatch.action is not event.action or dispatch.goal_revision != event.goal_revision:
            raise IntegrationEventRejected(RejectionReason.REVISION_MISMATCH)
        return operation, dispatch

    def _apply_action_status(
        self,
        record: SessionRecord,
        operation: ExternalOperation,
        event: AccountActionStatusEvent,
        *,
        now: datetime,
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        resolved = resolve_action_status(event.status)
        if resolved is None:
            # Unknown literal: acknowledge, invent nothing, keep waiting.
            self._metrics.record_counter("unrecognized_action_status", 1)
            return (
                record,
                IntegrationOutcome(
                    directive=IntegrationDirective.POLL_RD,
                    next_step=NextStep.POLL_RD,
                    operation_state=project_operation_state(operation),
                ),
                False,
            )
        if resolved is AccountActionStatus.NONE:
            if operation.is_active():
                updated, message = self._apply_progress(operation, now=now)
                changed = updated != operation
                if changed:
                    record = record.model_copy(
                        update={"external_operation": updated, "updated_at": now}
                    )
                return (
                    record,
                    IntegrationOutcome(
                        directive=IntegrationDirective.POLL_RD,
                        next_step=NextStep.POLL_RD,
                        message=message,
                        operation_state=project_operation_state(updated),
                    ),
                    changed,
                )
            # A late NONE after a terminal result never reopens anything.
            return (
                record,
                self._terminal_outcome(record, operation, speak=False),
                False,
            )
        if resolved is AccountActionStatus.SUCESSO:
            if operation.status in {OperationStatus.PENDING, OperationStatus.UNKNOWN}:
                updated = operation.model_copy(update={"status": OperationStatus.CONFIRMED})
                updated_record = record.model_copy(
                    update={"external_operation": updated, "updated_at": now}
                )
                return (
                    updated_record,
                    self._terminal_outcome(updated_record, updated, speak=True),
                    True,
                )
            if operation.status is OperationStatus.CONFIRMED:
                return (record, self._terminal_outcome(record, operation, speak=True), False)
            raise IntegrationEventRejected(RejectionReason.ILLEGAL_TRANSITION)
        # Any known failure status: persist the failure the evidence supports.
        if operation.status in {OperationStatus.PENDING, OperationStatus.UNKNOWN}:
            updated = operation.model_copy(update={"status": OperationStatus.FAILED})
            updated_record = record.model_copy(
                update={"external_operation": updated, "updated_at": now}
            )
            return (
                updated_record,
                self._terminal_outcome(updated_record, updated, speak=True),
                True,
            )
        if operation.status is OperationStatus.FAILED:
            return (record, self._terminal_outcome(record, operation, speak=True), False)
        raise IntegrationEventRejected(RejectionReason.ILLEGAL_TRANSITION)

    def _apply_dispatch_error(
        self,
        record: SessionRecord,
        operation: ExternalOperation,
        *,
        now: datetime,
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        """An uncertain dispatch never becomes success, failure or a re-POST."""
        if operation.status is OperationStatus.PENDING:
            updated = operation.model_copy(update={"status": OperationStatus.UNKNOWN})
            return (
                record.model_copy(update={"external_operation": updated, "updated_at": now}),
                IntegrationOutcome(
                    directive=IntegrationDirective.POLL_RD,
                    next_step=NextStep.POLL_RD,
                    operation_state=project_operation_state(updated),
                ),
                True,
            )
        if operation.status is OperationStatus.UNKNOWN:
            return (
                record,
                IntegrationOutcome(
                    directive=IntegrationDirective.POLL_RD,
                    next_step=NextStep.POLL_RD,
                    operation_state=project_operation_state(operation),
                ),
                False,
            )
        raise IntegrationEventRejected(RejectionReason.ILLEGAL_TRANSITION)

    def _apply_action_error(
        self,
        record: SessionRecord,
        operation: ExternalOperation,
        event: AccountActionErrorEvent,
        *,
        now: datetime,
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        if event.phase is ActionErrorPhase.DISPATCH:
            return self._apply_dispatch_error(record, operation, now=now)
        # POLL error: the result stays unconfirmed; only polling continues.
        if operation.is_active():
            return (
                record,
                IntegrationOutcome(
                    directive=IntegrationDirective.POLL_RD,
                    next_step=NextStep.POLL_RD,
                    operation_state=project_operation_state(operation),
                ),
                False,
            )
        return (record, self._terminal_outcome(record, operation, speak=False), False)

    # --- next-step-v1 action events --------------------------------------

    async def _apply_action_status_v1(
        self,
        record: SessionRecord,
        event: AccountActionStatusV1Event,
        *,
        now: datetime,
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        """Apply one sequenced observation: truth, budget, feedback, persist."""
        operation, _ = self._correlate_action(record, event)
        resolved = resolve_action_status(event.status)
        if resolved is None:
            self._metrics.record_counter("unrecognized_action_status", 1)
            kind = ObservationKind.UNRECOGNIZED
        elif resolved is AccountActionStatus.NONE:
            kind = ObservationKind.PENDING
        elif resolved is AccountActionStatus.SUCESSO:
            kind = ObservationKind.SUCCEEDED
        else:
            kind = ObservationKind.FAILED
        fingerprint = observation_fingerprint(kind)
        polling = self._polling_for(record, operation, now=now)
        decision = classify_sequence(polling, sequence=event.poll_sequence, fingerprint=fingerprint)
        if decision is SequenceDecision.CONFLICT:
            raise IntegrationEventRejected(RejectionReason.POLL_SEQUENCE_CONFLICT)
        if decision is SequenceDecision.REPLAY:
            # A replay never consumes budget and never re-speaks anything.
            return (record, self._replay_outcome(record, operation), False)
        if not kind.is_terminal() and polling.budget_exhausted():
            # The GET budget is closed: a new non-terminal observation can no
            # longer extend polling. A terminal result is still reconciled.
            raise IntegrationEventRejected(RejectionReason.POLL_SEQUENCE_CONFLICT)
        consumed = append_receipt(polling, sequence=event.poll_sequence, fingerprint=fingerprint)
        record = record.model_copy(update={"polling": consumed, "updated_at": now})
        if kind is ObservationKind.UNRECOGNIZED:
            return await self._non_terminal_observation(
                record,
                operation,
                polling=consumed,
                kind=FeedbackObservationKind.UNRECOGNIZED,
                sequence=event.poll_sequence,
                now=now,
            )
        if kind is ObservationKind.PENDING:
            if operation.is_active():
                return await self._non_terminal_observation(
                    record,
                    operation,
                    polling=consumed,
                    kind=FeedbackObservationKind.PENDING,
                    sequence=event.poll_sequence,
                    now=now,
                )
            # A late NONE after a terminal result never reopens anything.
            return (record, self._terminal_outcome(record, operation, speak=False), True)
        if kind is ObservationKind.SUCCEEDED:
            if operation.status in {OperationStatus.PENDING, OperationStatus.UNKNOWN}:
                updated = operation.model_copy(update={"status": OperationStatus.CONFIRMED})
                updated_record = record.model_copy(
                    update={"external_operation": updated, "updated_at": now}
                )
                return (
                    updated_record,
                    self._terminal_outcome(updated_record, updated, speak=True),
                    True,
                )
            if operation.status is OperationStatus.CONFIRMED:
                # The truth was already delivered: the observation consumes its
                # sequence but never re-speaks the terminal phrase.
                return (record, self._terminal_outcome(record, operation, speak=False), True)
            raise IntegrationEventRejected(RejectionReason.ILLEGAL_TRANSITION)
        # Known failure status.
        if operation.status in {OperationStatus.PENDING, OperationStatus.UNKNOWN}:
            updated = operation.model_copy(update={"status": OperationStatus.FAILED})
            updated_record = record.model_copy(
                update={"external_operation": updated, "updated_at": now}
            )
            return (
                updated_record,
                self._terminal_outcome(updated_record, updated, speak=True),
                True,
            )
        if operation.status is OperationStatus.FAILED:
            return (record, self._terminal_outcome(record, operation, speak=False), True)
        raise IntegrationEventRejected(RejectionReason.ILLEGAL_TRANSITION)

    async def _apply_action_error_v1(
        self,
        record: SessionRecord,
        event: AccountActionErrorV1Event,
        *,
        now: datetime,
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        """A POLL error is an observation; a DISPATCH error never consumes GET."""
        operation, _ = self._correlate_action(record, event)
        if event.phase is ActionErrorPhase.DISPATCH:
            return self._apply_dispatch_error(record, operation, now=now)
        sequence = event.poll_sequence
        if sequence is None:  # defensive: the closed schema already requires it
            raise IntegrationEventRejected(RejectionReason.POLL_SEQUENCE_CONFLICT)
        kind = ObservationKind.ERROR
        fingerprint = observation_fingerprint(
            kind,
            phase=event.phase.value,
            error_kind=event.error_kind.value,
            http_status=event.http_status,
        )
        polling = self._polling_for(record, operation, now=now)
        decision = classify_sequence(polling, sequence=sequence, fingerprint=fingerprint)
        if decision is SequenceDecision.CONFLICT:
            raise IntegrationEventRejected(RejectionReason.POLL_SEQUENCE_CONFLICT)
        if decision is SequenceDecision.REPLAY:
            return (record, self._replay_outcome(record, operation), False)
        if polling.budget_exhausted():
            raise IntegrationEventRejected(RejectionReason.POLL_SEQUENCE_CONFLICT)
        consumed = append_receipt(polling, sequence=sequence, fingerprint=fingerprint)
        record = record.model_copy(update={"polling": consumed, "updated_at": now})
        if not operation.is_active():
            return (record, self._terminal_outcome(record, operation, speak=False), True)
        return await self._non_terminal_observation(
            record,
            operation,
            polling=consumed,
            kind=FeedbackObservationKind.ERROR,
            sequence=sequence,
            now=now,
        )

    def _polling_for(
        self, record: SessionRecord, operation: ExternalOperation, *, now: datetime
    ) -> PollingState:
        """Return the polling plane for this operation, opening it when absent."""
        polling = record.polling
        if polling is None or polling.operation_id != operation.operation_id:
            return new_polling_state(operation.operation_id, now=now)
        return polling

    async def _non_terminal_observation(
        self,
        record: SessionRecord,
        operation: ExternalOperation,
        *,
        polling: PollingState,
        kind: FeedbackObservationKind,
        sequence: int,
        now: datetime,
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        """Budget first, then at most one waiting-feedback composition."""
        if polling.budget_exhausted():
            # The ninth non-terminal observation transfers without turning
            # PENDING/UNKNOWN into FAILED: the result stays unconfirmed.
            return (
                record,
                IntegrationOutcome(
                    directive=IntegrationDirective.ESCALATE,
                    next_step=NextStep.TRANSFER,
                    message=POLL_EXHAUSTED_MESSAGE,
                    operation_state=project_operation_state(operation),
                ),
                True,
            )
        record, message = await self._maybe_feedback(
            record,
            operation,
            polling=polling,
            kind=kind,
            sequence=sequence,
            now=now,
        )
        return (
            record,
            IntegrationOutcome(
                directive=IntegrationDirective.POLL_RD,
                next_step=NextStep.POLL_RD,
                message=message,
                operation_state=project_operation_state(operation),
            ),
            True,
        )

    async def _maybe_feedback(
        self,
        record: SessionRecord,
        operation: ExternalOperation,
        *,
        polling: PollingState,
        kind: FeedbackObservationKind,
        sequence: int,
        now: datetime,
    ) -> tuple[SessionRecord, str | None]:
        """Compose one waiting message only when the cadence says it is due.

        The first observation only starts the cadence, so the runtime never
        speaks twice at once. A composer timeout, invalid output or
        inadmissible text yields ``message=null``: business state stays
        intact, safe poll metadata is preserved, no rotation phrase is spoken
        and no second model call happens.
        """
        if not operation.is_active():
            return record, None
        if len(polling.feedback_messages) >= MAX_FEEDBACK_MESSAGES:
            return record, None
        last = polling.last_feedback_attempt_at
        if last is None:
            started = polling.model_copy(update={"last_feedback_attempt_at": now})
            return record.model_copy(update={"polling": started, "updated_at": now}), None
        if now - last < POLLING_FEEDBACK_INTERVAL:
            return record, None
        dispatch = record.dispatch
        request = PollingFeedbackRequest(
            action=operation.action,
            goal_revision=dispatch.goal_revision if dispatch is not None else 0,
            confirmation_obtained=dispatch is not None,
            operation_state=(
                FeedbackOperationState.UNKNOWN
                if operation.status is OperationStatus.UNKNOWN
                else FeedbackOperationState.PENDING
            ),
            observation_kind=kind,
            poll_sequence=sequence,
            observations_used=polling.observations_used,
            observation_limit=polling.observation_limit,
            previous_messages=polling.feedback_messages,
        )
        candidate: str | None = None
        try:
            candidate = await self._composer.compose(request)
        except Exception:
            self._metrics.record_counter("polling_feedback_composer_failure", 1)
            candidate = None
        validated = validate_feedback_message(candidate)
        messages = polling.feedback_messages + ((validated,) if validated is not None else ())
        updated_polling = polling.model_copy(
            update={"last_feedback_attempt_at": now, "feedback_messages": messages}
        )
        return record.model_copy(update={"polling": updated_polling, "updated_at": now}), validated

    # --- password presentation -------------------------------------------

    def _apply_password_presentation(
        self,
        record: SessionRecord,
        event: PasswordPresentationResultEvent,
        *,
        now: datetime,
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        """Persist the presentation facts of a confirmed reset; never re-present."""
        operation = record.external_operation
        dispatch = record.dispatch
        if operation is None:
            raise IntegrationEventRejected(RejectionReason.OPERATION_MISSING)
        if operation.operation_id != event.operation_id:
            raise IntegrationEventRejected(RejectionReason.OPERATION_MISMATCH)
        if operation.action is not Action.RESET_PASSWORD:
            raise IntegrationEventRejected(RejectionReason.ACTION_MISMATCH)
        if dispatch is None or dispatch.operation_id != operation.operation_id:
            raise IntegrationEventRejected(RejectionReason.DISPATCH_MISMATCH)
        if (
            dispatch.action is not Action.RESET_PASSWORD
            or dispatch.goal_revision != event.goal_revision
        ):
            raise IntegrationEventRejected(RejectionReason.REVISION_MISMATCH)
        if operation.status is not OperationStatus.CONFIRMED:
            raise IntegrationEventRejected(RejectionReason.ILLEGAL_TRANSITION)
        candidate = PasswordPresentation(
            operation_id=event.operation_id,
            action=event.action,
            goal_revision=event.goal_revision,
            voice=event.voice,
            email_requested=event.email_requested,
            email_acceptance=event.email_acceptance,
            email_delivery=event.email_delivery,
            presented_at=now,
        )
        existing = record.password_presentation
        if existing is not None:
            identical = (
                existing.voice == candidate.voice
                and existing.email_requested == candidate.email_requested
                and existing.email_acceptance == candidate.email_acceptance
                and existing.email_delivery == candidate.email_delivery
            )
            if identical:
                return (record, self._presentation_outcome(record, operation), False)
            raise IntegrationEventRejected(RejectionReason.PASSWORD_PRESENTATION_CONFLICT)
        updated = record.model_copy(update={"password_presentation": candidate, "updated_at": now})
        return (updated, self._presentation_outcome(updated, operation), True)

    def _presentation_outcome(
        self, record: SessionRecord, operation: ExternalOperation
    ) -> IntegrationOutcome:
        """After presentation, listen: delivery stays UNKNOWN and unclaimed."""
        return IntegrationOutcome(
            directive=IntegrationDirective.RESUME_CONVERSATION,
            next_step=NextStep.LISTEN,
            operation_state=project_operation_state(operation),
        )

    # --- projections ------------------------------------------------------

    def _replay_outcome(
        self, record: SessionRecord, operation: ExternalOperation
    ) -> IntegrationOutcome:
        """Idempotent projection of a replayed observation; never re-speaks."""
        if operation.is_active():
            polling = record.polling
            if polling is not None and polling.budget_exhausted():
                return IntegrationOutcome(
                    directive=IntegrationDirective.ESCALATE,
                    next_step=NextStep.TRANSFER,
                    operation_state=project_operation_state(operation),
                )
            return IntegrationOutcome(
                directive=IntegrationDirective.POLL_RD,
                next_step=NextStep.POLL_RD,
                operation_state=project_operation_state(operation),
            )
        return self._terminal_outcome(record, operation, speak=False)

    def _apply_progress(
        self, operation: ExternalOperation, *, now: datetime
    ) -> tuple[ExternalOperation, str | None]:
        """Emit one deterministic progress phrase only after the interval."""
        last = operation.last_progress_feedback_at
        if last is None:
            # No known initial-message instant: start the interval now instead
            # of speaking twice at once.
            return operation.model_copy(update={"last_progress_feedback_at": now}), None
        if now - last < PROGRESS_FEEDBACK_INTERVAL:
            return operation, None
        index = operation.progress_feedback_index
        message = PROGRESS_MESSAGES[index % len(PROGRESS_MESSAGES)]
        return (
            operation.model_copy(
                update={
                    "last_progress_feedback_at": now,
                    "progress_feedback_index": index + 1,
                }
            ),
            message,
        )

    def _terminal_message(self, operation: ExternalOperation) -> str:
        """Grounded terminal phrase; never invents delivery or internals."""
        if operation.status is OperationStatus.CONFIRMED:
            if operation.action is Action.UNLOCK_ACCOUNT:
                return UNLOCK_COMPLETED_MESSAGE
            # RESET: the reset result is confirmed, the delivery fact is not.
            return RESET_CONFIRMED_MESSAGE
        return OPERATION_FAILED_MESSAGE

    def _terminal_next_step(self, record: SessionRecord, operation: ExternalOperation) -> NextStep:
        """Terminal projection: unlock completes, a reset needs presentation."""
        if operation.status is OperationStatus.CONFIRMED:
            if operation.action is Action.UNLOCK_ACCOUNT:
                return NextStep.COMPLETE
            if record.password_presentation is None:
                return NextStep.DELIVER_PASSWORD
            return NextStep.LISTEN
        return NextStep.LISTEN

    def _terminal_outcome(
        self, record: SessionRecord, operation: ExternalOperation, *, speak: bool
    ) -> IntegrationOutcome:
        """Terminal directive; ``speak`` is False for already-delivered results."""
        state = project_operation_state(operation)
        if operation.status is OperationStatus.CONFIRMED:
            if operation.action is Action.UNLOCK_ACCOUNT:
                directive = IntegrationDirective.COMPLETE
            else:
                directive = IntegrationDirective.RESUME_CONVERSATION
        else:
            directive = IntegrationDirective.RESUME_CONVERSATION
        return IntegrationOutcome(
            directive=directive,
            next_step=self._terminal_next_step(record, operation),
            message=self._terminal_message(operation) if speak else None,
            operation_state=state,
        )


__all__ = [
    "ACTION_FAILURE_STATUSES",
    "IDENTITY_INVALID_MESSAGE",
    "IDENTITY_TECHNICAL_FAILURE_MESSAGE",
    "IDENTITY_VALID_MESSAGE",
    "MAX_VOICE_CAPTURE_FAILURES",
    "OPERATION_FAILED_MESSAGE",
    "POLLING_FEEDBACK_INTERVAL",
    "POLL_EXHAUSTED_MESSAGE",
    "PROGRESS_FEEDBACK_INTERVAL",
    "PROGRESS_MESSAGES",
    "RESET_CONFIRMATION_MESSAGE",
    "RESET_CONFIRMED_MESSAGE",
    "UNLOCK_COMPLETED_MESSAGE",
    "UNLOCK_CONFIRMATION_MESSAGE",
    "VOICE_RETRY_MESSAGES",
    "VOICE_TRANSFER_MESSAGE",
    "AccountActionErrorEvent",
    "AccountActionErrorV1Event",
    "AccountActionStatus",
    "AccountActionStatusEvent",
    "AccountActionStatusV1Event",
    "ActionErrorKind",
    "ActionErrorPhase",
    "IdentityInputFailureEvent",
    "IdentityInputFailureReason",
    "IdentityValidationOutcome",
    "IdentityValidationResultEvent",
    "IntegrationDirective",
    "IntegrationEvent",
    "IntegrationEventRejected",
    "IntegrationEventService",
    "IntegrationOperationState",
    "IntegrationOutcome",
    "NextStepIntegrationEvent",
    "PasswordPresentationResultEvent",
    "RejectionReason",
    "VoiceInputFailureEvent",
    "VoiceInputFailureReason",
    "project_operation_state",
    "resolve_action_status",
]
