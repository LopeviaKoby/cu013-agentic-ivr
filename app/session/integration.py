"""Technical XCALLY → CU013 integration boundary for account operations.

This module owns the second HTTP contract: after Cally Square captures and
validates identity, or after it executes an authorized order against
Orchestrator/TIVIT/AD, it posts a small PII-safe technical event here. The
runtime reconciles external truth, keeps conversation legality and returns a
tiny directive so TEST can decide TTS, polling or return to the conversation.

Invariants:

- no transcript enters here and no model call ever happens here;
- raw DTMF, document, birth date, password, email and RD payloads are not
  part of the contract and the closed request models reject unknown fields;
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

from pydantic import BaseModel, ConfigDict, Field

from app.session.actions import Action
from app.session.metrics import NullTurnMetrics, TurnMetrics
from app.session.record import (
    MAX_CALLER_IDENTITY_FAILURES,
    ExternalOperation,
    IdentityState,
    OperationStatus,
    SessionRecord,
)
from app.session.repository import SessionRepository
from app.session.turns import ESCALATION_MESSAGE

IDENTITY_VALID_MESSAGE = "Gracias. Tu identidad quedó validada. ¿Deseas continuar con la solicitud?"
IDENTITY_INVALID_MESSAGE = "No pude validar tus datos. Por favor, inténtalo de nuevo."
IDENTITY_TECHNICAL_FAILURE_MESSAGE = (
    "No pude completar la validación en este momento. Por favor, inténtalo de nuevo."
)

UNLOCK_COMPLETED_MESSAGE = "El desbloqueo fue confirmado correctamente."

RESET_CONFIRMED_MESSAGE = (
    "El restablecimiento fue confirmado. La entrega de la contraseña todavía no está confirmada."
)

OPERATION_FAILED_MESSAGE = "No pudimos completar la operación."

# Experimental anti-silence cadence: coherent with the observed LATAM wait of
# about ten seconds between polls. The final value is accepted only after E2E
# evidence; it is not an SLO.
PROGRESS_FEEDBACK_INTERVAL = timedelta(seconds=10)
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
    """Small instruction for Cally Square; never the conversational route enum."""

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


class AccountActionStatusEvent(BaseModel):
    """Sanitized RD status; the RD body never reaches this boundary.

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
    """Technical failure of the external call; never the RD error body."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["ACCOUNT_ACTION_ERROR"]
    operation_id: str = Field(min_length=1)
    action: Action
    goal_revision: int = Field(ge=0)
    phase: ActionErrorPhase
    error_kind: ActionErrorKind
    http_status: int | None = None


IntegrationEvent = Annotated[
    IdentityValidationResultEvent
    | VoiceInputFailureEvent
    | AccountActionStatusEvent
    | AccountActionErrorEvent,
    Field(discriminator="event"),
]


class IntegrationOutcome(BaseModel):
    """Flat directive the technical endpoint returns to Cally Square."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    directive: IntegrationDirective
    message: str | None = None
    operation_state: IntegrationOperationState | None = None


