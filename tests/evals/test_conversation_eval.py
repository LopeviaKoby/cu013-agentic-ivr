"""Deterministic tests for the conversation evaluator; no model, no ADC."""

from __future__ import annotations

import json

import pytest

from app.conversation.errors import InvalidModelOutputError, ModelUnavailableError
from app.conversation.gemini import active_conversation_baseline
from app.session.metrics import RecordingTurnMetrics
from evals.conversation_eval import finalize_repetition, replay_trial, sequence_series
from evals.conversation_lab import (
    RepetitionObservation,
    ToolObservation,
    TurnObservation,
    iter_trials,
    load_corpus,
    summarize_tokens,
    validate_corpus,
)
from tests.evals.fixtures import NOW, ScriptedModel, make_case, make_decision


async def replay_case(
    case: dict,
    model: ScriptedModel,
    *,
    repetitions: int = 1,
    metrics: RecordingTurnMetrics | None = None,
) -> list[RepetitionObservation]:
    records: list[RepetitionObservation] = []
    owned_metrics = metrics or RecordingTurnMetrics()
    for trial_id, turn_index in iter_trials(case):
        for repetition_id in range(1, repetitions + 1):
            raw = await replay_trial(model, owned_metrics, case, trial_id, turn_index, now=NOW)
            records.append(finalize_repetition(case, raw, repetition_id=repetition_id))
    return records


def final_turn(record: RepetitionObservation) -> TurnObservation:
    return record.turns[-1]


async def test_independent_paraphrases_start_from_fresh_state() -> None:
    case = make_case(
        turns=[{"transcript": "uno"}, {"transcript": "dos"}],
        expected={"conversation_goal": "unchanged"},
    )
    model = ScriptedModel(
        [
            make_decision(goal_intent="REQUEST", goal_action="UNLOCK_ACCOUNT"),
            make_decision(goal_intent="REQUEST", goal_action="RESET_PASSWORD"),
        ]
    )
    records = await replay_case(case, model, repetitions=2)
    assert len(records) == 4
    for record in records:
        assert record.turns[0].state_before.goal_action is None
        assert record.turns[0].state_before.identity_validated is False


async def test_sequence_retains_state_between_turns() -> None:
    case = make_case(
        scenario_kind="sequence",
        turns=[{"transcript": "uno"}, {"transcript": "dos"}],
        expected={"conversation_goal": "UNLOCK_ACCOUNT"},
    )
    model = ScriptedModel(
        [
            make_decision(goal_intent="REQUEST", goal_action="UNLOCK_ACCOUNT"),
            make_decision(goal_intent="NONE"),
        ]
    )
    records = await replay_case(case, model)
    assert len(records) == 1
    turns = records[0].turns
    assert turns[0].state_after.goal_action == "UNLOCK_ACCOUNT"
    assert turns[1].state_before.goal_action == "UNLOCK_ACCOUNT"
    assert turns[1].goal_transition == "retained"
    assert turns[1].revision_transition == "same"


async def test_correction_on_same_action_stays_retained_and_bumps_revision() -> None:
    case = make_case(
        scenario_kind="sequence",
        turns=[{"transcript": "uno"}, {"transcript": "dos"}],
        expected={"conversation_goal": "UNLOCK_ACCOUNT"},
    )
    model = ScriptedModel(
        [
            make_decision(goal_intent="REQUEST", goal_action="UNLOCK_ACCOUNT"),
            make_decision(goal_intent="CORRECT", goal_action="UNLOCK_ACCOUNT"),
        ]
    )
    records = await replay_case(case, model)
    turns = records[0].turns
    assert turns[1].goal_transition == "retained"
    assert turns[1].revision_transition == "incremented"


async def test_pre_existing_authorized_dispatch_still_counts_as_authorized() -> None:
    case = make_case(
        turns=[{"transcript": "hazlo otra vez"}],
        initial_state={
            "identity_validated": True,
            "conversation_goal": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "confirmation": "authorized",
            "pending_operation": "pending",
        },
        expected={
            "route": "CONTINUE",
            "confirmation_state": "authorized",
            "dispatch_count": 0,
        },
    )
    records = await replay_case(case, ScriptedModel([make_decision()]))
    assert records[0].classification == "PASS"


