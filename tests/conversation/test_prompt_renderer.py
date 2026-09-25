"""Deterministic renderer tests: goal selection, order and no I/O.

The renderer is pure: the same durable goal always yields the same text, the
active protocol is selected only from the semantic state, and nothing is read
after startup. No model, network or credentials are involved.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from app.conversation.prompt_renderer import (
    BASE_INSTRUCTION_KEY,
    PromptBundle,
    StaticPrompt,
)
from app.session.actions import Action
from app.session.record import ConversationGoal
from tests.conversation.prompt_fixtures import (
    SYNTHETIC_RESET_BODY,
    SYNTHETIC_UNLOCK_BODY,
    make_bundle,
    synthetic_protocol_bundle,
)


def goal(action: Action | None) -> ConversationGoal | None:
    if action is None:
        return None
    return ConversationGoal(action=action, revision=1)


def test_goal_null_selects_core_plus_catalog(tmp_path: Path) -> None:
    bundle = synthetic_protocol_bundle(tmp_path)
    base = bundle.system_instructions(None)
    assert bundle.core.text in base
    assert bundle.catalog.text in base
    assert SYNTHETIC_RESET_BODY not in base
    assert SYNTHETIC_UNLOCK_BODY not in base


def test_reset_goal_selects_only_the_reset_protocol(tmp_path: Path) -> None:
    bundle = synthetic_protocol_bundle(tmp_path)
    reset = bundle.system_instructions(goal(Action.RESET_PASSWORD))
    assert SYNTHETIC_RESET_BODY in reset
    assert SYNTHETIC_UNLOCK_BODY not in reset
    assert "## Protocolo activo: RESET_PASSWORD" in reset


def test_unlock_goal_selects_only_the_unlock_protocol(tmp_path: Path) -> None:
    bundle = synthetic_protocol_bundle(tmp_path)
    unlock = bundle.system_instructions(goal(Action.UNLOCK_ACCOUNT))
    assert SYNTHETIC_UNLOCK_BODY in unlock
    assert SYNTHETIC_RESET_BODY not in unlock
    assert "## Protocolo activo: UNLOCK_ACCOUNT" in unlock


def test_goal_switch_follows_the_durable_state_only(tmp_path: Path) -> None:
    """A corrected goal changes the next composition, not the same turn."""
    bundle = synthetic_protocol_bundle(tmp_path)
    unlock_turn = bundle.system_instructions(goal(Action.UNLOCK_ACCOUNT))
    corrected_turn = bundle.system_instructions(goal(Action.RESET_PASSWORD))
    assert SYNTHETIC_UNLOCK_BODY in unlock_turn
    assert SYNTHETIC_UNLOCK_BODY not in corrected_turn
    assert SYNTHETIC_RESET_BODY not in unlock_turn
    assert SYNTHETIC_RESET_BODY in corrected_turn


def test_cancelled_goal_returns_to_core_plus_catalog(tmp_path: Path) -> None:
    bundle = synthetic_protocol_bundle(tmp_path)
    base = bundle.system_instructions(None)
    assert bundle.system_instructions(goal(None)) == base
    assert SYNTHETIC_RESET_BODY not in base


def test_composition_is_deterministic_in_order_and_hashes() -> None:
    first = make_bundle()
    second = make_bundle()
    assert first.fingerprint == second.fingerprint
    orders = first.composition_orders()
    assert orders[BASE_INSTRUCTION_KEY] == ["core.md", "catalog.md", "few_shot.md"]
    assert orders["RESET_PASSWORD"] == [
        "core.md",
        "catalog.md",
        "RESET_PASSWORD.runtime.md",
        "few_shot.md",
    ]
    assert orders["UNLOCK_ACCOUNT"] == [
        "core.md",
        "catalog.md",
        "UNLOCK_ACCOUNT.runtime.md",
        "few_shot.md",
    ]
    assert orders["RESET_PASSWORD@microsoft_portal"] == [
        "core.md",
        "catalog.md",
        "RESET_PASSWORD.runtime.md",
        "step:microsoft_portal",
        "few_shot.md",
    ]
    assert first.instruction_hashes() == second.instruction_hashes()
    assert first.projection_modes == ("step_window",)


def test_few_shot_module_is_optional_and_changes_composition_deterministically() -> None:
    full = make_bundle()
    bare = make_bundle(few_shot_text=None)
    assert full.few_shot is not None
    assert bare.few_shot is None
    assert bare.fingerprint != full.fingerprint
    assert "few_shot.md" not in bare.module_hashes()
    assert bare.composition_orders()[BASE_INSTRUCTION_KEY] == ["core.md", "catalog.md"]
    assert bare.instruction_hashes() != full.instruction_hashes()
    assert "few_shot" not in bare.system_instructions(None)


def test_renderer_never_reads_transcript_or_files(tmp_path: Path) -> None:
    bundle = load_and_delete_sources(tmp_path)
    base = bundle.system_instructions(None)
    reset = bundle.system_instructions(goal(Action.RESET_PASSWORD))
    assert "synthetic transcript" not in base
    assert "synthetic transcript" not in reset
    assert SYNTHETIC_RESET_BODY in reset


def test_prompt_source_selection_only_accepts_durable_state() -> None:
    parameters = list(inspect.signature(PromptBundle.system_instructions).parameters)
    assert parameters == ["self", "goal", "procedure_current"]
    static_parameters = list(inspect.signature(StaticPrompt.system_instructions).parameters)
    assert static_parameters == ["self", "goal", "procedure_current"]


def load_and_delete_sources(tmp_path: Path) -> PromptBundle:
    bundle = synthetic_protocol_bundle(tmp_path)
    for path in sorted(tmp_path.iterdir()):
        path.unlink()
    return bundle
