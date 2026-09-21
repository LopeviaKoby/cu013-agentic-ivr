"""Deterministic tests for the Exp 0009 lab extension; no model, no ADC."""

from __future__ import annotations

import json

from app.session.memory import ExperimentalMemoryConfig
from evals.conversation_compare import compare_runs
from evals.conversation_eval import (
    build_variant_identity,
    finalize_repetition,
    project_record,
    replay_trial,
    replay_trial_repository,
)
from evals.conversation_lab import (
    StateProjection,
    TurnObservation,
    iter_trials,
    sanitization_findings,
    turn_property_observations,
    turn_property_verdicts,
    validate_corpus,
)
from tests.evals.fixtures import NOW, ScriptedModel, make_artifact, make_case, make_decision

RECENT_MEMORY = ExperimentalMemoryConfig(variant="recent_conversation_memory")
PROCEDURE_ONLY = ExperimentalMemoryConfig(variant="procedure_progress_only")


async def _replay(case: dict, model: ScriptedModel, *, lane: str, experimental=None):  # type: ignore[no-untyped-def]
    from app.session.metrics import RecordingTurnMetrics

    metrics = RecordingTurnMetrics()
    trial_id, turn_index = iter_trials(case)[0]
    if lane == "repository":
        raw = await replay_trial_repository(
            model, metrics, case, trial_id, turn_index, now=NOW, experimental=experimental
        )
    else:
        raw = await replay_trial(
            model, metrics, case, trial_id, turn_index, now=NOW, experimental=experimental
        )
    return finalize_repetition(case, raw, repetition_id=1)


def test_procedure_oracles_match_exact_steps_and_null() -> None:
    present = _minimal_observation(StateProjection(procedure_current="microsoft_portal"))
    assert (
        turn_property_verdicts({"procedure_current": "microsoft_portal"}, present)[
            "procedure_current"
        ]
        == "PASS"
    )
    assert (
        turn_property_verdicts({"procedure_current": "tivit_portal"}, present)["procedure_current"]
        == "FAIL"
    )
    absent = _minimal_observation(StateProjection())
    assert (
        turn_property_verdicts({"procedure_current": None}, absent)["procedure_current"] == "PASS"
    )
    assert (
        turn_property_verdicts({"procedure_last_completed": None}, absent)[
            "procedure_last_completed"
        ]
        == "PASS"
    )
    assert turn_property_verdicts({}, absent)["procedure_current"] == "NOT_ORACLED"


def test_window_pairs_oracle_compares_counts() -> None:
    assert (
        turn_property_verdicts({"window_pairs": 2}, _observation_with_pairs(2))["window_pairs"]
        == "PASS"
    )
    assert (
        turn_property_verdicts({"window_pairs": 3}, _observation_with_pairs(2))["window_pairs"]
        == "FAIL"
    )
    assert turn_property_verdicts({}, _observation_with_pairs(0))["window_pairs"] == "NOT_ORACLED"


def _observation_with_pairs(count: int) -> TurnObservation:
    return _minimal_observation(StateProjection(memory_pairs=count))


def _minimal_observation(after: StateProjection) -> TurnObservation:
    return TurnObservation(
        turn_index=0,
        input_id="trial:turn1",
        event_id=None,
        event_kind=None,
        model_called=True,
        proposed_route="CONTINUE",
        proposed_goal_intent=None,
        proposed_goal_action=None,
        proposed_confirmation_request=None,
        proposed_confirmation_observation=None,
        proposed_handoff_cause=None,
        proposed_claim_kinds=[],
        runtime_route="CONTINUE",
        goal_transition="retained",
        revision_transition="same",
        confirmation_state="absent",
        confirmation_conclusion=None,
        handoff_cause=None,
        identity_valid=False,
        identity_requires_handoff=False,
        operation_state="none",
        dispatch_eligible=False,
        dispatched=False,
        dispatch_count_before=0,
        dispatch_count_after=0,
        critical_findings=[],
        blocked_proposals=[],
        state_before=StateProjection(),
        state_after=after,
        model_latency_ms=None,
        runtime_semantic_ms=0.0,
        total_turn_ms=0.0,
        prompt_tokens=None,
        completion_tokens=None,
    )


def test_corpus_validation_rejects_unknown_procedure_steps() -> None:
    case = make_case(
        scenario_kind="sequence",
        turns=[{"transcript": "uno", "expect": {"procedure_current": "invented"}}],
    )
    problems = validate_corpus([case])
    assert any("procedure_current" in problem for problem in problems)


def test_corpus_validation_rejects_negative_window_pairs() -> None:
    case = make_case(
        scenario_kind="sequence",
        turns=[{"transcript": "uno", "expect": {"window_pairs": -1}}],
    )
    problems = validate_corpus([case])
    assert any("window_pairs" in problem for problem in problems)


