"""Account actions authorized for the first slice.

Kept in its own module so the experimental memory plane
(`app.session.memory`) and the durable contract (`app.session.record`) can
share it without an import cycle.
"""

from enum import StrEnum


class Action(StrEnum):
    """Account actions authorized for the first slice."""

    RESET_PASSWORD = "RESET_PASSWORD"
    UNLOCK_ACCOUNT = "UNLOCK_ACCOUNT"


class ActionEffect(StrEnum):
    """Temporal fail-safe classification for the one-mutation-per-call rule.

    MUTATES_AD counts against the per-call budget (RESET_PASSWORD,
    UNLOCK_ACCOUNT). READ_ONLY and GUIDANCE never consume it: identity
    lookup, polling, password repetition, voice recovery, side questions and
    future VPN/VDI guidance are conversational or read-only and may appear
    before, between or after an account need.
    """

    MUTATES_AD = "MUTATES_AD"
    READ_ONLY = "READ_ONLY"
    GUIDANCE = "GUIDANCE"


def action_effect(action: Action) -> ActionEffect:
    """Pure closed classifier: only AD mutations consume the call budget."""
    if action in {Action.RESET_PASSWORD, Action.UNLOCK_ACCOUNT}:
        return ActionEffect.MUTATES_AD
    return ActionEffect.GUIDANCE
