"""Local spoken-quality review probe for CU013 (manual, outside CI).

It replays selected corpus cases against the real model and prints the caller
turn and the assistant message per case ID so the owner can judge brevity,
naturalness, one-main-question, non-repetition, orientation, contextual
coherence and return to the procedure. Output is local review material only:
nothing is written to artifacts, and message text must never be copied into
shared evidence or durable state.

Usage:
    python evals/spoken_review_probe.py --prompt-variant prompt_composition_protocols \
        --families ambiguous-reset-unlock,long-conversation-memory
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from google.genai import Client
from google.genai.types import HttpOptions

from app.conversation.errors import (
    InvalidModelOutputError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.conversation.gemini import GeminiBaseline, GeminiTurnModel
from app.session.memory import (
    DEFAULT_PROMPT_POLICY,
    RECENT_CONVERSATION_MEMORY,
    ExperimentalMemoryConfig,
    render_memory_block,
)
from app.session.service import consolidate
from app.session.turns import advance_turn, initial_graph_state
from evals.conversation_eval import (
    PROMPT_VARIANT_PROTOCOLS,
    PROMPT_VARIANT_SNAPSHOT,
    build_initial_record,
    build_turn_input,
    resolve_prompt_source,
)
from evals.conversation_lab import (
    TrialKind,
    challenge_presentation_coherent,
    derive_expected_response,
    derive_message_source,
    derive_override_reason,
    derive_required_act,
    iter_trials,
    load_corpus,
    trial_kind,
    turn_events,
)

REVIEW_NOTE = (
    "LOCAL SPOKEN-QUALITY REVIEW OUTPUT — messages are printed for the owner "
    "and must never be stored in shared artifacts, logs or durable state."
)


def describe_selected_response(
    *, decision: Any, outcome: Any, record_before: Any, record_after: Any
) -> dict[str, Any]:
    """Closed caller-facing description of the selected outcome.

    Derives provenance, obligation, expected response, override reason, and
    coherence from closed facts only. The returned ``selected_message`` is
    for local human display in this probe; it must never be persisted in
    ``evals/results``, git, logs, or shared artifacts.
    """
    decision_exists = decision is not None
    outcome_exists = outcome is not None
    selected_message = outcome.message if outcome_exists else None
    message_overridden = decision_exists and outcome_exists and outcome.message != decision.message
    next_step = outcome.next_step.value if outcome_exists else None
    has_violations = bool(outcome.violations) if outcome_exists else False
    before_challenge = record_before.confirmation if record_before is not None else None
    after_challenge = record_after.confirmation if record_after is not None else None
    challenge_present = after_challenge is not None
    before_id = before_challenge.challenge_id if before_challenge is not None else None
    after_id = after_challenge.challenge_id if after_challenge is not None else None
    if after_id is None:
        confirmation_state = "absent"
    elif before_id is None:
        confirmation_state = "opened"
    elif before_id == after_id:
        confirmation_state = "pending"
    else:
        confirmation_state = "changed"
    observation = getattr(getattr(decision, "confirmation_observation", None), "value", None)
    is_recovery = (
        decision_exists
        and observation == "AFFIRMATIVE"
        and before_id is None
        and challenge_present
        and next_step == "LISTEN"
        and not has_violations
    )
    goal = record_after.goal if record_after is not None else None
    goal_action = goal.action.value if goal is not None else None
    assistance_mode = (
        goal.assistance_mode.value
        if goal is not None and goal.assistance_mode is not None
        else None
    )
    message_source = derive_message_source(
        decision_exists=decision_exists,
        outcome_exists=outcome_exists,
        message_overridden=message_overridden,
    )
    required_act = derive_required_act(
        outcome_exists=outcome_exists,
        next_step=next_step,
        has_violations=has_violations,
        challenge_present=challenge_present,
        decision_request=(decision.confirmation_request if decision_exists else None),
        is_recovery=is_recovery,
    )
    expected_response = derive_expected_response(
        outcome_exists=outcome_exists,
        required_act=required_act,
        goal_action=goal_action,
        assistance_mode=assistance_mode,
    )
    override_reason = derive_override_reason(
        message_overridden=message_overridden,
        next_step=next_step,
        has_violations=has_violations,
        is_recovery=is_recovery,
    )
    coherent = challenge_presentation_coherent(
        challenge_present=challenge_present,
        confirmation_state=confirmation_state,
        required_act=required_act,
        challenge_action=(after_challenge.action.value if after_challenge is not None else None),
        goal_action=goal_action,
        challenge_revision=(after_challenge.goal_revision if after_challenge is not None else None),
        goal_revision=(goal.revision if goal is not None else None),
    )
    return {
        "selected_message": selected_message,
        "message_source": message_source,
        "message_overridden": message_overridden,
        "override_reason": override_reason,
        "required_communicative_act": required_act,
        "expected_user_response": expected_response,
        "next_step": next_step,
        "challenge_after": challenge_present,
        "challenge_action": (after_challenge.action.value if after_challenge is not None else None),
        "challenge_message_coherent": coherent,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CU013 local spoken review probe")
    parser.add_argument("--families", default=None, help="comma-separated family filter")
    parser.add_argument(
        "--prompt-variant",
        choices=[PROMPT_VARIANT_PROTOCOLS, PROMPT_VARIANT_SNAPSHOT],
        default=PROMPT_VARIANT_PROTOCOLS,
    )
    parser.add_argument(
        "--harness-language",
        choices=["es", "en"],
        default="es",
    )
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument(
        "--semantic-obligation",
        choices=["off", "p1"],
        default="off",
        help="P1 candidate lane: render the ephemeral semantic-obligation block",
    )
    return parser.parse_args(argv)


def selected_turns(case: dict[str, Any], turn_index: int | None) -> list[dict[str, Any]]:
    turns = list(case.get("turns") or [])
    if trial_kind(case) is TrialKind.SEQUENCE:
        return turns or [{}]
    if turn_index is None:
        return [{}]
    return [turns[turn_index]]


async def review_case(
    model: GeminiTurnModel,
    case: dict[str, Any],
    trial_id: str,
    turn_index: int | None,
    *,
    now: datetime,
    experimental: ExperimentalMemoryConfig,
    include_semantic_obligation: bool = False,
) -> None:
    record = build_initial_record(case, now)
    turns = selected_turns(case, turn_index)
    for index, turn in enumerate(turns):
        is_last = index == len(turns) - 1
        events = turn_events(case, turn, is_last=is_last)
        transcript = turn.get("transcript")
        if transcript is None:
            print(f"[{case['case_id']} {trial_id} t{index + 1}] (no caller speech; event only)")
            continue
        turn_input = build_turn_input(events, transcript)
        memory_context, _ = render_memory_block(
            record.experimental_window,
            record.experimental_procedure,
            record.experimental_suspended,
            window_n=experimental.window_n,
            strategy=experimental.strategy,
        )
        procedure = record.experimental_procedure
        semantic_block: str | None = None
        if include_semantic_obligation:
            from app.session.semantic_obligation import (
                derive_semantic_obligation,
                render_semantic_obligation,
            )

            semantic_block = render_semantic_obligation(
                derive_semantic_obligation(
                    goal=record.goal,
                    identity=record.identity,
                    confirmation=record.confirmation,
                    external_operation=record.external_operation,
                    password_presentation=record.password_presentation,
                    now=now,
                )
            )
        try:
            decision = await model.decide(
                transcript=transcript,
                goal=record.goal,
                identity_validated=record.identity_is_valid(now),
                confirmation=record.confirmation,
                external_operation=record.external_operation,
                memory_context=memory_context,
                procedure_current=(procedure.current_step if procedure is not None else None),
                semantic_obligation=semantic_block,
            )
        except (ModelTimeoutError, ModelUnavailableError) as exc:
            print(f"[{case['case_id']} {trial_id} t{index + 1}] INFRA {type(exc).__name__}")
            return
        except InvalidModelOutputError as exc:
            print(f"[{case['case_id']} {trial_id} t{index + 1}] MODEL_FAILURE {type(exc).__name__}")
            return
        print(
            f"[{case['case_id']} {trial_id} t{index + 1}] "
            f"route={decision.route.value} "
            f"goal={decision.goal.intent.value if decision.goal else 'NONE'}"
            f"/{decision.goal.action.value if decision.goal and decision.goal.action else '-'} "
            f"procedure={decision.procedure_observation.value} "
            f"confirmation_request={decision.confirmation_request}"
        )
        print(f"  caller: {transcript}")
        state = initial_graph_state(record, turn_input, now=now, experimental=experimental)
        state["model_decision"] = decision
        record_before = record
        delta = advance_turn(state)
        record = consolidate(record, delta, now=now)
        selected = describe_selected_response(
            decision=decision,
            outcome=delta["outcome"],
            record_before=record_before,
            record_after=record,
        )
        print(f"  assistant (selected): {selected['selected_message']}")
        print(
            "  selected_metadata: "
            f"message_source={selected['message_source']} "
            f"required_communicative_act={selected['required_communicative_act']} "
            f"expected_user_response={selected['expected_user_response']} "
            f"override_reason={selected['override_reason']} "
            f"next_step={selected['next_step']} "
            f"challenge_after={selected['challenge_after']} "
            f"challenge_action={selected['challenge_action']} "
            f"challenge_message_coherent={selected['challenge_message_coherent']}"
        )


async def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases = load_corpus()
    if args.families:
        wanted = {family.strip() for family in args.families.split(",")}
        cases = [case for case in cases if case["family"] in wanted]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2
    print(REVIEW_NOTE)
    prompt_source = resolve_prompt_source(args.prompt_variant, args.harness_language)
    baseline = GeminiBaseline.from_env()
    client = Client(
        vertexai=True,
        project=baseline.project,
        location=baseline.location,
        http_options=HttpOptions(api_version=baseline.api_version),
    )
    model = GeminiTurnModel(client, baseline, prompts=prompt_source)
    experimental = ExperimentalMemoryConfig(
        variant=RECENT_CONVERSATION_MEMORY,
        window_n=3,
        strategy=DEFAULT_PROMPT_POLICY,
    )
    now = datetime.now(UTC)
    try:
        for case in cases:
            for trial_id, turn_index in iter_trials(case):
                for _ in range(args.repetitions):
                    await review_case(
                        model,
                        case,
                        trial_id,
                        turn_index,
                        now=now,
                        experimental=experimental,
                        include_semantic_obligation=(args.semantic_obligation == "p1"),
                    )
    finally:
        await client.aio.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