async def test_projection_carries_only_scalar_memory_facts() -> None:
    from app.session.metrics import RecordingTurnMetrics

    case = make_case(
        scenario_kind="sequence",
        turns=[{"transcript": "uno"}, {"transcript": "dos"}],
        expected={"conversation_goal": "RESET_PASSWORD"},
    )
    model = ScriptedModel(
        [
            make_decision(goal_intent="REQUEST", goal_action="RESET_PASSWORD"),
            make_decision(),
        ]
    )
    metrics = RecordingTurnMetrics()
    trial_id, turn_index = iter_trials(case)[0]
    raw = await replay_trial(
        model, metrics, case, trial_id, turn_index, now=NOW, experimental=RECENT_MEMORY
    )
    assert len(raw.turns) == 2
    payload = json.dumps(raw.turns[1].to_dict(), sort_keys=True)
    assert "uno" not in payload
    assert "synthetic message" not in payload


async def test_repository_lane_reloads_state_between_turns() -> None:
    case = make_case(
        scenario_kind="sequence",
        turns=[{"transcript": "uno"}, {"transcript": "dos"}],
        expected={"conversation_goal": "UNLOCK_ACCOUNT"},
    )
    model = ScriptedModel(
        [
            make_decision(goal_intent="REQUEST", goal_action="UNLOCK_ACCOUNT"),
            make_decision(),
        ]
    )
    record = await _replay(case, model, lane="repository", experimental=RECENT_MEMORY)
    assert record.turns[1].state_before.goal_action == "UNLOCK_ACCOUNT"
    assert record.turns[1].goal_transition == "retained"
    assert record.turns[1].state_after.memory_pairs == 2
    assert record.turns[0].session_bytes is not None
    assert record.turns[0].session_bytes_over_guard is False


async def test_repository_lane_matches_direct_lane_without_memory() -> None:
    case = make_case(
        turns=[{"transcript": "uno"}],
        initial_state={
            "identity_validated": True,
            "conversation_goal": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "confirmation": None,
            "pending_operation": None,
        },
        expected={"route": "CONTINUE", "conversation_goal": "UNLOCK_ACCOUNT"},
    )
    direct = await _replay(case, ScriptedModel([make_decision()]), lane="direct")
    repository = await _replay(case, ScriptedModel([make_decision()]), lane="repository")
    assert direct.classification == repository.classification == "PASS"
    assert direct.turns[0].runtime_route == repository.turns[0].runtime_route == "CONTINUE"
    # The repository lane must start from the fixture state, not a blank
    # record: the durable goal is visible before and after the turn.
    assert repository.turns[0].state_before.goal_action == "UNLOCK_ACCOUNT"
    assert repository.turns[0].state_after.goal_action == "UNLOCK_ACCOUNT"
    assert repository.turns[0].state_after.memory_pairs == 0


async def test_repository_lane_tracks_procedure_for_p() -> None:
    case = make_case(
        scenario_kind="sequence",
        turns=[{"transcript": "uno"}, {"transcript": "dos"}],
        expected={"conversation_goal": "RESET_PASSWORD"},
    )
    model = ScriptedModel(
        [
            make_decision(goal_intent="REQUEST", goal_action="RESET_PASSWORD"),
            make_decision(procedure_observation="ADVANCE"),
        ]
    )
    record = await _replay(case, model, lane="repository", experimental=PROCEDURE_ONLY)
    assert record.turns[0].state_after.procedure_current == "microsoft_portal"
    assert record.turns[1].state_after.procedure_current == "tivit_portal"
    assert record.turns[1].state_after.procedure_last_completed == "microsoft_portal"
    # Procedure-only carries no window even though turns completed.
    assert record.turns[1].state_after.memory_pairs == 0


def test_variant_identity_carries_memory_dimensions() -> None:
    identity = build_variant_identity(
        None, memory_variant="recent_conversation_memory", memory_n=3, lane="repository"
    )
    assert identity["memory_variant"] == "recent_conversation_memory"
    assert identity["memory_n"] == 3
    assert identity["lane"] == "repository"
    assert identity["memory_renderer_hash"]
    assert identity["procedure_schema_hash"]
    assert identity["prompt_strategy"] == "default_prompt_policy"
    assert identity["thinking_level"] is None


def test_variant_identity_distinguishes_policies_and_thinking() -> None:
    from app.conversation.gemini import GeminiBaseline

    default = build_variant_identity(
        None, memory_variant="recent_conversation_memory", strategy="default_prompt_policy"
    )
    concise = build_variant_identity(
        None, memory_variant="recent_conversation_memory", strategy="concise_prompt_policy"
    )
    contrastive = build_variant_identity(
        None,
        memory_variant="recent_conversation_memory",
        strategy="contrastive_examples_prompt_policy",
    )
    assert default["prompt_strategy_hash"] != concise["prompt_strategy_hash"]
    assert concise["prompt_strategy_hash"] != contrastive["prompt_strategy_hash"]
    assert (
        default["memory_renderer_hash"]
        == concise["memory_renderer_hash"]
        == contrastive["memory_renderer_hash"]
    )
    baseline = GeminiBaseline(
        project="p",
        location="us",
        model="gemini-3.1-flash-lite",
        api_version="v1",
        thinking_budget=0,
        thinking_level="MINIMAL",
        timeout_ms=15000,
        attempts=1,
    )
    identity = build_variant_identity(baseline, memory_variant="recent_conversation_memory")
    assert identity["model_id"] == "gemini-3.1-flash-lite"
    assert identity["region"] == "us"
    assert identity["thinking_level"] == "MINIMAL"


