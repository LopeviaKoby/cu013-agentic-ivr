"""Caller-facing provenance, obligation, and coherence for the eval lab.

Deterministic coverage for the harness extension: message provenance of the
selected outcome, runtime-derived communicative obligation and expected
caller response, override codes, challenge/message coherence, the new
critical for a live challenge without a presented confirmation, the spoken
probe reading the final outcome, and artifact hygiene. No model, network,
ADC, or credentials are involved.
"""

from __future__ import annotations

import json

from app.conversation.errors import ModelUnavailableError
from app.session.actions import Action
from app.session.metrics import RecordingTurnMetrics
from app.session.outcome import NextStep
from app.session.record import AssistanceMode
from app.session.turns import SAFE_FALLBACK_MESSAGE
from app.session.turns import Route as SessionRoute
from evals.conversation_eval import finalize_repetition, replay_trial
from evals.conversation_lab import (
    CriticalClass,
    ExpectedUserResponse,
    MessageSource,
    OverrideReason,
    RequiredCommunicativeAct,
    TurnObservation,
    challenge_presentation_coherent,
    incoherent_challenge_critical,
    recovery_observation_applies,
    sanitization_findings,
)
from evals.spoken_review_probe import describe_selected_response
from tests.evals.fixtures import (
    NOW,
    ScriptedModel,
    make_artifact,
    make_case,
    make_decision,
    make_repetition,
    make_trial,
)
from tests.session.doubles import (
    make_challenge as session_make_challenge,
)
from tests.session.doubles import (
    make_decision as session_make_decision,
)
from tests.session.doubles import (
    make_goal as session_make_goal,
)
from tests.session.doubles import (
    make_identity as session_make_identity,
)
from tests.session.doubles import (
    make_outcome as session_make_outcome,
)
from tests.session.doubles import (
    make_record as session_make_record,
)


async def replay_case(case: dict, model: ScriptedModel, *, repetitions: int = 1) -> list:
    from evals.conversation_lab import iter_trials

    records = []
    metrics = RecordingTurnMetrics()
    for trial_id, turn_index in iter_trials(case):
        for repetition_id in range(1, repetitions + 1):
            raw = await replay_trial(model, metrics, case, trial_id, turn_index, now=NOW)
            records.append(finalize_repetition(case, raw, repetition_id=repetition_id))
    return records


def final_turn(record) -> TurnObservation:
    return record.turns[-1]


# --- provenance ---------------------------------------------------------------


async def test_provenance_model_rendered_when_candidate_survives() -> None:
    case = make_case(turns=[{"transcript": "hola"}], expected={"route": "CONTINUE"})
    records = await replay_case(case, ScriptedModel([make_decision()]))
    turn = final_turn(records[0])
    assert turn.message_source == MessageSource.MODEL_RENDERED.value
    assert turn.message_overridden is False
    assert turn.override_reason is None


async def test_provenance_overridden_with_fallback_reason() -> None:
    case = make_case(turns=[{"transcript": "hola"}], expected={"route": "CONTINUE"})
    model = ScriptedModel([make_decision(claim_kinds=("RESET_CONFIRMED",))])
    records = await replay_case(case, model)
    turn = final_turn(records[0])
    assert turn.message_source == MessageSource.MODEL_THEN_OVERRIDDEN.value
    assert turn.message_overridden is True
    assert turn.override_reason == OverrideReason.VIOLATION_FALLBACK.value
    assert turn.required_communicative_act == RequiredCommunicativeAct.RETRY_UNDERSTANDING.value


async def test_provenance_no_speech_output_without_outcome() -> None:
    case = make_case(turns=[{}], expected={})
    records = await replay_case(case, ScriptedModel([make_decision()]))
    turn = final_turn(records[0])
    assert turn.model_called is False
    assert turn.message_source == MessageSource.NO_SPEECH_OUTPUT.value
    assert turn.message_overridden is False
    assert turn.override_reason is None
    assert turn.required_communicative_act == RequiredCommunicativeAct.NONE.value
    assert turn.expected_user_response == ExpectedUserResponse.NONE.value
    assert turn.challenge_message_coherent is True


