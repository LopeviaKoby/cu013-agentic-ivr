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
from evals.conversation_lab import TrialKind, iter_trials, load_corpus, trial_kind, turn_events

REVIEW_NOTE = (
    "LOCAL SPOKEN-QUALITY REVIEW OUTPUT — messages are printed for the owner "
    "and must never be stored in shared artifacts, logs or durable state."
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CU013 local spoken review probe")
    parser.add_argument("--families", default=None, help="comma-separated family filter")
    parser.add_argument(
        "--prompt-variant",
        choices=[PROMPT_VARIANT_PROTOCOLS, PROMPT_VARIANT_SNAPSHOT],
        default=PROMPT_VARIANT_PROTOCOLS,
    )
    parser.add_argument(
        "--few-shot-variant",
        choices=["f4", "f2", "f1", "f0"],
        default="f4",
        help="static decision-example ablation variant",
    )
    parser.add_argument(
        "--harness-language",
        choices=["es", "en"],
        default="es",
    )
    parser.add_argument("--repetitions", type=int, default=1)
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
        try:
            decision = await model.decide(
                transcript=transcript,
                goal=record.goal,
                identity_validated=record.identity_is_valid(now),
                confirmation=record.confirmation,
                external_operation=record.external_operation,
                memory_context=memory_context,
                procedure_current=(procedure.current_step if procedure is not None else None),
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
        print(f"  assistant: {decision.message}")
        state = initial_graph_state(record, turn_input, now=now, experimental=experimental)
        state["model_decision"] = decision
        record = consolidate(record, advance_turn(state), now=now)


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
    prompt_source = resolve_prompt_source(
        args.prompt_variant, args.few_shot_variant, None, args.harness_language
    )
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
                        model, case, trial_id, turn_index, now=now, experimental=experimental
                    )
    finally:
        await client.aio.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
