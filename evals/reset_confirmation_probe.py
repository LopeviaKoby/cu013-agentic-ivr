"""Focused real-model probe for the RESET modality selection turn.

F1 of the Ivr01-1790609256.7975 diagnosis: the exact observed state
(RESET/UNDECIDED, valid identity, historical UNLOCK confirmed, no challenge)
plus four explicit autonomous-selection phrases. It records only closed
semantic facts from the structured decision and the resulting state; it never
prints the model message or any secret.

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
from app.session.integration import (
    AccountActionStatusV1Event,
    IntegrationEventService,
)
from app.session.record import (
    AssistanceMode,
    OperationStatus,
    session_record_from_document,
    session_record_to_document,
)
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

PHRASES: tuple[tuple[str, str], ...] = (
    ("A1", "Hazlo t\u00fa por favor"),
    ("A2", "quiero que t\u00fa cambies mi contrase\u00f1a"),
    ("A3", "prefiero que lo hagas t\u00fa"),
    ("A4", "restabl\u00e9cela t\u00fa"),
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


def _seed(store: InMemorySessionDocumentStore) -> None:
    """Exact state observed before the failing turn."""
    record = make_record(
        goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.UNDECIDED),
        identity=make_identity(NOW),
        confirmation=None,
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


def _state(record: Any) -> dict[str, Any]:
    goal = record.goal
    return {
        "goal": goal.action.value if goal is not None else None,
        "revision": goal.revision if goal is not None else None,
        "mode": (
            goal.assistance_mode.value
            if goal is not None and goal.assistance_mode is not None
            else None
        ),
        "challenge": record.confirmation is not None,
        "dispatch_action": record.dispatch.action.value if record.dispatch is not None else None,
    }


def _mode_transition(before: dict[str, Any], after: dict[str, Any]) -> str:
    if before["mode"] is None and after["mode"] is None:
        return "none"
    if before["mode"] is None:
        return "created"
    if after["mode"] is None:
        return "cleared"
    return "retained" if before["mode"] == after["mode"] else "changed"


async def _run_phrase(model: GeminiTurnModel, metrics: TokenMetrics, phrase: str) -> dict[str, Any]:
    store = InMemorySessionDocumentStore()
    _seed(store)
    before = _state(session_record_from_document(store.documents["conversation-1"]))
    prompt_before = metrics.prompt_tokens
    completion_before = metrics.completion_tokens
    service = TurnService(
        SessionRepository(store),
        build_turn_graph(model=model),
        clock=FrozenClock(NOW),
    )
    started = time.monotonic()
    result = await service.handle_turn("conversation-1", TurnInput(transcript=phrase))
    latency = (time.monotonic() - started) * 1000.0
    after = _state(result.record)
    decision = result.decision
    outcome = result.outcome
    return {
        "decision_goal": (
            f"{decision.goal.intent.value}:{decision.goal.action.value}"
            if decision is not None and decision.goal is not None and decision.goal.action
            else (decision.goal.intent.value if decision is not None and decision.goal else None)
        ),
        "decision_mode": (
            decision.assistance_mode.value
            if decision is not None and decision.assistance_mode is not None
            else None
        ),
        "decision_observation": (
            decision.confirmation_observation.value if decision is not None else None
        ),
        "decision_confirmation_request": (
            decision.confirmation_request if decision is not None else None
        ),
        "decision_route": decision.route.value if decision is not None else None,
        "decision_claims": (
            [claim.kind.value for claim in decision.claims] if decision is not None else []
        ),
        "violations": list(outcome.violations) if outcome is not None else [],
        "next_step": outcome.next_step.value if outcome is not None else None,
        "state_before": before,
        "state_after": after,
        "mode_transition": _mode_transition(before, after),
        "prompt_tokens": metrics.prompt_tokens - prompt_before,
        "completion_tokens": metrics.completion_tokens - completion_before,
        "latency_ms": round(latency, 1),
    }


def _unlock_seed(store: InMemorySessionDocumentStore) -> None:
    """State after identity VALID with the specific UNLOCK challenge open."""
    record = make_record(
        goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1),
        identity=make_identity(NOW),
        confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
        dispatch=None,
        external_operation=None,
    )
    store.documents["conversation-1"] = session_record_to_document(record)


async def _run_trajectory(model: GeminiTurnModel, metrics: TokenMetrics) -> dict[str, Any]:
    """F2: UNLOCK (mocked RD) then RESET selection and confirmation."""
    store = InMemorySessionDocumentStore()
    _unlock_seed(store)
    repository = SessionRepository(store)
    service = TurnService(repository, build_turn_graph(model=model), clock=FrozenClock(NOW))
    events = IntegrationEventService(repository, clock=FrozenClock(NOW))
    steps: list[dict[str, Any]] = []

    unlock = await service.handle_turn(
        "conversation-1", TurnInput(transcript="s\u00ed, confirmo el desbloqueo")
    )
    dispatch = unlock.record.dispatch
    assert dispatch is not None
    steps.append(
        {
            "step": "unlock_confirmation",
            "next_step": unlock.outcome.next_step.value if unlock.outcome else None,
            "dispatch_action": dispatch.action.value,
        }
    )

    terminal = await events.handle_event(
        "conversation-1",
        AccountActionStatusV1Event.model_validate(
            {
                "event": "ACCOUNT_ACTION_STATUS",
                "operation_id": dispatch.operation_id,
                "action": "UNLOCK_ACCOUNT",
                "goal_revision": dispatch.goal_revision,
                "status": "SUCESSO",
                "poll_sequence": 1,
            }
        ),
    )
    steps.append(
        {
            "step": "unlock_terminal",
            "next_step": terminal.next_step.value,
            "operation_state": terminal.operation_state.value if terminal.operation_state else None,
            "goal": (session_record_from_document(store.documents["conversation-1"]).goal),
        }
    )

    offer = await service.handle_turn(
        "conversation-1", TurnInput(transcript="quiero cambiar mi contrase\u00f1a")
    )
    steps.append(
        {
            "step": "vague_reset",
            "next_step": offer.outcome.next_step.value if offer.outcome else None,
            "state_after": _state(offer.record),
            "decision_mode": (
                offer.decision.assistance_mode.value
                if offer.decision is not None and offer.decision.assistance_mode is not None
                else None
            ),
        }
    )

    choose = await service.handle_turn(
        "conversation-1", TurnInput(transcript="Hazlo t\u00fa por favor")
    )
    steps.append(
        {
            "step": "choose_autonomous",
            "next_step": choose.outcome.next_step.value if choose.outcome else None,
            "state_after": _state(choose.record),
            "decision_mode": (
                choose.decision.assistance_mode.value
                if choose.decision is not None and choose.decision.assistance_mode is not None
                else None
            ),
            "violations": list(choose.outcome.violations) if choose.outcome else [],
        }
    )

    confirm = await service.handle_turn("conversation-1", TurnInput(transcript="s\u00ed"))
    final_dispatch = confirm.record.dispatch
    decision = confirm.decision
    steps.append(
        {
            "step": "confirm_reset",
            "next_step": confirm.outcome.next_step.value if confirm.outcome else None,
            "decision_mode": (
                decision.assistance_mode.value
                if decision is not None and decision.assistance_mode is not None
                else None
            ),
            "decision_observation": (
                decision.confirmation_observation.value if decision is not None else None
            ),
            "decision_confirmation_request": (
                decision.confirmation_request if decision is not None else None
            ),
            "decision_route": decision.route.value if decision is not None else None,
            "decision_goal": (
                f"{decision.goal.intent.value}:{decision.goal.action.value}"
                if decision is not None and decision.goal is not None and decision.goal.action
                else None
            ),
            "decision_claims": (
                [claim.kind.value for claim in decision.claims] if decision is not None else []
            ),
            "violations": list(confirm.outcome.violations) if confirm.outcome else [],
            "state_after": _state(confirm.record),
            "dispatch_action": final_dispatch.action.value if final_dispatch else None,
            "operation_action": (
                confirm.record.external_operation.action.value
                if confirm.record.external_operation is not None
                else None
            ),
        }
    )

    reset_dispatches = sum(
        1
        for step in steps
        if step.get("step") == "confirm_reset" and step.get("dispatch_action") == "RESET_PASSWORD"
    )
    return {
        "trajectory": steps,
        "reset_dispatches": reset_dispatches,
        "verdict": "PASS" if reset_dispatches == 1 else "FAIL",
        "prompt_tokens": metrics.prompt_tokens,
        "completion_tokens": metrics.completion_tokens,
    }


def _verdict(facts: dict[str, Any]) -> dict[str, bool]:
    """Expected: AUTONOMOUS selected, no affirmation, no violation."""
    return {
        "mode_autonomous": facts["decision_mode"] == "AUTONOMOUS",
        "not_an_affirmation": facts["decision_observation"] in {None, "NONE"},
        "no_violations": not facts["violations"],
        "mode_persisted": facts["state_after"]["mode"] == "AUTONOMOUS",
    }


async def _probe(model: GeminiTurnModel, metrics: TokenMetrics, repetitions: int) -> list[dict]:
    reports: list[dict[str, Any]] = []
    for label, phrase in PHRASES:
        for repetition in range(1, repetitions + 1):
            facts = await _run_phrase(model, metrics, phrase)
            checks = _verdict(facts)
            reports.append(
                {
                    "label": label,
                    "repetition": repetition,
                    "verdict": "PASS" if all(checks.values()) else "FAIL",
                    "checks": checks,
                    **facts,
                }
            )
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description="CU013 reset confirmation probe")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--trajectory", action="store_true")
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
    if args.trajectory:
        report = asyncio.run(_run_trajectory(model, metrics))
        print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
        print(f"trajectory summary: {report['verdict']}")
        return 0 if report["verdict"] == "PASS" else 1
    reports = asyncio.run(_probe(model, metrics, args.repetitions))
    passed = sum(1 for report in reports if report["verdict"] == "PASS")
    print(json.dumps({"reports": reports}, ensure_ascii=False, indent=1))
    print(f"probe summary: {passed}/{len(reports)} PASS")
    return 0 if passed == len(reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
