"""Deterministic tests for the transient model-facing state projection.

The projection is derived per turn from the authoritative runtime state, is
never persisted and travels only as closed semantic values. These tests pin
its determinism, its permission facts and the cancellation/re-request
semantics it exposes; no model, network or credentials are involved.
"""

from __future__ import annotations

import json
from datetime import timedelta

from app.conversation.gemini import render_state_projection
from app.session.actions import Action
from app.session.memory import (
    GUIDED_PROCEDURE_ID,
    GUIDED_STEPS,
    RECENT_CONVERSATION_MEMORY,
    ExperimentalMemoryConfig,
    ExperimentalProcedureState,
)
from app.session.record import (
    AuthorizedDispatch,
    ExternalOperation,
    IdentityState,
    OperationStatus,
)
from app.session.state_projection import (
    IdentityStatus,
    project_model_state,
    projection_from_turn_inputs,
)
from app.session.turns import advance_turn
from tests.session.doubles import (
    NOW,
    make_challenge,
    make_decision,
    make_goal,
    make_identity,
    make_state,
)

ALLOWED_KEYS = {
    "active_goal",
    "goal_revision",
    "identity_status",
    "confirmation_pending",
    "execution_confirmation_allowed",
    "external_action_allowed",
    "external_success_claim_allowed",
    "external_operation_status",
    "external_delivery_status",
    "procedure_id",
    "procedure_current",
}


def empty_projection():  # type: ignore[no-untyped-def]
    return project_model_state(
        goal=None,
        identity=IdentityState(),
        confirmation=None,
        dispatch=None,
        operation=None,
        procedure=None,
        now=NOW,
    )


def active_reset_projection(identity: IdentityState):  # type: ignore[no-untyped-def]
    return project_model_state(
        goal=make_goal(Action.RESET_PASSWORD, revision=2),
        identity=identity,
        confirmation=None,
        dispatch=None,
        operation=None,
        procedure=None,
        now=NOW,
    )


def test_projection_is_deterministic_and_closed() -> None:
    first = empty_projection()
    second = empty_projection()
    assert first == second
    assert set(first.model_dump()) == ALLOWED_KEYS
    rendered = render_state_projection(first)
    assert rendered == render_state_projection(second)
    assert rendered.startswith("<conversation_state>\n")
    assert rendered.endswith("\n</conversation_state>")
    payload = json.loads(rendered.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert set(payload) == ALLOWED_KEYS


def test_projection_carries_no_pii_or_transcript() -> None:
    canaries = ("12345678", "1900-01-01", "persona@example.test", "hunter2")
    fields = [
        empty_projection(),
        active_reset_projection(make_identity(NOW)),
    ]
    for projection in fields:
        payload = render_state_projection(projection)
        for canary in canaries:
            assert canary not in payload


def test_identity_status_covers_missing_valid_expired_and_handoff() -> None:
    assert empty_projection().identity_status is IdentityStatus.MISSING
    valid = active_reset_projection(make_identity(NOW))
    assert valid.identity_status is IdentityStatus.VALID
    expired = active_reset_projection(IdentityState(validated_at=NOW - timedelta(minutes=31)))
    assert expired.identity_status is IdentityStatus.EXPIRED
    handoff = active_reset_projection(IdentityState(caller_failures=3))
    assert handoff.identity_status is IdentityStatus.HANDOFF_REQUIRED


def test_execution_confirmation_requires_identity_and_a_clean_window() -> None:
    no_identity = active_reset_projection(IdentityState())
    assert no_identity.execution_confirmation_allowed is False
    allowed = active_reset_projection(make_identity(NOW))
    assert allowed.execution_confirmation_allowed is True
    with_challenge = project_model_state(
        goal=make_goal(Action.RESET_PASSWORD, revision=2),
        identity=make_identity(NOW),
        confirmation=make_challenge(Action.RESET_PASSWORD, revision=2),
        dispatch=None,
        operation=None,
        procedure=None,
        now=NOW,
    )
    assert with_challenge.confirmation_pending is True
    assert with_challenge.execution_confirmation_allowed is False
    with_operation = project_model_state(
        goal=make_goal(Action.RESET_PASSWORD, revision=2),
        identity=make_identity(NOW),
        confirmation=None,
        dispatch=None,
        operation=ExternalOperation(
            operation_id="operation-1",
            action=Action.RESET_PASSWORD,
            status=OperationStatus.PENDING,
        ),
        procedure=None,
        now=NOW,
    )
    assert with_operation.execution_confirmation_allowed is False


def test_external_permissions_follow_dispatch_and_operation_truth() -> None:
    operation = ExternalOperation(
        operation_id="operation-1",
        action=Action.RESET_PASSWORD,
        status=OperationStatus.CONFIRMED,
    )
    projection = project_model_state(
        goal=make_goal(Action.RESET_PASSWORD, revision=1),
        identity=make_identity(NOW),
        confirmation=None,
        dispatch=AuthorizedDispatch(
            operation_id="operation-1",
            action=Action.RESET_PASSWORD,
            goal_revision=1,
            challenge_id="challenge-1",
            authorized_at=NOW,
        ),
        operation=operation,
        procedure=None,
        now=NOW,
    )
    assert projection.external_action_allowed is True
    assert projection.external_success_claim_allowed is True
    assert projection.external_operation_status == "confirmed"


def test_projection_reflects_the_durable_procedure_step() -> None:
    procedure = ExperimentalProcedureState(
        procedure_id=GUIDED_PROCEDURE_ID,
        current_step=GUIDED_STEPS[0],
        goal_revision=1,
        opened_at=NOW,
    )
    projection = project_model_state(
        goal=make_goal(Action.RESET_PASSWORD, revision=1),
        identity=make_identity(),
        confirmation=None,
        dispatch=None,
        operation=None,
        procedure=procedure,
        now=NOW,
    )
    assert projection.procedure_id == GUIDED_PROCEDURE_ID
    assert projection.procedure_current == GUIDED_STEPS[0]


def test_adapter_fallback_never_invents_authorization_or_results() -> None:
    fallback = projection_from_turn_inputs(
        goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1),
        identity_validated=False,
        confirmation=None,
        external_operation=None,
        procedure_current=None,
    )
    assert fallback.active_goal == "UNLOCK_ACCOUNT"
    assert fallback.identity_status is IdentityStatus.MISSING
    assert fallback.execution_confirmation_allowed is False
    assert fallback.external_action_allowed is False
    assert fallback.external_success_claim_allowed is False


