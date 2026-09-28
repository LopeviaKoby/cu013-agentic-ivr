"""Deterministic regressions from E2E Ivr02-1790603869.7395.

The caller selected AUTONOMOUS, then an ambiguous/noisy turn proposed
UNDECIDED and the runtime downgraded the mode and cleared the challenge,
so the later affirmation could not dispatch. These tests pin the invariant:
an established GUIDED/AUTONOMOUS reset never degrades to UNDECIDED, and an
ambiguous confirmation invalidates the challenge but a fresh specific
confirmation recovers the dispatch.
"""

from app.session.actions import Action
from app.session.outcome import NextStep
from app.session.record import AssistanceMode, OperationStatus
from app.session.turns import (
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


def _autonomous_state(**overrides: object):  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "goal": make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
        "identity": make_identity(NOW),
        "confirmation": make_challenge(Action.RESET_PASSWORD, challenge_id="reset-challenge"),
        "dispatch": make_dispatch(
            Action.UNLOCK_ACCOUNT,
            revision=1,
            operation_id="operation-1",
            challenge_id="unlock-challenge",
        ),
        "external_operation": make_operation(
            Action.UNLOCK_ACCOUNT, OperationStatus.CONFIRMED, operation_id="operation-1"
        ),
    }
    values.update(overrides)
    return make_state(**values)


def test_explicit_undecided_never_downgrades_an_established_mode() -> None:
    """A noisy turn proposing UNDECIDED must not undo the caller's choice."""
    delta = advance_turn(
        _autonomous_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                message=(
                    "Para confirmar el restablecimiento, indícame si deseas "
                    "que lo ejecute o prefieres guía."
                ),
                assistance_mode=AssistanceMode.UNDECIDED,
            )
        )
    )
    assert delta["goal"] is not None
    assert delta["goal"].assistance_mode is AssistanceMode.AUTONOMOUS
    assert delta["confirmation"] is not None
    # The historical UNLOCK guard stays as correlation metadata; no new
    # dispatch was created and the RESET challenge remains pending.
    assert delta["dispatch"] is not None
    assert delta["dispatch"].challenge_id == "unlock-challenge"


def test_affirmative_with_an_established_autonomous_mode_dispatches_reset() -> None:
    delta = advance_turn(
        _autonomous_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            )
        )
    )
    assert delta["goal"] is not None
    assert delta["goal"].assistance_mode is AssistanceMode.AUTONOMOUS
    assert delta["dispatch"] is not None
    assert delta["dispatch"].action is Action.RESET_PASSWORD
    assert delta["external_operation"] is not None
    assert delta["external_operation"].action is Action.RESET_PASSWORD
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.EXECUTE_ACTION


def test_ambiguous_confirmation_invalidates_then_a_fresh_one_recovers() -> None:
    ambiguous = advance_turn(
        _autonomous_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                confirmation_observation=ConfirmationObservation.AMBIGUOUS,
            )
        )
    )
    assert ambiguous["confirmation"] is None
    # The historical UNLOCK guard stays as correlation metadata; no new
    # dispatch was created.
    assert ambiguous["dispatch"] is not None
    assert ambiguous["dispatch"].challenge_id == "unlock-challenge"
    assert ambiguous["goal"] is not None
    assert ambiguous["goal"].assistance_mode is AssistanceMode.AUTONOMOUS

    reissued = advance_turn(
        _autonomous_state(
            confirmation=None,
            model_decision=make_decision(route=Route.CONTINUE, confirmation_request=True),
        )
    )
    assert reissued["confirmation"] is not None
    assert reissued["dispatch"] is not None
    assert reissued["dispatch"].challenge_id == "unlock-challenge"

    authorized = advance_turn(
        _autonomous_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            )
        )
    )
    assert authorized["dispatch"] is not None
    assert authorized["dispatch"].action is Action.RESET_PASSWORD


def test_explicit_guided_switch_still_changes_the_mode() -> None:
    delta = advance_turn(
        _autonomous_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                assistance_mode=AssistanceMode.GUIDED,
            )
        )
    )
    assert delta["goal"] is not None
    assert delta["goal"].assistance_mode is AssistanceMode.GUIDED
    assert delta["confirmation"] is None
    assert delta["dispatch"] is not None
    assert delta["dispatch"].challenge_id == "unlock-challenge"