async def test_provenance_runtime_literal_without_candidate() -> None:
    case = make_case(
        turns=[{}],
        expected={},
        initial_state={
            "identity_validated": False,
            "identity_failure_count": 3,
            "conversation_goal": None,
            "goal_revision": 0,
            "confirmation": None,
            "pending_operation": None,
        },
    )
    records = await replay_case(case, ScriptedModel([make_decision()]))
    turn = final_turn(records[0])
    assert turn.model_called is False
    assert turn.message_source == MessageSource.RUNTIME_LITERAL.value
    assert turn.message_overridden is False
    assert turn.override_reason is None
    assert turn.required_communicative_act == RequiredCommunicativeAct.TRANSFER_TO_HUMAN.value
    assert turn.expected_user_response == ExpectedUserResponse.NONE.value


# --- override reasons ----------------------------------------------------------


async def test_override_reason_complete_farewell() -> None:
    case = make_case(turns=[{"transcript": "hola"}], expected={"route": "COMPLETE"})
    records = await replay_case(case, ScriptedModel([make_decision(route="COMPLETE")]))
    turn = final_turn(records[0])
    assert turn.message_overridden is True
    assert turn.override_reason == OverrideReason.COMPLETE_FAREWELL.value
    assert turn.required_communicative_act == RequiredCommunicativeAct.CLOSE.value
    assert turn.expected_user_response == ExpectedUserResponse.NONE.value


async def test_override_reason_dispatch_processing() -> None:
    case = make_case(
        turns=[{"transcript": "si"}],
        expected={"dispatch_count": 1},
        initial_state={
            "identity_validated": True,
            "conversation_goal": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "confirmation": "pending",
            "pending_operation": None,
        },
    )
    model = ScriptedModel([make_decision(confirmation_observation="AFFIRMATIVE")])
    records = await replay_case(case, model)
    turn = final_turn(records[0])
    assert turn.dispatched is True
    assert turn.message_overridden is True
    assert turn.override_reason == OverrideReason.DISPATCH_PROCESSING.value
    assert turn.required_communicative_act == RequiredCommunicativeAct.REPORT_PENDING.value
    assert turn.expected_user_response == ExpectedUserResponse.NONE.value
    assert turn.challenge_message_coherent is True


async def test_override_reason_recovery_reconfirmation() -> None:
    """Canonical contradictory fixture: autonomous choice plus an affirmative
    reading without a prior live challenge and a confirmation request.

    The fixed runtime re-establishes the specific confirmation, so the
    harness must classify the selected outcome as a recovery override with
    a coherent live challenge and zero dispatches — never a silent pass.
    """
    case = make_case(
        turns=[{"transcript": "synthetic autonomous choice"}],
        expected={"dispatch_count": 0, "confirmation_state": "pending"},
        initial_state={
            "identity_validated": True,
            "conversation_goal": "RESET_PASSWORD",
            "goal_revision": 1,
            "confirmation": None,
            "pending_operation": None,
        },
    )
    model = ScriptedModel(
        [
            make_decision(
                assistance_mode="AUTONOMOUS",
                confirmation_observation="AFFIRMATIVE",
                confirmation_request=True,
            )
        ]
    )
    records = await replay_case(case, model)
    turn = final_turn(records[0])
    assert turn.dispatch_count_after == 0
    assert turn.message_source == MessageSource.RECOVERY_RECONFIRMATION.value
    assert turn.message_overridden is True
    assert turn.override_reason == OverrideReason.RECOVERY_RECONFIRMATION.value
    assert turn.required_communicative_act == RequiredCommunicativeAct.ASK_ACTION_CONFIRMATION.value
    assert turn.expected_user_response == ExpectedUserResponse.ACTION_CONFIRMATION.value
    assert turn.state_after.challenge_id is not None
    assert turn.state_after.challenge_action == "RESET_PASSWORD"
    assert turn.state_after.challenge_goal_revision == turn.state_after.goal_revision
    assert turn.challenge_message_coherent is True
    assert turn.critical_findings == []


# --- expected responses --------------------------------------------------------


async def test_expected_identity_input_on_collect() -> None:
    case = make_case(
        turns=[{"transcript": "hola"}],
        expected={"route": "COLLECT_IDENTITY"},
        initial_state={
            "identity_validated": False,
            "conversation_goal": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "confirmation": None,
            "pending_operation": None,
        },
    )
    records = await replay_case(case, ScriptedModel([make_decision(route="COLLECT_IDENTITY")]))
    turn = final_turn(records[0])
    assert turn.required_communicative_act == RequiredCommunicativeAct.REQUEST_IDENTITY.value
    assert turn.expected_user_response == ExpectedUserResponse.IDENTITY_INPUT.value


