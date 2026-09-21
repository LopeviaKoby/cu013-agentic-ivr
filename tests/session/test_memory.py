"""Exp 0009 deterministic memory/procedure tests; synthetic only, no model network.

Covers the experimental memory plane: guided-procedure lifecycle, the
three-pair window (trim, omission, byte guards), service opt-in
attribution, restart continuity and identity-expiry behavior. Every
utterance is synthetic and non-sensitive; prohibited values never appear
here (they are covered by tests/session/test_memory_privacy.py and
tests/api/).
"""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.session.actions import Action
from app.session.memory import (
    CONCISE_PROMPT_POLICY,
    CONTRASTIVE_EXAMPLES_PROMPT_POLICY,
    DEFAULT_PROMPT_POLICY,
    GUIDED_PROCEDURE_ID,
    GUIDED_STEP_DESCRIPTIONS,
    GUIDED_STEPS,
    MEMORY_PAIR_BYTES,
    MEMORY_WINDOW_BYTES,
    PRECEDENCE_PROMPT_POLICY,
    SESSION_BYTES_GUARD,
    ExperimentalMemoryConfig,
    ExperimentalProcedureState,
    ExperimentalTurnPair,
    ProcedureObservation,
    append_pair,
    apply_goal_lifecycle,
    apply_procedure_observation,
    make_pair,
    open_procedure,
    procedure_schema_identity,
    render_memory_block,
    session_document_bytes,
    window_bytes,
)
from app.session.record import SessionRecord, session_record_to_document
from app.session.repository import SessionRepository
from app.session.service import TurnService
from app.session.turns import (
    IdentityOutcome,
    Route,
    TurnInput,
    build_turn_graph,
    initial_graph_state,
)
from tests.session.doubles import (
    NOW,
    FrozenClock,
    InMemorySessionDocumentStore,
    make_decision,
    make_record,
)

PROCEDURE_ONLY = ExperimentalMemoryConfig(variant="procedure_progress_only")
RECENT_MEMORY = ExperimentalMemoryConfig(variant="recent_conversation_memory")
RECENT_MEMORY_N5 = ExperimentalMemoryConfig(variant="recent_conversation_memory", window_n=5)


def open_reset(*, revision: int = 1) -> ExperimentalProcedureState:
    procedure = open_procedure(Action.RESET_PASSWORD, goal_revision=revision, now=NOW)
    assert procedure is not None
    return procedure


# --- procedure lifecycle ----------------------------------------------------


def test_procedure_opens_only_for_reset() -> None:
    assert open_procedure(Action.RESET_PASSWORD, goal_revision=1, now=NOW) is not None
    assert open_procedure(Action.UNLOCK_ACCOUNT, goal_revision=1, now=NOW) is None
    assert open_procedure(None, goal_revision=0, now=NOW) is None


def test_opened_procedure_starts_at_first_guided_step() -> None:
    procedure = open_reset()
    assert procedure.procedure_id == GUIDED_PROCEDURE_ID
    assert procedure.current_step == GUIDED_STEPS[0]
    assert procedure.last_completed_step is None
    assert procedure.awaiting_caller is False


def test_advance_moves_through_the_accepted_slice_in_order() -> None:
    procedure = open_reset()
    procedure = apply_procedure_observation(procedure, ProcedureObservation.ADVANCE)
    assert procedure is not None
    assert (procedure.current_step, procedure.last_completed_step) == (
        GUIDED_STEPS[1],
        GUIDED_STEPS[0],
    )
    procedure = apply_procedure_observation(procedure, ProcedureObservation.ADVANCE)
    assert procedure is not None
    assert (procedure.current_step, procedure.last_completed_step) == (
        GUIDED_STEPS[2],
        GUIDED_STEPS[1],
    )
    procedure = apply_procedure_observation(procedure, ProcedureObservation.ADVANCE)
    assert procedure is not None
    assert procedure.current_step is None
    assert procedure.last_completed_step == GUIDED_STEPS[-1]


def test_advance_past_completion_is_a_noop() -> None:
    procedure = open_reset()
    for _ in GUIDED_STEPS:
        procedure = apply_procedure_observation(procedure, ProcedureObservation.ADVANCE)
    assert procedure is not None
    finished = procedure
    assert apply_procedure_observation(finished, ProcedureObservation.ADVANCE) == finished