def test_usage_drain_separates_reasoning_tokens() -> None:
    from app.session.metrics import RecordingTurnMetrics
    from evals.conversation_eval import _drain_usage

    metrics = RecordingTurnMetrics()
    metrics.record_counter("prompt_tokens", 100)
    metrics.record_counter("completion_tokens", 10)
    metrics.record_counter("reasoning_tokens", 4)
    assert _drain_usage(metrics) == (100, 10, 4, False)
    metrics.record_counter("procedure_observation_emitted", 1)
    assert _drain_usage(metrics) == (None, None, None, True)
    assert _drain_usage(RecordingTurnMetrics()) == (None, None, None, False)


def test_generated_identifiers_stay_sanitizer_clean() -> None:
    from evals.conversation_lab import make_run_id, sanitization_findings, variant_digest

    for seed in range(50):
        digest = variant_digest({"seed": seed, "variant": "recent_conversation_memory"})
        run_id = make_run_id("conversation-eval", at="2026-09-18T06:44:50+00:00", digest=digest)
        assert sanitization_findings({"run_id": run_id}) == []
        assert sanitization_findings({"variant_digest": digest}) == []


async def test_observation_records_cue_value_and_emission() -> None:
    case = make_case(
        scenario_kind="sequence",
        turns=[{"transcript": "uno"}, {"transcript": "dos"}],
        expected={"conversation_goal": "RESET_PASSWORD"},
    )
    model = ScriptedModel(
        [
            make_decision(goal_intent="REQUEST", goal_action="RESET_PASSWORD"),
            make_decision(procedure_observation="ADVANCE"),
        ]
    )
    record = await _replay(case, model, lane="repository", experimental=RECENT_MEMORY)
    first, second = record.turns
    # Scripted doubles return decisions without the adapter emission counter,
    # so emission reads defaulted while the value is still observed.
    assert first.proposed_procedure_observation == "NONE"
    assert first.procedure_observation_emitted is False
    assert second.proposed_procedure_observation == "ADVANCE"
    assert second.procedure_observation_emitted is False
    baseline_identity = build_variant_identity(None)
    assert baseline_identity["memory_variant"] == "no_recent_memory"


def test_comparator_accepts_memory_variant_as_declared_variable() -> None:
    baseline = make_artifact(run_id="base")
    candidate = make_artifact(run_id="cand")
    candidate["variant"] = {
        **baseline["variant"],
        "memory_variant": "recent_conversation_memory",
    }
    comparison = compare_runs(baseline, candidate, variables=["memory_variant"], target_families=[])
    assert comparison["compatibility"]["ok"] is True
    assert "memory_variant" in comparison["compatibility"]["declared_variables"]


def test_memory_token_growth_is_explained_by_the_declared_variant() -> None:
    from evals.conversation_compare import compare_efficiency

    baseline = make_artifact(run_id="base", prompt_p50=1475.0)
    candidate = make_artifact(run_id="cand", prompt_p50=1605.0)
    efficiency = compare_efficiency(
        baseline, candidate, changed_dimensions=["memory_variant"], confounders=[]
    )
    assert efficiency["unexplained"] is False
    assert any("higher" in finding for finding in efficiency["findings"])


def test_sanitizer_flags_memory_text_keys() -> None:
    assert sanitization_findings({"caller_text": "hola"})
    assert sanitization_findings({"assistant_text": "buenas"})
    assert sanitization_findings({"memory_context": "bloque"})
    assert sanitization_findings({"transcript": "hola"})
    assert sanitization_findings({"nested": {"assistant_text": "x"}})
    assert sanitization_findings({"memory_pairs": 2}) == []


def test_projection_defaults_keep_no_memory_artifacts_stable() -> None:
    projection = StateProjection()
    assert projection.procedure_current is None
    assert projection.memory_pairs == 0
    assert projection.memory_bytes == 0
    observations = turn_property_observations(_minimal_observation(projection))
    assert observations["procedure_current"] is None
    assert observations["window_pairs"] == 0


def test_projected_record_exposes_procedure_facts() -> None:
    from tests.session.doubles import make_record

    record = make_record()
    projected = project_record(record, NOW)
    assert projected.goal_action == "RESET_PASSWORD"
    assert projected.procedure_current is None
    assert projected.memory_pairs == 0
