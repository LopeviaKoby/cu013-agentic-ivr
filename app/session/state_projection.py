"""Transient, model-facing projection of the durable session state.

Iteration A: the runtime keeps authoritative truth and, every turn, derives a
small immutable view of what is true and what is **permitted** for the model.
The projection is never persisted, never part of ``SessionRecord`` and never
prescribes a conversational next action: it exposes identity status, a pending
confirmation and the execution permissions, so the model can answer side
questions, clarify, explain a step or resume a procedure while the runtime
still owns legality and ``next_step``.

Only closed semantic values travel: raw DTMF, documents, entry dates, email,
passwords, transcripts, RD bodies and caller text never enter this plane.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.session.memory import ExperimentalProcedureState
from app.session.record import (
    Action,
    AuthorizedDispatch,
    ConfirmationChallenge,
    ConversationGoal,
    ExternalOperation,
    IdentityState,
    OperationStatus,
    PasswordPresentation,
    PlaybackVoice,
)

__all__ = [
    "IdentityStatus",
    "ModelStateProjection",
    "identity_status_for",
    "presentation_is_active",
    "project_model_state",
    "projection_from_turn_inputs",
]

ExternalOperationStatus = Literal["none", "pending", "unknown", "confirmed", "failed"]
DeliveryStatusLiteral = Literal["none", "pending", "confirmed", "failed"]
PresentationStatusLiteral = Literal[
    "not_applicable",
    "pending",
    "returned",
    "failed_before_playback",
]


class IdentityStatus(StrEnum):
    """Caller identity authorization status at the turn instant."""

    MISSING = "MISSING"
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    HANDOFF_REQUIRED = "HANDOFF_REQUIRED"


class ModelStateProjection(BaseModel):
    """Immutable facts and permissions derived from the durable state.

    It reads as permissions, never as orders: the model may always answer a
    side question, clarify an ambiguity or explain the current step.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    active_goal: str | None
    goal_revision: int | None
    identity_status: IdentityStatus
    confirmation_pending: bool
    execution_confirmation_allowed: bool
    external_action_allowed: bool
    external_success_claim_allowed: bool
    external_operation_status: ExternalOperationStatus
    external_delivery_status: DeliveryStatusLiteral
    external_presentation_status: PresentationStatusLiteral
    password_presentation_active: bool
    procedure_id: str | None
    procedure_current: str | None


def identity_status_for(identity: IdentityState, now: datetime) -> IdentityStatus:
    """Precedence: exhausted attempts, missing, valid, expired."""
    if identity.requires_handoff():
        return IdentityStatus.HANDOFF_REQUIRED
    if identity.validated_at is None:
        return IdentityStatus.MISSING
    if identity.is_valid_at(now):
        return IdentityStatus.VALID
    return IdentityStatus.EXPIRED


def _operation_is_active(operation: ExternalOperation | None) -> bool:
    return operation is not None and operation.is_active()


def presentation_is_active(
    operation: ExternalOperation | None,
    presentation: PasswordPresentation | None,
) -> bool:
    """True while a confirmed reset still owes the spoken password.

    The first vocalization is eligible before any presentation plane exists
    (the playback event only arrives after the TTS), and the lifecycle stays
    active until the caller explicitly says the dictation is finished.
    """
    if (
        operation is None
        or operation.action is not Action.RESET_PASSWORD
        or operation.status is not OperationStatus.CONFIRMED
    ):
        return False
    return presentation is None or not presentation.caller_finished


def _dispatch_is_live(
    dispatch: AuthorizedDispatch | None,
    operation: ExternalOperation | None,
) -> bool:
    """True while the dispatch still authorizes an execution.

    Once the operation it authorized reached a terminal result the durable
    guard is kept only as correlation metadata (password presentation and late
    results), never as a reusable execution authorization.
    """
    if dispatch is None:
        return False
    return operation is None or operation.is_active()


def _presentation_status(
    operation: ExternalOperation | None,
    presentation: PasswordPresentation | None,
) -> PresentationStatusLiteral:
    """Voice-presentation truth of a confirmed reset, independent of delivery."""
    if (
        operation is None
        or operation.action is not Action.RESET_PASSWORD
        or operation.status is not OperationStatus.CONFIRMED
    ):
        return "not_applicable"
    if presentation is None:
        return "pending"
    if presentation.voice is PlaybackVoice.PLAYBACK_RETURNED:
        return "returned"
    return "failed_before_playback"


def project_model_state(
    *,
    goal: ConversationGoal | None,
    identity: IdentityState,
    confirmation: ConfirmationChallenge | None,
    dispatch: AuthorizedDispatch | None,
    operation: ExternalOperation | None,
    presentation: PasswordPresentation | None,
    procedure: ExperimentalProcedureState | None,
    now: datetime,
) -> ModelStateProjection:
    """Derive the turn's projection from the authoritative runtime state."""
    identity_valid = identity.is_valid_at(now)
    confirmation_allowed = (
        goal is not None
        and identity_valid
        and not identity.requires_handoff()
        and confirmation is None
        and not _dispatch_is_live(dispatch, operation)
        and not _operation_is_active(operation)
    )
    return ModelStateProjection(
        active_goal=goal.action.value if goal is not None else None,
        goal_revision=goal.revision if goal is not None else None,
        identity_status=identity_status_for(identity, now),
        confirmation_pending=confirmation is not None,
        execution_confirmation_allowed=confirmation_allowed,
        external_action_allowed=_dispatch_is_live(dispatch, operation),
        external_success_claim_allowed=(
            operation is not None and operation.status is OperationStatus.CONFIRMED
        ),
        external_operation_status=(operation.status.value if operation is not None else "none"),
        external_delivery_status=(
            operation.delivery.value
            if operation is not None and operation.delivery is not None
            else "none"
        ),
        external_presentation_status=_presentation_status(operation, presentation),
        password_presentation_active=presentation_is_active(operation, presentation),
        procedure_id=procedure.procedure_id if procedure is not None else None,
        procedure_current=procedure.current_step if procedure is not None else None,
    )


def projection_from_turn_inputs(
    *,
    goal: ConversationGoal | None,
    identity_validated: bool,
    confirmation: ConfirmationChallenge | None,
    external_operation: ExternalOperation | None,
    procedure_current: str | None,
) -> ModelStateProjection:
    """Adapter fallback when no runtime-built projection reaches the seam.

    It only mirrors the facts the adapter already received; it never invents
    identity, authorization or results.
    """
    return ModelStateProjection(
        active_goal=goal.action.value if goal is not None else None,
        goal_revision=goal.revision if goal is not None else None,
        identity_status=(IdentityStatus.VALID if identity_validated else IdentityStatus.MISSING),
        confirmation_pending=confirmation is not None,
        execution_confirmation_allowed=(
            goal is not None
            and identity_validated
            and confirmation is None
            and not _operation_is_active(external_operation)
        ),
        external_action_allowed=False,
        external_success_claim_allowed=(
            external_operation is not None
            and external_operation.status is OperationStatus.CONFIRMED
        ),
        external_operation_status=(
            external_operation.status.value if external_operation is not None else "none"
        ),
        external_delivery_status=(
            external_operation.delivery.value
            if external_operation is not None and external_operation.delivery is not None
            else "none"
        ),
        external_presentation_status="not_applicable",
        password_presentation_active=False,
        procedure_id=None,
        procedure_current=procedure_current,
    )