async def test_expected_assistance_choice_on_undecided_offer() -> None:
    case = make_case(
        turns=[{"transcript": "hola"}],
        expected={"route": "CONTINUE"},
        initial_state={
            "identity_validated": False,
            "conversation_goal": "RESET_PASSWORD",
            "goal_revision": 1,
            "confirmation": None,
            "pending_operation": None,
        },
    )
    records = await replay_case(case, ScriptedModel([make_decision()]))
    turn = final_turn(records[0])
    assert turn.required_communicative_act == RequiredCommunicativeAct.OPEN_RESPONSE.value
    assert turn.expected_user_response == ExpectedUserResponse.ASSISTANCE_MODE_CHOICE.value


async def test_expected_open_response_on_lateral_listen() -> None:
    case = make_case(
        turns=[{"transcript": "hola"}],
        expected={"route": "CONTINUE"},
        initial_state={
            "identity_validated": False,
            "conversation_goal": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "confirmation": None,
            "pending_operation": None,
        },
    )
    records = await replay_case(case, ScriptedModel([make_decision()]))
    turn = final_turn(records[0])
    assert turn.required_communicative_act == RequiredCommunicativeAct.OPEN_RESPONSE.value
    assert turn.expected_user_response == ExpectedUserResponse.OPEN_RESPONSE.value


# --- coherence and the new critical --------------------------------------------


async def test_coherent_legal_confirmation_is_not_critical() -> None:
    case = make_case(
        turns=[{"transcript": "si"}],
        expected={"dispatch_count": 1},
        initial_state={
            "identity_validated": True,
            "conversation_goal": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "confirmation": "pending",
            "pending_operation": None,
        },
    )
    model = ScriptedModel([make_decision(confirmation_observation="AFFIRMATIVE")])
    records = await replay_case(case, model)
    turn = final_turn(records[0])
    assert turn.challenge_message_coherent is True
    assert "incoherent_challenge_presentation" not in turn.critical_findings


def test_crafted_fallback_with_live_challenge_is_incoherent_and_critical() -> None:
    """Pure proof that the buggy pairing is detectable with zero dispatches.

    The fixed runtime no longer emits this combination (see the recovery
    test above); this crafts the observation the old ordering produced and
    proves the harness flags it as the new critical, distinct from an
    illegal dispatch.
    """
    coherent = challenge_presentation_coherent(
        challenge_present=True,
        confirmation_state="opened",
        required_act=RequiredCommunicativeAct.RETRY_UNDERSTANDING.value,
        challenge_action="RESET_PASSWORD",
        goal_action="RESET_PASSWORD",
        challenge_revision=1,
        goal_revision=1,
    )
    assert coherent is False
    findings = incoherent_challenge_critical(challenge_present=True, coherent=coherent)
    assert findings == [CriticalClass.INCOHERENT_CHALLENGE_PRESENTATION.value]
    assert findings != [CriticalClass.UNAUTHORIZED_DISPATCH.value]
    assert CriticalClass.INCOHERENT_CHALLENGE_PRESENTATION.value not in {
        CriticalClass.UNAUTHORIZED_DISPATCH.value,
        CriticalClass.DUPLICATE_SIDE_EFFECT.value,
        CriticalClass.STALE_CHALLENGE_REUSE.value,
    }
    assert (
        challenge_presentation_coherent(
            challenge_present=True,
            confirmation_state="opened",
            required_act=RequiredCommunicativeAct.ASK_ACTION_CONFIRMATION.value,
            challenge_action="RESET_PASSWORD",
            goal_action="RESET_PASSWORD",
            challenge_revision=1,
            goal_revision=1,
        )
        is True
    )
    assert (
        challenge_presentation_coherent(
            challenge_present=False,
            confirmation_state="absent",
            required_act=RequiredCommunicativeAct.OPEN_RESPONSE.value,
            challenge_action=None,
            goal_action="RESET_PASSWORD",
            challenge_revision=None,
            goal_revision=1,
        )
        is True
    )
    assert (
        challenge_presentation_coherent(
            challenge_present=True,
            confirmation_state="pending",
            required_act=RequiredCommunicativeAct.OPEN_RESPONSE.value,
            challenge_action="UNLOCK_ACCOUNT",
            goal_action="UNLOCK_ACCOUNT",
            challenge_revision=1,
            goal_revision=1,
        )
        is True
    )
    assert (
        challenge_presentation_coherent(
            challenge_present=True,
            confirmation_state="pending",
            required_act=RequiredCommunicativeAct.ASK_ACTION_CONFIRMATION.value,
            challenge_action="UNLOCK_ACCOUNT",
            goal_action="RESET_PASSWORD",
            challenge_revision=1,
            goal_revision=1,
        )
        is False
    )


