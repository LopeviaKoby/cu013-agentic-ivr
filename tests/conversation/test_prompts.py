"""Deterministic policy contract tests for the versioned system prompt.

The prompt is a textual contract expressed as code, so these tests lock the
structural properties the runtime depends on: every closed route, decision
field and semantic vocabulary value is documented, the plan/authorization
separation is stated, and no utterance-specific patch list exists. No model,
network or credentials are involved.
"""

from app.conversation.prompts import SYSTEM_INSTRUCTIONS
from app.session.memory import GUIDED_STEPS, ProcedureObservation, render_memory_block
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
        if field == "procedure_observation":
            # Exp 0009 documents the procedure cue in the experimental memory
            # renderer, not in the baseline system prompt, so the baseline
            # prompt stays byte-identical. The renderer vocabulary is pinned
            # below.
            continue
        assert field in SYSTEM_INSTRUCTIONS


def test_experimental_renderer_documents_the_procedure_vocabulary() -> None:
    block, _ = render_memory_block((), None, None, window_n=3)
    assert "procedure_observation" in block
    # The advertised core vocabulary; PAUSE/RESUME stay valid runtime cues
    # covered by the deterministic transition tests.
    for cue in (
        ProcedureObservation.NONE,
        ProcedureObservation.ADVANCE,
        ProcedureObservation.REGRESS,
    ):
        assert cue.value in block
    for step in GUIDED_STEPS:
        assert step in block


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


def test_active_prompt_is_single_baseline_without_compact_variants() -> None:
    import app.conversation.prompts as prompts_module

    prompt_constants = [
        name for name in dir(prompts_module) if name.endswith("SYSTEM_INSTRUCTIONS")
    ]
    assert prompt_constants == ["SYSTEM_INSTRUCTIONS"]
    assert "Mesa de Ayuda" in SYSTEM_INSTRUCTIONS