async def test_replaced_challenge_still_records_the_old_conclusion() -> None:
    case = make_case(
        turns=[{"transcript": "mejor no, solo necesito desbloquear la cuenta"}],
        initial_state={
            "identity_validated": True,
            "conversation_goal": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "confirmation": "pending",
            "pending_operation": None,
        },
        expected={
            "route": "CONTINUE",
            "conversation_goal": "UNLOCK_ACCOUNT",
            "confirmation_state": "invalidated",
            "dispatch_count": 0,
        },
    )
    model = ScriptedModel(
        [
            make_decision(
                goal_intent="CORRECT",
                goal_action="UNLOCK_ACCOUNT",
                confirmation_request=True,
            )
        ]
    )
    records = await replay_case(case, model)
    assert final_turn(records[0]).confirmation_state == "changed"
    assert final_turn(records[0]).confirmation_conclusion == "invalidated"
    assert records[0].case_verdicts["confirmation_state"] == "PASS"
    assert records[0].classification == "PASS"


async def test_route_is_not_oracled_when_the_turn_carries_no_speech() -> None:
    case = make_case(
        turns=[{"transcript": ""}],
        initial_state={
            "identity_validated": True,
            "conversation_goal": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "confirmation": "pending",
            "pending_operation": None,
        },
        expected={"route": "CONTINUE", "confirmation_state": "invalidated"},
        external_events=[{"event": "confirmation_timeout"}],
    )
    records = await replay_case(case, ScriptedModel([make_decision()]))
    assert records[0].case_verdicts["route"] == "NOT_ORACLED"
    assert records[0].case_verdicts["confirmation_state"] == "PASS"
    assert records[0].classification == "PASS"


async def test_per_repetition_verdicts_are_preserved() -> None:
    # The route is not oracled here: a pending pre-auth goal projects the
    # residual CONTINUE proposal onto COLLECT_IDENTITY by owner precedence.
    case = make_case(
        turns=[{"transcript": "uno"}],
        expected={"conversation_goal": "UNLOCK_ACCOUNT"},
    )
    model = ScriptedModel(
        [
            make_decision(goal_intent="REQUEST", goal_action="UNLOCK_ACCOUNT"),
            make_decision(),
            make_decision(goal_intent="REQUEST", goal_action="UNLOCK_ACCOUNT"),
        ]
    )
    records = await replay_case(case, model, repetitions=3)
    classifications = [record.classification for record in records]
    assert classifications == ["PASS", "FAIL", "PASS"]
    assert records[1].case_verdicts["conversation_goal"] == "FAIL"
    assert records[0].case_verdicts["conversation_goal"] == "PASS"
    assert records[2].case_verdicts["conversation_goal"] == "PASS"


async def test_absent_oracle_key_is_not_oracled() -> None:
    case = make_case(turns=[{"transcript": "uno"}], expected={"route": "CONTINUE"})
    records = await replay_case(case, ScriptedModel([make_decision()]))
    assert records[0].case_verdicts["conversation_goal"] == "NOT_ORACLED"
    assert records[0].case_verdicts["dispatch_count"] == "NOT_ORACLED"
    assert records[0].classification == "PASS"


async def test_null_expected_value_asserts_absence() -> None:
    case = make_case(turns=[{"transcript": "uno"}], expected={"conversation_goal": None})
    passing = await replay_case(case, ScriptedModel([make_decision()]))
    assert passing[0].case_verdicts["conversation_goal"] == "PASS"
    failing = await replay_case(
        case,
        ScriptedModel([make_decision(goal_intent="REQUEST", goal_action="UNLOCK_ACCOUNT")]),
    )
    assert failing[0].case_verdicts["conversation_goal"] == "FAIL"
    assert failing[0].classification == "FAIL"


async def test_property_level_not_representable() -> None:
    case = make_case(
        turns=[{"transcript": "uno"}],
        expected={"route": "CONTINUE", "wibble": True},
    )
    records = await replay_case(case, ScriptedModel([make_decision()]))
    assert records[0].case_verdicts["wibble"] == "NOT_REPRESENTABLE"
    assert records[0].classification == "NOT_REPRESENTABLE"
    problems = validate_corpus([case])
    assert any("not representable" in problem for problem in problems)


async def test_infra_at_one_repetition_does_not_erase_valid_repetitions() -> None:
    case = make_case(turns=[{"transcript": "uno"}], expected={"route": "CONTINUE"})
    model = ScriptedModel(
        [
            make_decision(),
            ModelUnavailableError("vertex unreachable"),
            make_decision(),
        ]
    )
    records = await replay_case(case, model, repetitions=3)
    assert [record.status for record in records] == ["valid", "infra", "valid"]
    assert [record.classification for record in records] == ["PASS", "INFRA", "PASS"]
    assert records[1].case_verdicts == {}


async def test_invalid_structured_output_is_not_infra() -> None:
    case = make_case(turns=[{"transcript": "uno"}], expected={"route": "CONTINUE"})
    model = ScriptedModel([InvalidModelOutputError("bad json")])
    records = await replay_case(case, model)
    assert records[0].status == "valid"
    assert records[0].classification == "MODEL_FAILURE"
    assert records[0].error_class == "InvalidModelOutputError"