def test_regress_returns_to_a_legal_point_and_supersedes() -> None:
    procedure = open_reset()
    procedure = apply_procedure_observation(procedure, ProcedureObservation.ADVANCE)
    assert procedure is not None
    procedure = apply_procedure_observation(procedure, ProcedureObservation.REGRESS)
    assert procedure is not None
    assert procedure.current_step == GUIDED_STEPS[0]
    assert procedure.last_completed_step is None


def test_regress_at_first_step_is_a_noop() -> None:
    procedure = open_reset()
    assert apply_procedure_observation(procedure, ProcedureObservation.REGRESS) == procedure


def test_pause_and_resume_only_flip_the_marker() -> None:
    procedure = open_reset()
    paused = apply_procedure_observation(procedure, ProcedureObservation.PAUSE)
    assert paused is not None and paused.awaiting_caller is True
    assert paused.current_step == procedure.current_step
    resumed = apply_procedure_observation(paused, ProcedureObservation.RESUME)
    assert resumed is not None and resumed.awaiting_caller is False


def test_unknown_procedure_or_step_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ExperimentalProcedureState(
            procedure_id="INVENTED_PROCEDURE",
            current_step=GUIDED_STEPS[0],
            last_completed_step=None,
            goal_revision=1,
            opened_at=NOW,
        )
    with pytest.raises(ValidationError):
        ExperimentalProcedureState(
            procedure_id=GUIDED_PROCEDURE_ID,
            current_step="invented_step",
            last_completed_step=None,
            goal_revision=1,
            opened_at=NOW,
        )


def test_cancel_clears_active_and_suspended() -> None:
    procedure = open_reset()
    cleared, suspended = apply_goal_lifecycle(
        procedure,
        None,
        previous_action=Action.RESET_PASSWORD,
        current_action=None,
        current_revision=0,
        now=NOW,
    )
    assert cleared is None
    assert suspended is None


def test_temporary_switch_suspends_and_explicit_return_resumes() -> None:
    procedure = open_reset()
    procedure = apply_procedure_observation(procedure, ProcedureObservation.ADVANCE)
    assert procedure is not None
    # RESET -> UNLOCK: the guided procedure parks in the single bounded slot.
    parked, suspended = apply_goal_lifecycle(
        procedure,
        None,
        previous_action=Action.RESET_PASSWORD,
        current_action=Action.UNLOCK_ACCOUNT,
        current_revision=2,
        now=NOW,
    )
    assert parked is None
    assert suspended is not None
    assert suspended.current_step == GUIDED_STEPS[1]
    # UNLOCK -> RESET: explicit return restores the steps rebound to the new
    # revision; no confirmation is restored here (challenge logic owns that).
    restored, suspended = apply_goal_lifecycle(
        parked,
        suspended,
        previous_action=Action.UNLOCK_ACCOUNT,
        current_action=Action.RESET_PASSWORD,
        current_revision=3,
        now=NOW,
    )
    assert suspended is None
    assert restored is not None
    assert restored.current_step == GUIDED_STEPS[1]
    assert restored.last_completed_step == GUIDED_STEPS[0]
    assert restored.goal_revision == 3


def test_same_action_correction_rebinds_without_restarting() -> None:
    procedure = open_reset()
    kept, _ = apply_goal_lifecycle(
        procedure,
        None,
        previous_action=Action.RESET_PASSWORD,
        current_action=Action.RESET_PASSWORD,
        current_revision=2,
        now=NOW,
    )
    assert kept is not None
    assert kept.current_step == GUIDED_STEPS[0]
    assert kept.goal_revision == 2


# --- window -----------------------------------------------------------------


def test_pair_enforces_the_per_pair_byte_cap() -> None:
    pair = make_pair("hola", "buenas", sequence=1, goal_revision=1)
    assert pair.byte_size() <= MEMORY_PAIR_BYTES
    assert pair.omitted is False
    with pytest.raises(ValidationError):
        ExperimentalTurnPair(
            caller_text="x" * MEMORY_PAIR_BYTES,
            assistant_text="y",
            sequence=1,
        )


def test_oversize_input_becomes_an_explicit_omission_marker() -> None:
    oversize = "palabra " * 500
    pair = make_pair(oversize, "respuesta breve", sequence=7, goal_revision=2)
    assert pair.omitted is True
    assert pair.byte_size() <= MEMORY_PAIR_BYTES
    assert oversize not in (pair.caller_text + pair.assistant_text)


