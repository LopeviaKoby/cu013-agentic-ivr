"""Deterministic policy contract tests for the composed system prompt.

The prompt is a textual contract expressed as versioned modules, so these
tests lock the structural properties the runtime depends on: every closed
route and decision field is documented, the plan/authorization separation and
the ambiguity rule are stated, the semantic vocabularies are covered by the
composed text or by the required response schema, and no utterance-specific
patch list exists. The private protocol bodies only enter the composition of
their own capability. No model, network or credentials are involved.
"""

from pathlib import Path

from app.conversation.prompt_renderer import BASE_INSTRUCTION_KEY, PromptBundle
from app.session.actions import Action
from app.session.memory import GUIDED_STEPS, ProcedureObservation, render_memory_block
from app.session.record import ConversationGoal
from app.session.turns import (
    ConfirmationObservation,
    GoalIntent,
    ModelTurnDecision,
    Route,
)
from tests.conversation.prompt_fixtures import (
    PROTOCOL_BODIES,
    synthetic_protocol_bundle,
)


def composed_prompt(tmp_path: Path) -> PromptBundle:
    return synthetic_protocol_bundle(tmp_path)


def base_text(tmp_path: Path) -> str:
    return composed_prompt(tmp_path).system_instructions(None)


def test_prompt_documents_every_closed_route(tmp_path: Path) -> None:
    text = base_text(tmp_path)
    for route in Route:
        assert route.value in text


def test_prompt_documents_every_decision_field(tmp_path: Path) -> None:
    text = base_text(tmp_path)
    for field in ModelTurnDecision.model_fields:
        if field == "procedure_observation":
            # Exp 0009 documents the procedure cue in the experimental memory
            # renderer, not in the composed system prompt. The renderer
            # vocabulary is pinned below.
            continue
        assert field in text


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


def test_prompt_semantics_are_stated_without_duplicating_schema_enums(tmp_path: Path) -> None:
    """Closed enum values live in the response schema; policy stays in prose."""
    text = base_text(tmp_path)
    schema = ModelTurnDecision.model_json_schema()
    for field in ("route", "goal", "confirmation_observation", "handoff_cause", "claims"):
        assert field in schema["properties"]
    for intent in (GoalIntent.REQUEST, GoalIntent.CORRECT, GoalIntent.CANCEL):
        assert intent.value in text
    assert "afirmativo" in text
    assert "negativo" in text
    assert "ambigua" in text
    assert "cancelación" in text
    assert "fallo terminal" in text
    assert ConfirmationObservation.CANCEL.value in text
    # Claims policy is stated in prose; values stay schema-enforced.
    assert "restablecida" in text
    assert "entrega" in text


def test_prompt_states_the_plan_authorization_separation(tmp_path: Path) -> None:
    assert "El plan es lo que el llamante quiere, no lo que está autorizado" in (
        base_text(tmp_path)
    )


def test_prompt_states_the_central_conversational_property(tmp_path: Path) -> None:
    text = base_text(tmp_path)
    assert "atiende la necesidad conversacional inmediata" in text
    assert "sin perder el objetivo soportado vigente" in text


def test_prompt_states_the_ambiguity_rule(tmp_path: Path) -> None:
    """Objective property of this experiment: no premature goal."""
    text = base_text(tmp_path)
    assert "más de una acción soportada" in text
    assert "no propongas goal" in text
    assert "CONTINUE" in text


def test_prompt_uses_entry_date_wording_not_birth_date(tmp_path: Path) -> None:
    """The accepted identity question is fecha de ingreso (owner decision)."""
    text = base_text(tmp_path)
    assert "fechas de ingreso" in text
    assert "nacimiento" not in text


def test_prompt_has_no_utterance_specific_patch_lists(tmp_path: Path) -> None:
    text = base_text(tmp_path)
    for patch_phrase in ("pero antes", "antes dime", "primero,"):
        assert patch_phrase not in text


def test_prompt_module_no_longer_holds_a_monolithic_instruction() -> None:
    import app.conversation.prompts as prompts_module

    assert not hasattr(prompts_module, "SYSTEM_INSTRUCTIONS")
    assert "Mesa de Ayuda" in prompts_module.POLLING_FEEDBACK_INSTRUCTIONS


def test_composition_includes_only_the_active_protocol(tmp_path: Path) -> None:
    bundle = composed_prompt(tmp_path)
    base = bundle.system_instructions(None)
    reset = bundle.system_instructions(_goal("RESET_PASSWORD"))
    unlock = bundle.system_instructions(_goal("UNLOCK_ACCOUNT"))
    reset_body = PROTOCOL_BODIES["RESET_PASSWORD.runtime.md"]
    unlock_body = PROTOCOL_BODIES["UNLOCK_ACCOUNT.runtime.md"]
    assert reset_body not in base
    assert unlock_body not in base
    assert reset_body in reset
    assert unlock_body not in reset
    assert unlock_body in unlock
    assert reset_body not in unlock
    assert base == bundle.core.text + "\n\n" + bundle.catalog.text
    assert bundle.instruction(BASE_INSTRUCTION_KEY).order == ("core.md", "catalog.md")


def _goal(action: str) -> ConversationGoal:
    return ConversationGoal(action=Action(action), revision=1)