async def test_missing_token_usage_stays_missing() -> None:
    case = make_case(turns=[{"transcript": "uno"}], expected={"route": "CONTINUE"})
    records = await replay_case(case, ScriptedModel([make_decision()]))
    payload = final_turn(records[0]).to_dict()
    assert payload["prompt_tokens"] is None
    assert payload["completion_tokens"] is None
    assert json.loads(json.dumps(payload))["prompt_tokens"] is None
    summary = summarize_tokens([], missing=1)
    assert summary["count"] == 0
    assert summary["missing"] == 1


async def test_token_usage_is_recorded_when_available() -> None:
    metrics = RecordingTurnMetrics()
    case = make_case(turns=[{"transcript": "uno"}], expected={"route": "CONTINUE"})
    model = ScriptedModel([make_decision()], metrics=metrics)
    records = await replay_case(case, model, metrics=metrics)
    payload = final_turn(records[0]).to_dict()
    assert payload["prompt_tokens"] == 1234
    assert payload["completion_tokens"] == 56


async def test_retained_evidence_contains_no_transcript_or_dtmf() -> None:
    transcript = "mi documento es 12345678 y mi clave es hunter2"
    case = make_case(turns=[{"transcript": transcript}], expected={"route": "CONTINUE"})
    model = ScriptedModel(
        [
            make_decision(
                message="confirmo 12345678, escriba a persona@example.com",
            )
        ]
    )
    records = await replay_case(case, model)
    payload = json.dumps(records[0].to_dict(), sort_keys=True)
    assert transcript not in payload
    assert "12345678" not in payload
    assert "persona@example.com" not in payload
    assert "synthetic message" not in payload


async def test_sequence_series_reports_cumulative_growth() -> None:
    metrics = RecordingTurnMetrics()
    case = make_case(
        scenario_kind="sequence",
        turns=[{"transcript": "uno"}, {"transcript": "dos"}],
        expected={"conversation_goal": "UNLOCK_ACCOUNT"},
    )
    model = ScriptedModel(
        [
            make_decision(goal_intent="REQUEST", goal_action="UNLOCK_ACCOUNT"),
            make_decision(),
        ],
        metrics=metrics,
    )
    records = await replay_case(case, model, metrics=metrics)
    series = sequence_series(case, records)
    assert len(series) == 2
    assert series[0]["prompt_tokens_cumulative_mean"] == 1234.0
    assert series[1]["prompt_tokens_cumulative_mean"] == 2468.0
    assert series[1]["completion_tokens_cumulative_mean"] == 112.0
    assert series[1]["prompt_tokens_per_call"]["p50"] == 1234.0


def test_turn_observation_exposes_future_tool_schema() -> None:
    tool = ToolObservation(
        selected_capability="example_capability",
        arguments_semantic_result="accepted",
        required_arguments_present=True,
        forbidden_sensitive_arguments_absent=True,
        prerequisites_satisfied=True,
        runtime_execution="allowed",
        duplicate_tool_decision=False,
        result_operation_attribution="operation-1",
        communicated_truth_supported=True,
    )
    payload = tool.to_dict()
    assert payload["runtime_execution"] == "allowed"
    assert payload["forbidden_sensitive_arguments_absent"] is True
    assert set(payload) == {
        "selected_capability",
        "arguments_semantic_result",
        "required_arguments_present",
        "forbidden_sensitive_arguments_absent",
        "prerequisites_satisfied",
        "runtime_execution",
        "duplicate_tool_decision",
        "result_operation_attribution",
        "communicated_truth_supported",
    }


async def test_operation_projection_covers_pending_operation_states() -> None:
    case = make_case(
        turns=[{"transcript": "una"}],
        initial_state={
            "identity_validated": True,
            "conversation_goal": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "confirmation": None,
            "pending_operation": "unknown",
        },
        expected={"conversation_goal": "UNLOCK_ACCOUNT"},
    )
    records = await replay_case(case, ScriptedModel([make_decision()]))
    assert final_turn(records[0]).state_before.operation_status == "unknown"
    assert final_turn(records[0]).state_before.operation_delivery is None


async def test_every_corpus_case_replays_with_a_neutral_model() -> None:
    corpus = load_corpus()
    assert corpus
    for case in corpus:
        model = ScriptedModel([make_decision()])
        records = await replay_case(case, model, repetitions=1)
        for record in records:
            assert record.turns, case["case_id"]
            assert record.classification, case["case_id"]


