"""Minimal semantic-obligation projection for the conversational model.

Derived context, not memory: a small immutable hint computed pre-turn from
runtime-owned state only. It tells the model which caller response the turn
is waiting for; it never authorizes, never mutates, never persists, never
travels the wire, and never reaches tools or side effects.

Vocabulary is closed and transversal: the assistance-mode choice shared by
no other signal, the pending action confirmation, or nothing. Identity
input, presentation feedback, open responses, last-act tracking and textual
history are deliberately absent.
"""

import json
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.session.actions import Action
from app.session.record import (
    AssistanceMode,
    ConfirmationChallenge,
    ConversationGoal,
    ExternalOperation,
    IdentityState,
    PasswordPresentation,
)

__all__ = [
    "ExpectedUserResponse",
    "SemanticObligationProjection",
    "derive_semantic_obligation",
    "render_semantic_obligation",
]


class ExpectedUserResponse(StrEnum):
    """Which caller response the turn is waiting for, if any."""

    ASSISTANCE_MODE_CHOICE = "ASSISTANCE_MODE_CHOICE"
    ACTION_CONFIRMATION = "ACTION_CONFIRMATION"
    NONE = "NONE"


class SemanticObligationProjection(BaseModel):
    """Ephemeral model-facing hint; never durable, never authoritative."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_user_response: ExpectedUserResponse
    expected_action: Action | None = None
    expected_goal_revision: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _payload_matches_response(self) -> "SemanticObligationProjection":
        if self.expected_user_response is ExpectedUserResponse.NONE:
            if self.expected_action is not None or self.expected_goal_revision is not None:
                raise ValueError("NONE carries no action or revision")
        elif self.expected_action is None or self.expected_goal_revision is None:
            raise ValueError("a pending response binds an action and a revision")
        if (
            self.expected_user_response is ExpectedUserResponse.ASSISTANCE_MODE_CHOICE
            and self.expected_action is not Action.RESET_PASSWORD
        ):
            raise ValueError("the assistance-mode choice only applies to RESET_PASSWORD")
        return self


def _challenge_is_consumable(
    challenge: ConfirmationChallenge | None,
    *,
    goal: ConversationGoal | None,
    identity: IdentityState,
    now: datetime,
) -> bool:
    """A challenge the caller could still answer this turn."""
    if challenge is None or goal is None:
        return False
    if challenge.action is not goal.action or challenge.goal_revision != goal.revision:
        return False
    if challenge.identity_validated_at != identity.validated_at:
        return False
    return identity.is_valid_at(now)


def derive_semantic_obligation(
    *,
    goal: ConversationGoal | None,
    identity: IdentityState,
    confirmation: ConfirmationChallenge | None,
    external_operation: ExternalOperation | None,
    password_presentation: PasswordPresentation | None,
    now: datetime,
) -> SemanticObligationProjection:
    """Derive the pending caller response from runtime state only.

    Pure: no transcript, no keywords, no regex, no same-turn decision or
    candidate message. The operation and presentation planes only suppress;
    they never select.
    """
    if (
        goal is not None
        and goal.action is Action.RESET_PASSWORD
        and goal.assistance_mode is AssistanceMode.UNDECIDED
        and not _challenge_is_consumable(confirmation, goal=goal, identity=identity, now=now)
        and (external_operation is None or not external_operation.is_active())
        and password_presentation is None
    ):
        return SemanticObligationProjection(
            expected_user_response=ExpectedUserResponse.ASSISTANCE_MODE_CHOICE,
            expected_action=Action.RESET_PASSWORD,
            expected_goal_revision=goal.revision,
        )
    if _challenge_is_consumable(confirmation, goal=goal, identity=identity, now=now):
        assert confirmation is not None and goal is not None
        return SemanticObligationProjection(
            expected_user_response=ExpectedUserResponse.ACTION_CONFIRMATION,
            expected_action=confirmation.action,
            expected_goal_revision=confirmation.goal_revision,
        )
    return SemanticObligationProjection(expected_user_response=ExpectedUserResponse.NONE)


def render_semantic_obligation(obligation: SemanticObligationProjection) -> str | None:
    """Render the closed block, or None when there is nothing to ask.

    The caller renders the result only when it is not NONE, so an idle turn
    carries zero additional context.
    """
    if obligation.expected_user_response is ExpectedUserResponse.NONE:
        return None
    payload = json.dumps(
        {
            "expected_user_response": obligation.expected_user_response.value,
            "expected_action": (
                obligation.expected_action.value if obligation.expected_action is not None else None
            ),
            "expected_goal_revision": obligation.expected_goal_revision,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"<semantic_obligation>{payload}</semantic_obligation>"