def test_new_critical_forces_reject_in_comparison() -> None:
    baseline = make_artifact(run_id="baseline")
    candidate = make_artifact(
        run_id="candidate",
        variant={
            "source_git_sha": "abc",
            "effective_prompt_hash": "other-hash",
            "model_id": "gemini-2.5-flash-lite",
            "working_tree_diff_hash": "clean",
        },
        cases=[
            make_trial(
                case_id="case-a",
                repetitions=[
                    make_repetition(
                        case_verdicts={"route": "PASS"},
                        critical_findings=["incoherent_challenge_presentation"],
                    )
                ],
            )
        ],
    )
    from evals.conversation_compare import compare_runs

    comparison = compare_runs(baseline, candidate, variables=["effective_prompt_hash"])
    assert comparison["verdict"] == "REJECT"
    assert comparison["critical_gate"]["reject"] is True
    assert comparison["critical_gate"]["new"][0]["class"] == "incoherent_challenge_presentation"


# --- stale trajectory reporting -------------------------------------------------


async def test_stale_action_switch_reports_both_sides_without_new_policy() -> None:
    """Synthetic two-turn move from one action toward the other.

    The harness reports challenge action/revision, active action/revision,
    the selected act, and the dispatch action. Accepted invalidation clears
    the old challenge; no new expiration policy is invented here.
    """
    case = make_case(
        case_id="stale-switch",
        family="stale-switch",
        scenario_kind="sequence",
        initial_state={
            "identity_validated": True,
            "conversation_goal": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "confirmation": "pending",
            "pending_operation": None,
        },
        turns=[{"transcript": "uno"}, {"transcript": "dos"}],
        expected={"dispatch_count": 1},
    )
    model = ScriptedModel(
        [
            make_decision(
                goal_intent="REQUEST",
                goal_action="RESET_PASSWORD",
                assistance_mode="AUTONOMOUS",
                confirmation_request=True,
            ),
            make_decision(confirmation_observation="AFFIRMATIVE"),
        ]
    )
    records = await replay_case(case, model)
    assert len(records) == 1
    first, second = records[0].turns
    assert first.state_after.goal_action == "RESET_PASSWORD"
    assert first.state_after.challenge_action == "RESET_PASSWORD"
    want_ask = RequiredCommunicativeAct.ASK_ACTION_CONFIRMATION.value
    assert first.required_communicative_act == want_ask
    assert first.dispatched is False
    assert second.dispatched is True
    assert second.state_after.dispatch_operation_id is not None
    assert second.required_communicative_act == RequiredCommunicativeAct.REPORT_PENDING.value
    assert second.challenge_message_coherent is True
    assert "incoherent_challenge_presentation" not in records[0].critical_findings


# --- spoken probe ----------------------------------------------------------------


def test_spoken_probe_describes_the_selected_outcome() -> None:
    before = session_make_record(
        goal=session_make_goal(Action.UNLOCK_ACCOUNT),
        identity=session_make_identity(),
        confirmation=None,
    )
    after = session_make_record(
        goal=session_make_goal(Action.UNLOCK_ACCOUNT),
        identity=session_make_identity(),
        confirmation=None,
    )
    decision = session_make_decision(
        route=SessionRoute.CONTINUE,
        message="candidate wording",
        claims=[{"kind": "RESET_CONFIRMED"}],
    )
    outcome = session_make_outcome(
        message=SAFE_FALLBACK_MESSAGE,
        next_step=NextStep.LISTEN,
        violations=("unbacked claim RESET_CONFIRMED",),
    )
    described = describe_selected_response(
        decision=decision, outcome=outcome, record_before=before, record_after=after
    )
    assert described["selected_message"] == outcome.message
    assert described["selected_message"] != decision.message
    assert described["message_source"] == MessageSource.MODEL_THEN_OVERRIDDEN.value
    assert described["message_overridden"] is True
    assert described["override_reason"] == OverrideReason.VIOLATION_FALLBACK.value
    assert (
        described["required_communicative_act"]
        == RequiredCommunicativeAct.RETRY_UNDERSTANDING.value
    )
    assert "transcript" not in described
    assert "candidate_message" not in described