class IntegrationEventRejected(Exception):
    """The event cannot be correlated with the durable session or operation.

    Only a static reason travels; payload values never do.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def resolve_action_status(value: str) -> AccountActionStatus | None:
    """Resolve one external literal; unknown values stay unrecognized."""
    try:
        return AccountActionStatus(value)
    except ValueError:
        return None


class IntegrationEventService:
    """Reconcile technical XCALLY events against the durable session truth.

    The service performs exactly one load and, only when the event actually
    changes durable state, one save. It never calls the model and never
    creates an operation from a result.
    """

    def __init__(
        self,
        repository: SessionRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        metrics: TurnMetrics | None = None,
    ) -> None:
        self._repository = repository
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        self._metrics: TurnMetrics = metrics or NullTurnMetrics()

    async def handle_event(
        self, conversation_id: str, event: IntegrationEvent
    ) -> IntegrationOutcome:
        """Apply one technical event after correlating it with the session."""
        now = self._clock()
        record = await self._repository.load(conversation_id, now=now)
        if record.turn_count == 0:
            raise IntegrationEventRejected("unknown session")
        updated, outcome, changed = self._apply(record, event, now=now)
        if changed:
            await self._repository.save(updated)
        return outcome

    def _apply(
        self, record: SessionRecord, event: IntegrationEvent, *, now: datetime
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        if isinstance(event, IdentityValidationResultEvent):
            return self._apply_identity(record, event, now=now)
        if isinstance(event, VoiceInputFailureEvent):
            return self._apply_voice_failure(record, event, now=now)
        return self._apply_action_event(record, event, now=now)

    def _apply_identity(
        self, record: SessionRecord, event: IdentityValidationResultEvent, *, now: datetime
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        """Apply one identity outcome; a technical failure consumes nothing."""
        identity = record.identity
        if event.outcome is IdentityValidationOutcome.VALID:
            validated = IdentityState(validated_at=now, caller_failures=identity.caller_failures)
            # A new validation invalidates any challenge bound to an older one.
            confirmation = None
            updated = record.model_copy(
                update={"identity": validated, "confirmation": confirmation, "updated_at": now}
            )
            changed = validated != identity or record.confirmation is not None
            return (
                updated,
                IntegrationOutcome(
                    directive=IntegrationDirective.RESUME_CONVERSATION,
                    message=IDENTITY_VALID_MESSAGE,
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
                        message=ESCALATION_MESSAGE,
                        operation_state=project_operation_state(record.external_operation),
                    ),
                    True,
                )
            return (
                updated,
                IntegrationOutcome(
                    directive=IntegrationDirective.COLLECT_IDENTITY,
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
                message=IDENTITY_TECHNICAL_FAILURE_MESSAGE,
                operation_state=project_operation_state(record.external_operation),
            ),
            False,
        )

    def _apply_voice_failure(
        self, record: SessionRecord, event: VoiceInputFailureEvent, *, now: datetime
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        """A failed voice capture never authorizes and never consumes identity."""
        challenged = record.confirmation is not None
        if challenged:
            # SPEC: timeout, silence or insufficient ASR invalidates the
            # confirmation attempt; identity stays valid and the caller is
            # asked again without consuming identity attempts.
            updated = record.model_copy(update={"confirmation": None, "updated_at": now})
            changed = True
        else:
            updated = record
            changed = False
        return (
            updated,
            IntegrationOutcome(
                directive=IntegrationDirective.RETRY_SPEECH,
                message=VOICE_RETRY_MESSAGES[event.reason],
                operation_state=project_operation_state(record.external_operation),
            ),
            changed,
        )

    def _apply_action_event(
        self,
        record: SessionRecord,
        event: AccountActionStatusEvent | AccountActionErrorEvent,
        *,
        now: datetime,
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        """Correlate one action event; mismatches never mutate state."""
        operation = record.external_operation
        dispatch = record.dispatch
        if operation is None:
            raise IntegrationEventRejected("operation")
        if operation.operation_id != event.operation_id:
            raise IntegrationEventRejected("operation_id")
        if operation.action is not event.action:
            raise IntegrationEventRejected("action")
        if dispatch is None or dispatch.operation_id != operation.operation_id:
            raise IntegrationEventRejected("dispatch")
        if dispatch.action is not event.action or dispatch.goal_revision != event.goal_revision:
            raise IntegrationEventRejected("revision")
        if isinstance(event, AccountActionStatusEvent):
            return self._apply_action_status(record, operation, event, now=now)
        return self._apply_action_error(record, operation, event, now=now)

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
                        message=message,
                        operation_state=project_operation_state(updated),
                    ),
                    changed,
                )
            # A late NONE after a terminal result never reopens anything.
            return (
                record,
                self._terminal_outcome(operation, speak=False),
                False,
            )
        if resolved is AccountActionStatus.SUCESSO:
            if operation.status in {OperationStatus.PENDING, OperationStatus.UNKNOWN}:
                updated = operation.model_copy(update={"status": OperationStatus.CONFIRMED})
                updated_record = record.model_copy(
                    update={"external_operation": updated, "updated_at": now}
                )
                return (updated_record, self._terminal_outcome(updated, speak=True), True)
            if operation.status is OperationStatus.CONFIRMED:
                return (record, self._terminal_outcome(operation, speak=True), False)
            raise IntegrationEventRejected("terminal transition")
        # Any known failure status: persist the failure the evidence supports.
        if operation.status in {OperationStatus.PENDING, OperationStatus.UNKNOWN}:
            updated = operation.model_copy(update={"status": OperationStatus.FAILED})
            updated_record = record.model_copy(
                update={"external_operation": updated, "updated_at": now}
            )
            return (updated_record, self._terminal_outcome(updated, speak=True), True)
        if operation.status is OperationStatus.FAILED:
            return (record, self._terminal_outcome(operation, speak=True), False)
        raise IntegrationEventRejected("terminal transition")

    def _apply_action_error(
        self,
        record: SessionRecord,
        operation: ExternalOperation,
        event: AccountActionErrorEvent,
        *,
        now: datetime,
    ) -> tuple[SessionRecord, IntegrationOutcome, bool]:
        if event.phase is ActionErrorPhase.DISPATCH:
            if operation.status is OperationStatus.PENDING:
                # The order may or may not have reached RD: unknown, never a
                # success, never a failure, and never an automatic re-POST.
                updated = operation.model_copy(update={"status": OperationStatus.UNKNOWN})
                return (
                    record.model_copy(update={"external_operation": updated, "updated_at": now}),
                    IntegrationOutcome(
                        directive=IntegrationDirective.POLL_RD,
                        operation_state=project_operation_state(updated),
                    ),
                    True,
                )
            if operation.status is OperationStatus.UNKNOWN:
                return (
                    record,
                    IntegrationOutcome(
                        directive=IntegrationDirective.POLL_RD,
                        operation_state=project_operation_state(operation),
                    ),
                    False,
                )
            raise IntegrationEventRejected("terminal transition")
        # POLL error: the result stays unconfirmed; only polling continues.
        if operation.is_active():
            return (
                record,
                IntegrationOutcome(
                    directive=IntegrationDirective.POLL_RD,
                    operation_state=project_operation_state(operation),
                ),
                False,
            )
        return (record, self._terminal_outcome(operation, speak=False), False)

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

    def _terminal_outcome(self, operation: ExternalOperation, *, speak: bool) -> IntegrationOutcome:
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
            message=self._terminal_message(operation) if speak else None,
            operation_state=state,
        )


__all__ = [
    "ACTION_FAILURE_STATUSES",
    "IDENTITY_INVALID_MESSAGE",
    "IDENTITY_TECHNICAL_FAILURE_MESSAGE",
    "IDENTITY_VALID_MESSAGE",
    "OPERATION_FAILED_MESSAGE",
    "PROGRESS_FEEDBACK_INTERVAL",
    "PROGRESS_MESSAGES",
    "RESET_CONFIRMED_MESSAGE",
    "UNLOCK_COMPLETED_MESSAGE",
    "VOICE_RETRY_MESSAGES",
    "AccountActionErrorEvent",
    "AccountActionStatus",
    "AccountActionStatusEvent",
    "ActionErrorKind",
    "ActionErrorPhase",
    "IdentityValidationOutcome",
    "IdentityValidationResultEvent",
    "IntegrationDirective",
    "IntegrationEvent",
    "IntegrationEventRejected",
    "IntegrationEventService",
    "IntegrationOperationState",
    "IntegrationOutcome",
    "VoiceInputFailureEvent",
    "VoiceInputFailureReason",
    "project_operation_state",
    "resolve_action_status",
]