def test_window_trims_oldest_whole_pairs_in_one_pass() -> None:
    pairs: tuple[ExperimentalTurnPair, ...] = ()
    for sequence in range(1, 6):
        candidate = make_pair(
            f"turno {sequence}", f"respuesta {sequence}", sequence=sequence, goal_revision=1
        )
        pairs, _ = append_pair(pairs, candidate, window_n=3)
    assert [pair.sequence for pair in pairs] == [3, 4, 5]
    assert window_bytes(pairs) <= MEMORY_WINDOW_BYTES


def test_window_bytes_cap_evicts_whole_pairs() -> None:
    pairs: tuple[ExperimentalTurnPair, ...] = ()
    chunk = "a" * 900
    for sequence in range(1, 6):
        pairs, _ = append_pair(
            pairs,
            make_pair(chunk, "ok", sequence=sequence, goal_revision=1),
            window_n=5,
        )
    assert window_bytes(pairs) <= MEMORY_WINDOW_BYTES
    assert len(pairs) < 5


def test_runtime_transitions_never_read_pair_text() -> None:
    """Same structured state with different texts evolves identically."""
    texts_a = [("pregunta uno", "respuesta uno"), ("pregunta dos", "respuesta dos")]
    texts_b = [("otra cosa", "distinto"), ("más texto", "sigue")]
    windows = []
    for texts in (texts_a, texts_b):
        pairs: tuple[ExperimentalTurnPair, ...] = ()
        for index, (caller, assistant) in enumerate(texts, start=1):
            pair, _ = append_pair(
                pairs,
                make_pair(caller, assistant, sequence=index, goal_revision=1),
                window_n=3,
            )
            pairs = pair
        windows.append(pairs)
    assert windows[0] != windows[1]
    procedure = open_reset()
    evolved = [
        apply_procedure_observation(procedure, ProcedureObservation.ADVANCE) for _ in windows
    ]
    assert evolved[0] == evolved[1]


# --- service opt-in ----------------------------------------------------------


async def _service_with(
    store: InMemorySessionDocumentStore, clock: FrozenClock, *, model=None
) -> TurnService:
    return TurnService(
        SessionRepository(store),
        build_turn_graph(model=model) if model is not None else build_turn_graph(),
        clock=clock,
    )


async def test_default_turn_keeps_exact_v2_shape_and_no_memory() -> None:
    from tests.session.doubles import FakeTurnModel

    store = InMemorySessionDocumentStore()
    service = await _service_with(store, FrozenClock(), model=FakeTurnModel())
    result = await service.handle_turn(
        "conversation-1", TurnInput(transcript="quiero restablecer mi contraseña")
    )
    assert result.memory is None
    assert result.record.experimental_procedure is None
    assert result.record.experimental_window == ()
    document = store.documents["conversation-1"]
    assert "experimental_procedure" not in document
    assert "experimental_window" not in document


async def test_procedure_only_turn_tracks_procedure_without_window() -> None:
    from tests.session.doubles import FakeTurnModel

    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    model.decision = make_decision(
        route=Route.COLLECT_IDENTITY,
        goal={"intent": "REQUEST", "action": "RESET_PASSWORD"},
    )
    service = await _service_with(store, FrozenClock(), model=model)
    result = await service.handle_turn(
        "conversation-1",
        TurnInput(transcript="quiero restablecer mi contraseña"),
        experimental=PROCEDURE_ONLY,
    )
    assert result.memory is not None
    assert result.record.experimental_procedure is not None
    assert result.record.experimental_procedure.current_step == GUIDED_STEPS[0]
    assert result.record.experimental_window == ()
    assert model.calls[0]["memory_context"] is not None
    assert "Procedimiento guiado" in model.calls[0]["memory_context"]


async def test_recent_memory_turn_appends_completed_pairs_only() -> None:
    from tests.session.doubles import FakeTurnModel

    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    model.decision = make_decision(
        route=Route.COLLECT_IDENTITY,
        goal={"intent": "REQUEST", "action": "RESET_PASSWORD"},
    )
    service = await _service_with(store, FrozenClock(), model=model)
    first = await service.handle_turn(
        "conversation-1", TurnInput(transcript="quiero restablecer"), experimental=RECENT_MEMORY
    )
    assert len(first.record.experimental_window) == 1
    assert first.record.experimental_window[0].sequence == 1
    # Event-only turns (no transcript, no outcome) append nothing.
    second = await service.handle_turn(
        "conversation-1",
        TurnInput(identity_outcome=IdentityOutcome.VALIDATED),
        experimental=RECENT_MEMORY,
    )
    assert len(second.record.experimental_window) == 1
    assert second.memory is not None
    assert second.memory.memory_pairs == 1