def _procedure() -> ExperimentalProcedureState:
    return ExperimentalProcedureState(
        procedure_id=GUIDED_PROCEDURE_ID,
        current_step=GUIDED_STEPS[0],
        goal_revision=1,
        opened_at=NOW,
    )


def test_cancel_clears_instance_state_and_allows_a_fresh_request() -> None:
    """Cancel clears the active instance; a later explicit request is fresh."""
    config = ExperimentalMemoryConfig(variant=RECENT_CONVERSATION_MEMORY, window_n=3)
    before = make_state(
        goal=make_goal(Action.RESET_PASSWORD, revision=1),
        identity=make_identity(NOW),
        confirmation=make_challenge(Action.RESET_PASSWORD, revision=1),
        experimental_config=config,
        experimental_procedure=_procedure(),
        transcript="mejor cancelalo",
        model_decision=make_decision(goal={"intent": "CANCEL", "action": "RESET_PASSWORD"}),
    )
    cancelled = advance_turn(before)
    assert cancelled["goal"] is None
    assert cancelled["confirmation"] is None
    assert cancelled["experimental_procedure"] is None
    assert cancelled["experimental_suspended"] is None
    assert cancelled["dispatch"] is None

    projection_after = project_model_state(
        goal=cancelled["goal"],
        identity=cancelled["identity"],
        confirmation=cancelled["confirmation"],
        dispatch=cancelled["dispatch"],
        operation=cancelled["external_operation"],
        procedure=cancelled["experimental_procedure"],
        now=NOW,
    )
    assert projection_after.active_goal is None
    assert projection_after.confirmation_pending is False
    assert projection_after.execution_confirmation_allowed is False

    fresh = advance_turn(
        make_state(
            goal=None,
            identity=cancelled["identity"],
            model_decision=make_decision(goal={"intent": "REQUEST", "action": "RESET_PASSWORD"}),
        )
    )
    assert fresh["goal"] is not None
    assert fresh["goal"].action is Action.RESET_PASSWORD
    assert fresh["goal"].revision == 1
    # The cancelled instance's challenge is never revived.
    assert fresh["confirmation"] is None


def test_state_change_is_reflected_in_the_next_projection() -> None:
    before = empty_projection()
    after = active_reset_projection(make_identity(NOW))
    assert before != after
    assert before.active_goal is None
    assert after.active_goal == "RESET_PASSWORD"
