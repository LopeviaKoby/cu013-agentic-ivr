"""Temporary fail-safe: ONE MUTATING AD ACTION PER CALL.

Until accredited external correlation exists, once UNLOCK_ACCOUNT or
RESET_PASSWORD was dispatched in a call, any later attempt to dispatch a
second UNLOCK/RESET must produce 0 new POST, 0 new mutable operation and a
deterministic TRANSFER. Guidance, read-only work, password repetition and
voice recovery never consume the budget.
"""

from pydantic import SecretStr

from app.session.actions import Action
from app.session.outcome import NextStep
from app.session.record import AssistanceMode, OperationStatus
from app.session.turns import (
    AD_MUTATION_LIMIT_MESSAGE,
    ConfirmationObservation,
    Route,
    advance_turn,
)
from tests.session.doubles import (
    NOW,
    make_challenge,
    make_decision,
    make_dispatch,
    make_goal,
    make_identity,
    make_operation,
    make_state,
)


def _unlocked_state(**overrides: object):  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "goal": None,
        "identity": make_identity(NOW),
        "confirmation": None,
        "dispatch": make_dispatch(
            Action.UNLOCK_ACCOUNT, revision=1, operation_id="op-1", challenge_id="ch-1"
        ),
        "external_operation": make_operation(
            Action.UNLOCK_ACCOUNT, OperationStatus.CONFIRMED, operation_id="op-1"
        ),
    }
    values.update(overrides)
    return make_state(**values)


def _reset_dispatched_state(**overrides: object):  # type: ignore[no-untyped-def]
    from app.session.record import PasswordPresentation, PlaybackVoice

    finished_presentation = PasswordPresentation(
        operation_id="op-1",
        action=Action.RESET_PASSWORD,
        goal_revision=1,
        voice=PlaybackVoice.PLAYBACK_RETURNED,
        caller_finished=True,
        presented_at=NOW,
    )
    values: dict[str, object] = {
        "goal": None,
        "identity": make_identity(NOW),
        "confirmation": None,
        "dispatch": make_dispatch(
            Action.RESET_PASSWORD, revision=1, operation_id="op-1", challenge_id="ch-1"
        ),
        "external_operation": make_operation(
            Action.RESET_PASSWORD, OperationStatus.CONFIRMED, operation_id="op-1"
        ),
        "password_presentation": finished_presentation,
    }
    values.update(overrides)
    return make_state(**values)


def test_unlock_then_reset_request_transfers_without_second_command() -> None:
    delta = advance_turn(
        _unlocked_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                goal={"intent": "REQUEST", "action": "RESET_PASSWORD"},
                assistance_mode=AssistanceMode.AUTONOMOUS,
            ),
        )
    )
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.TRANSFER
    assert delta["outcome"].message == AD_MUTATION_LIMIT_MESSAGE
    assert delta["dispatch"] is not None
    assert delta["dispatch"].operation_id == "op-1"
    assert delta["dispatch"].action is Action.UNLOCK_ACCOUNT
    assert delta["confirmation"] is None


def test_reset_then_unlock_request_transfers_without_second_command() -> None:
    delta = advance_turn(
        _reset_dispatched_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                goal={"intent": "REQUEST", "action": "UNLOCK_ACCOUNT"},
            ),
        )
    )
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.TRANSFER
    assert delta["outcome"].message == AD_MUTATION_LIMIT_MESSAGE
    assert delta["dispatch"] is not None
    assert delta["dispatch"].operation_id == "op-1"
    assert delta["confirmation"] is None


def test_reset_then_reset_request_transfers_without_second_command() -> None:
    delta = advance_turn(
        _reset_dispatched_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                goal={"intent": "REQUEST", "action": "RESET_PASSWORD"},
                assistance_mode=AssistanceMode.AUTONOMOUS,
            ),
        )
    )
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.TRANSFER
    assert delta["outcome"].message == AD_MUTATION_LIMIT_MESSAGE
    assert delta["dispatch"] is not None
    assert delta["dispatch"].operation_id == "op-1"


def test_affirmative_for_second_mutation_never_dispatches() -> None:
    state = _unlocked_state(
        goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
        confirmation=make_challenge(Action.RESET_PASSWORD, revision=1, challenge_id="ch-2"),
        model_decision=make_decision(
            route=Route.CONTINUE,
            confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
        ),
    )
    delta = advance_turn(state)
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.TRANSFER
    assert delta["outcome"].message == AD_MUTATION_LIMIT_MESSAGE
    # No new command: the durable guard still points to the first operation.
    assert delta["dispatch"] is not None
    assert delta["dispatch"].operation_id == "op-1"
    assert delta["dispatch"].action is Action.UNLOCK_ACCOUNT


def test_password_repeat_after_dispatch_is_allowed_without_redispatch() -> None:
    from app.session.record import PasswordPresentation, PlaybackVoice

    presentation = PasswordPresentation(
        operation_id="op-1",
        action=Action.RESET_PASSWORD,
        goal_revision=1,
        voice=PlaybackVoice.PLAYBACK_RETURNED,
        presented_at=NOW,
    )
    state = _reset_dispatched_state(
        goal=None,
        confirmation=None,
        password_presentation=presentation,
        temporary_password=SecretStr("Aa1?Bb2@Cc3#Dd4!"),
        model_decision=make_decision(
            route=Route.CONTINUE,
            message="Repite la contraseña completa por favor",
        ),
    )
    delta = advance_turn(state)
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.DELIVER_PASSWORD
    assert delta["dispatch"] is not None
    assert delta["dispatch"].operation_id == "op-1"
    assert delta["confirmation"] is None


def test_guided_reset_after_unlock_stays_allowed_as_guidance() -> None:
    # GUIDED never dispatches, so it is guidance like future VPN/VDI: it may
    # appear after a prior AD mutation without consuming the budget.
    delta = advance_turn(
        _unlocked_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                goal={"intent": "REQUEST", "action": "RESET_PASSWORD"},
                assistance_mode=AssistanceMode.GUIDED,
            ),
        )
    )
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is not NextStep.TRANSFER
    assert delta["goal"] is not None
    assert delta["goal"].assistance_mode is AssistanceMode.GUIDED


def test_side_question_after_dispatch_stays_allowed() -> None:
    # Normal conversation and future VPN/VDI guidance are GUIDANCE/READ_ONLY:
    # they never consume the AD budget and must not TRANSFER.
    delta = advance_turn(
        _unlocked_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                message="¿Cuál es el horario de mesa?",
            ),
        )
    )
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is not NextStep.TRANSFER
    assert delta["dispatch"] is not None
    assert delta["dispatch"].operation_id == "op-1"


def test_action_effect_classifier_is_explicit_and_closed() -> None:
    from app.session.actions import ActionEffect, action_effect

    assert action_effect(Action.RESET_PASSWORD) is ActionEffect.MUTATES_AD
    assert action_effect(Action.UNLOCK_ACCOUNT) is ActionEffect.MUTATES_AD


def test_transfer_message_never_claims_previous_failure() -> None:
    delta = advance_turn(
        _unlocked_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                goal={"intent": "REQUEST", "action": "RESET_PASSWORD"},
                assistance_mode=AssistanceMode.AUTONOMOUS,
            ),
        )
    )
    assert delta["outcome"] is not None
    message = delta["outcome"].message.lower()
    assert "fall" not in message
    assert "error" not in message
    assert "reintent" not in message
    assert "vuelve" not in message