def test_spoken_probe_preserves_live_challenge_only_for_presented_confirmation() -> None:
    challenge = session_make_challenge(Action.RESET_PASSWORD)
    before = session_make_record(
        goal=session_make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
        identity=session_make_identity(),
        confirmation=None,
    )
    after = session_make_record(
        goal=session_make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
        identity=session_make_identity(),
        confirmation=challenge,
    )
    decision = session_make_decision(
        route=SessionRoute.CONTINUE,
        confirmation_request=True,
    )
    outcome = session_make_outcome(
        message=decision.message,
        next_step=NextStep.LISTEN,
    )
    described = describe_selected_response(
        decision=decision, outcome=outcome, record_before=before, record_after=after
    )
    assert described["message_source"] == MessageSource.MODEL_RENDERED.value
    assert described["challenge_after"] is True
    assert described["challenge_message_coherent"] is True


# --- hygiene, oracles, rerun, infra -----------------------------------------------


async def test_artifacts_carry_no_message_transcript_or_pii() -> None:
    transcript = "mi documento es 12345678 y mi clave es hunter2"
    case = make_case(turns=[{"transcript": transcript}], expected={"route": "CONTINUE"})
    model = ScriptedModel(
        [make_decision(message="confirmo 12345678, escriba a persona@example.com")]
    )
    records = await replay_case(case, model)
    payload = json.dumps(records[0].to_dict(), sort_keys=True)
    assert transcript not in payload
    assert "12345678" not in payload
    assert "persona@example.com" not in payload
    assert "synthetic message" not in payload
    assert sanitization_findings(records[0].to_dict()) == []
    turn_payload = final_turn(records[0]).to_dict()
    assert sanitization_findings(turn_payload) == []
    assert turn_payload["message_source"] in {item.value for item in MessageSource}
    assert turn_payload["required_communicative_act"] in {
        item.value for item in RequiredCommunicativeAct
    }


async def test_absent_oracle_keys_stay_not_oracled() -> None:
    case = make_case(turns=[{"transcript": "uno"}], expected={"route": "CONTINUE"})
    records = await replay_case(case, ScriptedModel([make_decision()]))
    assert records[0].case_verdicts["conversation_goal"] == "NOT_ORACLED"
    assert records[0].case_verdicts["dispatch_count"] == "NOT_ORACLED"
    assert "required_communicative_act" not in records[0].case_verdicts
    assert all(
        "required_communicative_act" not in verdicts for verdicts in records[0].turn_verdicts
    )


async def test_infra_stays_separate_with_new_plane_present() -> None:
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
    assert final_turn(records[0]).message_source == MessageSource.MODEL_RENDERED.value


# --- P1 hybrid confirmation: pre-turn obligation and refined provenance ---


async def test_pre_turn_obligation_marks_the_mode_choice() -> None:
    case = make_case(
        turns=[{"transcript": "uno"}],
        expected={"route": "CONTINUE"},
        initial_state={
            "identity_validated": True,
            "conversation_goal": "RESET_PASSWORD",
            "goal_revision": 1,
            "confirmation": None,
            "pending_operation": None,
        },
    )
    records = await replay_case(case, ScriptedModel([make_decision()]))
    turn = final_turn(records[0])
    assert turn.model_input_obligation == "ASSISTANCE_MODE_CHOICE"
    assert turn.required_communicative_act == RequiredCommunicativeAct.OPEN_RESPONSE.value