async def test_recent_memory_session_bytes_stay_within_guard() -> None:
    from tests.session.doubles import FakeTurnModel

    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    service = await _service_with(store, FrozenClock(), model=model)
    result: object = None
    for index in range(6):
        model.decision = make_decision(message=f"respuesta sintética {index}")
        result = await service.handle_turn(
            "conversation-1",
            TurnInput(transcript=f"turno sintético {index}"),
            experimental=RECENT_MEMORY,
        )
    assert result is not None
    assert len(result.record.experimental_window) == 3  # type: ignore[union-attr]
    assert result.memory is not None  # type: ignore[union-attr]
    assert result.memory.session_bytes_over_guard is False  # type: ignore[union-attr]
    assert result.memory.session_bytes < SESSION_BYTES_GUARD  # type: ignore[union-attr]
    document = store.documents["conversation-1"]
    assert session_document_bytes(document) == result.memory.session_bytes  # type: ignore[union-attr]


async def test_restart_loads_the_same_bounded_state() -> None:
    from tests.session.doubles import FakeTurnModel

    store = InMemorySessionDocumentStore()
    clock = FrozenClock()
    model = FakeTurnModel()
    model.decision = make_decision(
        route=Route.COLLECT_IDENTITY,
        goal={"intent": "REQUEST", "action": "RESET_PASSWORD"},
    )
    first_service = await _service_with(store, clock, model=model)
    await first_service.handle_turn(
        "conversation-1", TurnInput(transcript="quiero restablecer"), experimental=RECENT_MEMORY
    )
    model.decision = make_decision(procedure_observation="ADVANCE")
    await first_service.handle_turn(
        "conversation-1", TurnInput(transcript="ya completé ese paso"), experimental=RECENT_MEMORY
    )
    del first_service
    # A new process over the same session continues identically.
    restarted = await _service_with(store, clock, model=model)
    model.decision = make_decision()
    resumed = await restarted.handle_turn(
        "conversation-1", TurnInput(transcript="sigo por aquí"), experimental=RECENT_MEMORY
    )
    assert resumed.record.goal is not None
    assert resumed.record.goal.action is Action.RESET_PASSWORD
    assert resumed.record.experimental_procedure is not None
    assert resumed.record.experimental_procedure.current_step == GUIDED_STEPS[1]
    assert [pair.sequence for pair in resumed.record.experimental_window] == [1, 2, 3]
    assert model.calls[-1]["memory_context"] is not None
    # Recent-memory attribution: the first turn's caller words are still
    # readable by the model on the third turn, while procedure progress
    # survived the restart.
    assert "quiero restablecer" in model.calls[-1]["memory_context"]


async def test_identity_expiry_keeps_procedure_but_blocks_dispatch() -> None:
    from tests.session.doubles import FakeTurnModel

    store = InMemorySessionDocumentStore()
    clock = FrozenClock()
    model = FakeTurnModel()
    model.decision = make_decision(
        route=Route.COLLECT_IDENTITY,
        goal={"intent": "REQUEST", "action": "RESET_PASSWORD"},
    )
    service = await _service_with(store, clock, model=model)
    await service.handle_turn(
        "conversation-1", TurnInput(transcript="quiero restablecer"), experimental=RECENT_MEMORY
    )
    validated = await service.handle_turn(
        "conversation-1",
        TurnInput(identity_outcome=IdentityOutcome.VALIDATED),
        experimental=RECENT_MEMORY,
    )
    assert validated.record.identity_is_valid(clock())
    model.decision = make_decision(confirmation_request=True)
    challenged = await service.handle_turn(
        "conversation-1", TurnInput(transcript="sí, quiero confirmar"), experimental=RECENT_MEMORY
    )
    assert challenged.record.confirmation is not None
    # Past the absolute 30-minute TTL the authorization lapses while the
    # conversational plan and guided progress survive.
    clock.now = NOW + timedelta(minutes=31)
    model.decision = make_decision(
        confirmation_observation="AFFIRMATIVE",
    )
    expired = await service.handle_turn(
        "conversation-1", TurnInput(transcript="sí, confirmo"), experimental=RECENT_MEMORY
    )
    assert expired.record.identity_is_valid(clock()) is False
    assert expired.record.goal is not None
    assert expired.record.experimental_procedure is not None
    assert expired.record.experimental_procedure.current_step == GUIDED_STEPS[0]
    assert expired.record.dispatch is None
    violations = expired.outcome.violations if expired.outcome else ()
    assert any("dispatch" in violation for violation in violations)


