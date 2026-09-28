"""Ultra-scoped real-model probe for RESET confirmation semantics.

Four scenarios, one repetition by default, with the current model/config.
It reports only closed facts (verdict, next_step, mode, challenge presence,
dispatch action, latency, tokens) and never prints a message or secret.

Usage:
    python -B evals/reset_confirmation_probe.py [--repetitions 1]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from google.genai import Client
from google.genai.types import HttpOptions

from app.conversation.gemini import GeminiBaseline, GeminiTurnModel
from app.conversation.prompt_loader import load_prompt_bundle
from app.session.actions import Action
from app.session.record import AssistanceMode, OperationStatus, session_record_to_document
from app.session.repository import SessionRepository
from app.session.service import TurnService
from app.session.turns import TurnInput, build_turn_graph
from tests.session.doubles import (
    NOW,
    FrozenClock,
    InMemorySessionDocumentStore,
    make_challenge,
    make_dispatch,
    make_goal,
    make_identity,
    make_operation,
    make_record,
)


class TokenMetrics:
    """Minimal metrics seam: token counters only, never content."""

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def record_counter(self, name: str, value: int | float) -> None:
        if name == "prompt_tokens":
            self.prompt_tokens += int(value)
        elif name == "completion_tokens":
            self.completion_tokens += int(value)

    def record_segment(self, name: str, milliseconds: float) -> None:
        return None


def _seed(
    store: InMemorySessionDocumentStore,
    *,
    mode: AssistanceMode | None,
    with_challenge: bool,
) -> None:
    record = make_record(
        goal=make_goal(Action.RESET_PASSWORD, assistance_mode=mode),
        identity=make_identity(NOW),
        confirmation=(
            make_challenge(Action.RESET_PASSWORD, challenge_id="reset-challenge")
            if with_challenge
            else None
        ),
        dispatch=make_dispatch(
            Action.UNLOCK_ACCOUNT,
            revision=1,
            operation_id="operation-1",
            challenge_id="unlock-challenge",
        ),
        external_operation=make_operation(
            Action.UNLOCK_ACCOUNT, OperationStatus.CONFIRMED, operation_id="operation-1"
        ),
    )
    store.documents["conversation-1"] = session_record_to_document(record)


async def _run(
    model: GeminiTurnModel,
    *,
    mode: AssistanceMode | None,
    with_challenge: bool,
    transcript: str,
) -> dict[str, Any]:
    store = InMemorySessionDocumentStore()
    _seed(store, mode=mode, with_challenge=with_challenge)
    service = TurnService(
        SessionRepository(store),
        build_turn_graph(model=model),
        clock=FrozenClock(NOW),
    )
    started = time.monotonic()
    result = await service.handle_turn("conversation-1", TurnInput(transcript=transcript))
    latency = (time.monotonic() - started) * 1000.0
    record = result.record
    outcome = result.outcome
    dispatch = record.dispatch
    return {
        "next_step": outcome.next_step.value if outcome is not None else None,
        "goal": record.goal.action.value if record.goal is not None else None,
        "mode": (
            record.goal.assistance_mode.value
            if record.goal is not None and record.goal.assistance_mode is not None
            else None
        ),
        "challenge": record.confirmation is not None,
        "challenge_action": (
            record.confirmation.action.value if record.confirmation is not None else None
        ),
        "dispatch_action": dispatch.action.value if dispatch is not None else None,
        "dispatch_challenge": dispatch.challenge_id if dispatch is not None else None,
        "operation_action": (
            record.external_operation.action.value
            if record.external_operation is not None
            else None
        ),
        "latency_ms": round(latency, 1),
    }


async def _probe(
    model: GeminiTurnModel, repetitions: int, metrics: TokenMetrics
) -> list[dict[str, Any]]:
    scenarios = (
        (
            "affirmative_with_valid_challenge",
            AssistanceMode.AUTONOMOUS,
            True,
            "s\u00ed, te confirmo",
            lambda f: {
                "mode_preserved": f["mode"] == "AUTONOMOUS",
                "dispatched_reset": f["dispatch_action"] == "RESET_PASSWORD",
                "execute_action": f["next_step"] == "EXECUTE_ACTION",
            },
        ),
        (
            "ambiguous_with_valid_challenge",
            AssistanceMode.AUTONOMOUS,
            True,
            "siprosa",
            lambda f: {
                "mode_preserved": f["mode"] == "AUTONOMOUS",
                "no_reset_dispatch": f["dispatch_action"] == "UNLOCK_ACCOUNT",
                "no_modality_reset": f["mode"] != "UNDECIDED",
            },
        ),
        (
            "explicit_guided_switch",
            AssistanceMode.AUTONOMOUS,
            True,
            "mejor gu\u00edame paso a paso",
            lambda f: {
                "mode_guided": f["mode"] == "GUIDED",
                "no_reset_dispatch": f["dispatch_action"] == "UNLOCK_ACCOUNT",
            },
        ),
        (
            "undecided_then_autonomous",
            AssistanceMode.UNDECIDED,
            False,
            "t\u00fa hazlo",
            lambda f: {
                "mode_autonomous": f["mode"] == "AUTONOMOUS",
                "challenge_opened": f["challenge"] is True,
                "no_reset_dispatch": f["dispatch_action"] == "UNLOCK_ACCOUNT",
            },
        ),
    )
    reports: list[dict[str, Any]] = []
    for name, mode, with_challenge, transcript, checks in scenarios:
        for repetition in range(1, repetitions + 1):
            prompt_before = metrics.prompt_tokens
            completion_before = metrics.completion_tokens
            facts = await _run(
                model,
                mode=mode,
                with_challenge=with_challenge,
                transcript=transcript,
            )
            facts["prompt_tokens"] = metrics.prompt_tokens - prompt_before
            facts["completion_tokens"] = metrics.completion_tokens - completion_before
            results = checks(facts)
            reports.append(
                {
                    "case": name,
                    "repetition": repetition,
                    "verdict": "PASS" if all(results.values()) else "FAIL",
                    "checks": results,
                    "next_step": facts["next_step"],
                    "mode": facts["mode"],
                    "challenge": facts["challenge"],
                    "dispatch_action": facts["dispatch_action"],
                    "latency_ms": facts["latency_ms"],
                    "prompt_tokens": facts["prompt_tokens"],
                    "completion_tokens": facts["completion_tokens"],
                }
            )
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description="CU013 reset confirmation probe")
    parser.add_argument("--repetitions", type=int, default=1)
    args = parser.parse_args()

    try:
        prompts = load_prompt_bundle()
    except Exception as exc:  # pragma: no cover - environment failure path
        print(f"PROMPT {exc}")
        return 2

    baseline = GeminiBaseline.from_env()
    client = Client(
        vertexai=True,
        project=baseline.project,
        location=baseline.location,
        http_options=HttpOptions(api_version=baseline.api_version),
    )
    metrics = TokenMetrics()
    model = GeminiTurnModel(client, baseline, prompts=prompts, metrics=metrics)
    reports = asyncio.run(_probe(model, args.repetitions, metrics))
    passed = sum(1 for report in reports if report["verdict"] == "PASS")
    print(json.dumps({"reports": reports}, ensure_ascii=False, indent=1))
    print(f"probe summary: {passed}/{len(reports)} PASS")
    return 0 if passed == len(reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