@pytest.mark.parametrize("event", ["identity_validation", "confirmation_timeout"])
async def test_event_only_case_replays_without_model_call(event: str) -> None:
    events = (
        [{"event": "identity_validation", "result": "validated"}]
        if event == "identity_validation"
        else [{"event": "confirmation_timeout"}]
    )
    initial_state = (
        {"identity_validated": False, "conversation_goal": "UNLOCK_ACCOUNT"}
        if event == "identity_validation"
        else {"identity_validated": True, "conversation_goal": "UNLOCK_ACCOUNT"}
    )
    case = make_case(
        scenario_kind="sequence",
        turns=[{"transcript": "listo", "events": events}],
        initial_state=initial_state,
        expected={"conversation_goal": "UNLOCK_ACCOUNT"},
    )
    model = ScriptedModel([make_decision()])
    records = await replay_case(case, model)
    assert final_turn(records[0]).event_kind == event
    assert records[0].turns[0].model_called is True


# --- prompt composition lane (Experiment 0011) -------------------------------


def test_snapshot_prompt_fixture_round_trips_without_its_header(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from evals.conversation_eval import load_snapshot_prompt

    fixture = tmp_path / "fixture.md"
    fixture.write_text(
        "<!-- EVALUATION FIXTURE — NOT PRODUCT DOCUMENTATION\n"
        "SOURCE SHA: synthetic\n"
        "-->\n"
        "line one\r\nline two\n",
        encoding="utf-8",
        newline="",
    )
    prompt = load_snapshot_prompt(fixture)
    assert prompt.text == "line one\nline two"
    assert "EVALUATION FIXTURE" not in prompt.text


def test_snapshot_prompt_rejects_unlabeled_fixtures(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from evals.conversation_eval import load_snapshot_prompt

    fixture = tmp_path / "fixture.md"
    fixture.write_text("no label, no terminator", encoding="utf-8")
    with pytest.raises(ValueError):
        load_snapshot_prompt(fixture)


def test_prompt_composition_identity_retains_only_fingerprints() -> None:
    from evals.conversation_eval import prompt_composition_identity
    from tests.conversation.prompt_fixtures import SYNTHETIC_RESET_BODY, make_bundle

    identity = prompt_composition_identity(make_bundle())
    payload = json.dumps(identity)
    assert identity["mode"] == "prompt_composition_protocols"
    assert identity["composition_orders"]["RESET_PASSWORD"] == [
        "core.md",
        "catalog.md",
        "RESET_PASSWORD.runtime.md",
        "few_shot.md",
    ]
    assert identity["protocol_projection_mode"] == ["step_window"]
    assert identity["few_shot_variant"] == "few_shot.md"
    assert identity["renderer_sha256"]
    assert identity["loader_sha256"]
    assert SYNTHETIC_RESET_BODY not in payload


class _CountResponse:
    def __init__(self, total: int) -> None:
        self.total_tokens = total


class _CountModels:
    def __init__(self, *, fail: bool) -> None:
        self.calls: list[str] = []
        self.fail = fail

    async def count_tokens(self, *, model: str, contents: str) -> _CountResponse:
        self.calls.append(contents)
        if self.fail:
            raise RuntimeError("synthetic provider failure")
        return _CountResponse(len(contents))


class _CountAio:
    def __init__(self, models: _CountModels) -> None:
        self.models = models


class _CountClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.models_double = _CountModels(fail=fail)
        self.aio = _CountAio(self.models_double)


async def test_token_breakdown_counts_numbers_only() -> None:
    from evals.conversation_eval import token_composition_breakdown
    from tests.conversation.prompt_fixtures import SYNTHETIC_RESET_BODY, make_bundle

    client = _CountClient()
    result = await token_composition_breakdown(
        client,  # type: ignore[arg-type]
        active_conversation_baseline(),
        make_bundle(),
    )
    buckets = result["buckets"]
    assert result["missing"] == []
    assert buckets["system_instruction:RESET_PASSWORD"] > 0
    assert buckets["transcript_sample"] > 0
    assert all(isinstance(value, int) for value in buckets.values())
    assert SYNTHETIC_RESET_BODY not in json.dumps(result)
    assert len(client.models_double.calls) == len(buckets)


async def test_token_breakdown_missing_buckets_never_become_zero() -> None:
    from evals.conversation_eval import token_composition_breakdown
    from tests.conversation.prompt_fixtures import make_bundle

    client = _CountClient(fail=True)
    result = await token_composition_breakdown(
        client,  # type: ignore[arg-type]
        active_conversation_baseline(),
        make_bundle(),
    )
    assert result["buckets"] == {}
    assert result["missing"]