def test_rendered_block_never_leaks_into_durable_helpers() -> None:
    block, render_ms = render_memory_block((), None, None, window_n=3)
    assert "Pares recientes: ninguno." in block
    assert "Procedimiento guiado: ninguno." in block
    assert render_ms >= 0.0


def test_record_without_experimental_state_round_trips() -> None:
    record = make_record()
    assert record.experimental_procedure is None
    assert record.experimental_window == ()
    document = session_record_to_document(record)
    assert "experimental_procedure" not in document
    assert SessionRecord.model_validate(document) == record


def test_experimental_record_round_trips_with_native_datetimes() -> None:
    record = make_record(
        experimental_procedure=open_reset(),
        experimental_window=(make_pair("hola", "buenas", sequence=1, goal_revision=1),),
    )
    document = session_record_to_document(record)
    assert "experimental_procedure" in document
    assert SessionRecord.model_validate(document) == record


def test_initial_state_carries_no_experimental_config_by_default() -> None:
    state = initial_graph_state(make_record(), TurnInput(), now=NOW)
    assert state["experimental_config"] is None
    assert state["experimental_procedure"] is None
    assert state["experimental_window"] == ()


# --- focused-correction guards (Exp 0009 iteration 2) ------------------------


def test_rendered_block_describes_the_current_step_actionably() -> None:
    procedure = open_reset()
    block, _ = render_memory_block((), procedure, None, window_n=3)
    assert "microsoft_portal" in block
    assert GUIDED_STEP_DESCRIPTIONS["microsoft_portal"] in block


def test_step_descriptions_cover_the_accepted_slice_only() -> None:
    assert set(GUIDED_STEP_DESCRIPTIONS) == set(GUIDED_STEPS)
    for description in GUIDED_STEP_DESCRIPTIONS.values():
        assert description.strip()


def test_rendered_block_states_the_general_observation_criteria() -> None:
    block, _ = render_memory_block((), open_reset(), None, window_n=3)
    assert "ADVANCE sólo cuando el llamante afirma que ya hizo o completó" in block
    assert "REGRESS cuando el llamante dice que NO terminó o NO hizo" in block
    assert "goal CORRECT es para precisar o cambiar" in block
    assert "responde con el nombre y la instrucción del paso actual" in block
    assert "Si un dato no está aquí" in block
    assert "Nunca prometas ejecución sin la autorización" in block


def test_procedure_schema_identity_covers_descriptions() -> None:
    first = procedure_schema_identity()
    assert first["schema"]["step_descriptions"] == GUIDED_STEP_DESCRIPTIONS
    assert procedure_schema_identity()["procedure_schema_hash"] == first["procedure_schema_hash"]


def test_default_policy_is_the_default_and_stable_choice() -> None:
    procedure = open_reset()
    default_block, _ = render_memory_block((), procedure, None, window_n=3)
    explicit_block, _ = render_memory_block(
        (), procedure, None, window_n=3, strategy=DEFAULT_PROMPT_POLICY
    )
    assert default_block == explicit_block
    assert "Criterio general de procedure_observation" in default_block
    assert ExperimentalMemoryConfig(variant="recent_conversation_memory").strategy == (
        DEFAULT_PROMPT_POLICY
    )


def test_concise_policy_is_a_strict_diet_with_identical_state_lines() -> None:
    procedure = open_reset()
    base, _ = render_memory_block((), procedure, None, window_n=3, strategy=DEFAULT_PROMPT_POLICY)
    concise, _ = render_memory_block(
        (), procedure, None, window_n=3, strategy=CONCISE_PROMPT_POLICY
    )
    base_lines = base.splitlines()
    concise_lines = concise.splitlines()
    # Header, pairs and procedure lines are shared; only the final criteria
    # line differs.
    assert base_lines[:-1] == concise_lines[:-1]
    assert base_lines[-1] != concise_lines[-1]
    assert len(" ".join(concise_lines)) < len(" ".join(base_lines))
    assert "ADVANCE" in concise_lines[-1] and "REGRESS" in concise_lines[-1]
    assert "Grounding" in concise_lines[-1]


def test_contrastive_policy_adds_exactly_two_examples() -> None:
    concise, _ = render_memory_block((), None, None, window_n=3, strategy=CONCISE_PROMPT_POLICY)
    contrastive, _ = render_memory_block(
        (), None, None, window_n=3, strategy=CONTRASTIVE_EXAMPLES_PROMPT_POLICY
    )
    assert contrastive.startswith(concise)
    assert contrastive.count("<EJEMPLO") == 2
    assert "REGRESS" in contrastive and "ADVANCE" in contrastive


