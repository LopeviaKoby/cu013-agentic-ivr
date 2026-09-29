"""Voice UX hardening: mode preservation, explicit close and truthful waiting."""

from pydantic import SecretStr

from app.session.actions import Action
from app.session.integration import VOICE_RETRY_MESSAGES, VoiceInputFailureReason
from app.session.outcome import NextStep
from app.session.record import (
    AssistanceMode,
    OperationStatus,
    PasswordPresentation,
    PlaybackVoice,
)
from app.session.turns import (
    COMPLETE_FAREWELL_MESSAGE,
    PRESENTATION_WAITING_MESSAGE,
    Route,
    advance_turn,
)
from tests.session.doubles import (
    NOW,
    make_decision,
    make_dispatch,
    make_goal,
    make_identity,
    make_operation,
    make_state,
)


def test_voice_retry_messages_are_distinct_and_deterministic() -> None:
    assert (
        VOICE_RETRY_MESSAGES[VoiceInputFailureReason.NO_SPEECH]
        != VOICE_RETRY_MESSAGES[VoiceInputFailureReason.LOW_CONFIDENCE]
    )
    assert (
        VOICE_RETRY_MESSAGES[VoiceInputFailureReason.LOW_CONFIDENCE]
        != VOICE_RETRY_MESSAGES[VoiceInputFailureReason.TIMEOUT]
    )
    assert (
        VOICE_RETRY_MESSAGES[VoiceInputFailureReason.NO_SPEECH]
        != VOICE_RETRY_MESSAGES[VoiceInputFailureReason.TIMEOUT]
    )


def test_autonomous_mode_survives_voice_failure_invalidation() -> None:
    """RESET AUTONOMOUS + voice failure during confirmation keeps the mode."""
    from app.session.turns import ConfirmationEvent

    state = make_state(
        goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
        identity=make_identity(NOW),
        confirmation=None,
        dispatch=None,
        external_operation=None,
        confirmation_event=ConfirmationEvent.ASR_TIMEOUT,
        model_decision=make_decision(route=Route.CONTINUE),
    )
    # Simulate a prior AUTONOMOUS establishment: the goal already carries it.
    delta = advance_turn(state)
    assert delta["goal"] is not None
    # A voice failure must never degrade AUTONOMOUS to UNDECIDED; when no new
    # mode is proposed the established mode is preserved.
    assert delta["goal"].assistance_mode is AssistanceMode.AUTONOMOUS
    assert delta["confirmation"] is None


def test_explicit_close_after_presentation_is_allowed() -> None:
    presentation = PasswordPresentation(
        operation_id="op-1",
        action=Action.RESET_PASSWORD,
        goal_revision=1,
        voice=PlaybackVoice.PLAYBACK_RETURNED,
        presented_at=NOW,
    )
    state = make_state(
        goal=None,
        identity=make_identity(NOW),
        confirmation=None,
        dispatch=make_dispatch(
            Action.RESET_PASSWORD, revision=1, operation_id="op-1", challenge_id="ch-1"
        ),
        external_operation=make_operation(
            Action.RESET_PASSWORD, OperationStatus.CONFIRMED, operation_id="op-1"
        ),
        password_presentation=presentation,
        temporary_password=SecretStr("Aa1?Bb2@Cc3#Dd4!"),
        model_decision=make_decision(
            route=Route.COMPLETE,
            message="eso sería todo, gracias",
            password_presentation_finished=True,
        ),
    )
    delta = advance_turn(state)
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.COMPLETE
    assert delta["outcome"].message == COMPLETE_FAREWELL_MESSAGE


def test_waiting_message_never_invents_generation_state() -> None:
    state = make_state(
        goal=None,
        identity=make_identity(NOW),
        confirmation=None,
        dispatch=make_dispatch(
            Action.RESET_PASSWORD, revision=1, operation_id="op-1", challenge_id="ch-1"
        ),
        external_operation=make_operation(
            Action.RESET_PASSWORD, OperationStatus.CONFIRMED, operation_id="op-1"
        ),
        password_presentation=None,
        temporary_password=None,
        transcript="hola?",
        model_decision=make_decision(route=Route.CONTINUE),
    )
    # presentation_active with no secret -> deterministic waiting branch.
    # The test forces presentation_active by having CONFIRMED reset without
    # presentation; the waiting message must not claim generation state.
    delta = advance_turn(state)
    assert delta["outcome"] is not None
    message = delta["outcome"].message.lower()
    assert "generada" not in message
    assert "generado" not in message
    assert "casi lista" not in message
    assert "terminando" not in message
    assert delta["outcome"].message == PRESENTATION_WAITING_MESSAGE


def test_confirmed_reset_with_secret_starts_presentation_without_waiting() -> None:
    state = make_state(
        goal=None,
        identity=make_identity(NOW),
        confirmation=None,
        dispatch=make_dispatch(
            Action.RESET_PASSWORD, revision=1, operation_id="op-1", challenge_id="ch-1"
        ),
        external_operation=make_operation(
            Action.RESET_PASSWORD, OperationStatus.CONFIRMED, operation_id="op-1"
        ),
        password_presentation=None,
        temporary_password=SecretStr("Aa1?Bb2@Cc3#Dd4!"),
        transcript=None,
        model_decision=make_decision(
            route=Route.CONTINUE,
            message="Tu contraseña es A a 1 interrogación, etc.",
        ),
    )
    delta = advance_turn(state)
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.DELIVER_PASSWORD
    assert delta["outcome"].message != PRESENTATION_WAITING_MESSAGE
