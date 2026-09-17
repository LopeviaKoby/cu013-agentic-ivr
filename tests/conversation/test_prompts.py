"""Deterministic policy contract tests for the versioned system prompt.

The prompt is a textual contract expressed as code, so these tests lock the
structural properties the runtime depends on: every closed route, decision
field and semantic vocabulary value is documented, the plan/authorization
separation is stated, and no utterance-specific patch list exists. No model,
network or credentials are involved.
"""

from app.conversation.prompts import SYSTEM_INSTRUCTIONS
from app.session.turns import (
    ClaimKind,
    ConfirmationObservation,
    GoalIntent,
    HandoffCause,
    ModelTurnDecision,
    Route,
)


def test_prompt_documents_every_closed_route() -> None:
    for route in Route:
        assert route.value in SYSTEM_INSTRUCTIONS


def test_prompt_documents_every_decision_field() -> None:
    for field in ModelTurnDecision.model_fields:
        assert field in SYSTEM_INSTRUCTIONS


def test_prompt_documents_the_closed_semantic_vocabulary() -> None:
    for vocabulary in (GoalIntent, ConfirmationObservation, HandoffCause, ClaimKind):
        for member in vocabulary:
            assert member.value in SYSTEM_INSTRUCTIONS


def test_prompt_states_the_plan_authorization_separation() -> None:
    assert "El plan es lo que el llamante quiere, no lo que está autorizado" in (
        SYSTEM_INSTRUCTIONS
    )


def test_prompt_states_the_central_conversational_property() -> None:
    assert "atiende la necesidad conversacional inmediata" in SYSTEM_INSTRUCTIONS
    assert "sin perder el objetivo soportado vigente" in SYSTEM_INSTRUCTIONS


def test_prompt_has_no_utterance_specific_patch_lists() -> None:
    for patch_phrase in ("pero antes", "antes dime", "primero,"):
        assert patch_phrase not in SYSTEM_INSTRUCTIONS