def test_contrastive_examples_copy_no_corpus_utterance() -> None:
    from evals.conversation_lab import load_corpus

    block, _ = render_memory_block(
        (), None, None, window_n=3, strategy=CONTRASTIVE_EXAMPLES_PROMPT_POLICY
    )
    _, tail = block.split("<EJEMPLO", 1)
    assert tail
    for case in load_corpus():
        for turn in case.get("turns") or []:
            transcript = (turn or {}).get("transcript") or ""
            if len(transcript) > 12:
                assert transcript not in tail


def test_unknown_policy_is_rejected() -> None:
    with pytest.raises(ValueError):
        render_memory_block((), None, None, window_n=3, strategy="unknown_policy")
    with pytest.raises(ValueError):
        ExperimentalMemoryConfig(variant="recent_conversation_memory", strategy="unknown_policy")


def test_precedence_policy_prepends_to_verbatim_default() -> None:
    procedure = open_reset()
    base, _ = render_memory_block((), procedure, None, window_n=3, strategy=DEFAULT_PROMPT_POLICY)
    precedence, _ = render_memory_block(
        (), procedure, None, window_n=3, strategy=PRECEDENCE_PROMPT_POLICY
    )
    base_lines = base.splitlines()
    precedence_lines = precedence.splitlines()
    # Shared header/pairs/procedure lines; the final criteria line carries
    # the precedence prefix followed by the untouched default criteria.
    assert base_lines[:-1] == precedence_lines[:-1]
    assert precedence_lines[-1].endswith(base_lines[-1])
    assert precedence_lines[-1].index("Orden de precedencia") < precedence_lines[-1].index(
        "Criterio general"
    )
    assert "NO abras ni reabras confirmación" in precedence_lines[-1]
    assert "REGRESS con goal NONE (nunca CORRECT)" in precedence_lines[-1]
    # Minimal delta: the precedence prefix stays far below hundreds of tokens.
    assert 0 < len(precedence_lines[-1]) - len(base_lines[-1]) < 900


def test_decision_schema_documents_the_procedure_cue() -> None:
    from app.session.turns import ModelTurnDecision

    description = ModelTurnDecision.model_fields["procedure_observation"].description
    assert description is not None
    assert "REGRESS" in description
    assert "NONE" in description


def test_regress_never_revives_challenge_or_dispatch() -> None:
    from tests.session.doubles import make_challenge, make_dispatch

    procedure = open_reset()
    procedure = apply_procedure_observation(procedure, ProcedureObservation.ADVANCE)
    assert procedure is not None
    regressed = apply_procedure_observation(procedure, ProcedureObservation.REGRESS)
    assert regressed is not None
    assert regressed.current_step == GUIDED_STEPS[0]
    # The observation layer only moves steps: it cannot mint a challenge,
    # a dispatch or an authorization by itself.
    assert "challenge" not in regressed.model_dump()
    assert "dispatch" not in regressed.model_dump()
    assert make_challenge(Action.RESET_PASSWORD) is not None
    assert make_dispatch(Action.RESET_PASSWORD) is not None


async def test_regress_turn_keeps_challenge_cleared_and_dispatch_none() -> None:
    from tests.session.doubles import FakeTurnModel

    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    model.decision = make_decision(
        route=Route.COLLECT_IDENTITY,
        goal={"intent": "REQUEST", "action": "RESET_PASSWORD"},
    )
    service = await _service_with(store, FrozenClock(), model=model)
    await service.handle_turn(
        "conversation-1", TurnInput(transcript="quiero restablecer"), experimental=RECENT_MEMORY
    )
    model.decision = make_decision(procedure_observation="ADVANCE")
    await service.handle_turn(
        "conversation-1", TurnInput(transcript="ya lo hice"), experimental=RECENT_MEMORY
    )
    model.decision = make_decision(procedure_observation="REGRESS")
    regressed = await service.handle_turn(
        "conversation-1", TurnInput(transcript="no lo terminé"), experimental=RECENT_MEMORY
    )
    assert regressed.record.experimental_procedure is not None
    assert regressed.record.experimental_procedure.current_step == GUIDED_STEPS[0]
    assert regressed.record.experimental_procedure.last_completed_step is None
    assert regressed.record.confirmation is None
    assert regressed.record.dispatch is None
    assert regressed.record.goal is not None
    assert regressed.record.goal.revision == 1