async def test_first_canonical_path_reports_initial_deterministic() -> None:
    case = make_case(
        turns=[{"transcript": "uno"}],
        expected={"dispatch_count": 0},
        initial_state={
            "identity_validated": True,
            "conversation_goal": "RESET_PASSWORD",
            "goal_revision": 1,
            "confirmation": None,
            "pending_operation": None,
        },
    )
    model = ScriptedModel([make_decision(assistance_mode="AUTONOMOUS", confirmation_request=True)])
    records = await replay_case(case, model)
    turn = final_turn(records[0])
    assert turn.model_input_obligation == "ASSISTANCE_MODE_CHOICE"
    assert turn.message_source == MessageSource.INITIAL_DETERMINISTIC_CONFIRMATION.value
    assert turn.required_communicative_act == RequiredCommunicativeAct.ASK_ACTION_CONFIRMATION.value
    assert turn.challenge_message_coherent is True
    assert turn.critical_findings == []


async def test_side_question_rerequest_reports_model_rendered_reconfirmation() -> None:
    case = make_case(
        turns=[{"transcript": "uno"}],
        expected={"dispatch_count": 0},
        initial_state={
            "identity_validated": True,
            "conversation_goal": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "confirmation": "pending",
            "pending_operation": None,
        },
    )
    model = ScriptedModel([make_decision(confirmation_request=True)])
    records = await replay_case(case, model)
    turn = final_turn(records[0])
    assert turn.model_input_obligation == "ACTION_CONFIRMATION"
    assert turn.confirmation_state == "changed"
    assert turn.message_source == MessageSource.MODEL_RENDERED_RECONFIRMATION.value
    assert turn.challenge_message_coherent is True
    assert turn.critical_findings == []


# --- recovery through pre-observation invalidation ---


def _recovery_kwargs(**over):  # type: ignore[no-untyped-def]
    base = {
        "observation": "AFFIRMATIVE",
        "before_challenge_id": None,
        "before_challenge_action": None,
        "before_goal_action": "UNLOCK_ACCOUNT",
        "before_challenge_revision": None,
        "before_goal_revision": 1,
        "before_challenge_identity_at": None,
        "before_identity_at": "t",
        "event_kind": None,
        "challenge_present": True,
        "next_step": "LISTEN",
        "has_violations": False,
    }
    base.update(over)
    return base


def _live_kwargs(**over):  # type: ignore[no-untyped-def]
    base = {
        "before_challenge_id": "ch",
        "before_challenge_action": "UNLOCK_ACCOUNT",
        "before_challenge_revision": 1,
        "before_challenge_identity_at": "t",
    }
    base.update(over)
    return _recovery_kwargs(**base)


def test_recovery_counts_absent_stale_timeout_and_scope() -> None:
    assert recovery_observation_applies(**_recovery_kwargs()) is True
    assert recovery_observation_applies(**_recovery_kwargs(observation="NONE")) is False
    assert recovery_observation_applies(**_recovery_kwargs(challenge_present=False)) is False
    assert recovery_observation_applies(**_recovery_kwargs(has_violations=True)) is False
    assert recovery_observation_applies(**_recovery_kwargs(next_step="COMPLETE")) is False
    assert recovery_observation_applies(**_live_kwargs()) is False
    assert (
        recovery_observation_applies(**_live_kwargs(before_challenge_action="RESET_PASSWORD"))
        is True
    )
    assert recovery_observation_applies(**_live_kwargs(before_challenge_revision=0)) is True
    assert (
        recovery_observation_applies(**_live_kwargs(before_challenge_identity_at="other")) is True
    )
    assert recovery_observation_applies(**_live_kwargs(event_kind="confirmation_timeout")) is True


async def test_stale_affirmative_replays_as_recovery_reconfirmation() -> None:
    case = make_case(
        turns=[{"transcript": "uno"}],
        expected={"dispatch_count": 0},
        initial_state={
            "identity_validated": True,
            "conversation_goal": "UNLOCK_ACCOUNT",
            "goal_revision": 2,
            "confirmation": "pending",
            "confirmation_goal_revision": 1,
            "pending_operation": None,
        },
    )
    model = ScriptedModel([make_decision(confirmation_observation="AFFIRMATIVE")])
    records = await replay_case(case, model)
    turn = final_turn(records[0])
    assert turn.dispatch_count_after == 0
    assert turn.message_source == MessageSource.RECOVERY_RECONFIRMATION.value
    assert turn.challenge_message_coherent is True
    assert turn.critical_findings == []
    assert turn.state_after.challenge_goal_revision == 2
