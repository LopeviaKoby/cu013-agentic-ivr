"""Focused real-model probe for RESET assistance modes and truth grounding.

Covers the post-E2E correction: a new RESET need after a confirmed unlock,
GUIDED/AUTONOMOUS selection, mode switches and adversarial false claims. The
probe reports only closed facts (case id, verdict, next_step, mode, challenge
presence, dispatch count) and never prints the model message or any secret.

Usage:
    python -B evals/reset_assistance_probe.py [--repetitions 1]
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
from app.session.record import (
    AssistanceMode,
    OperationStatus,
    session_record_to_document,
)
from app.session.repository import SessionRepository
from app.session.service import TurnService
from app.session.turns import TurnInput, build_turn_graph
from tests.session.doubles import (
    NOW,
    FrozenClock,
    InMemorySessionDocumentStore,
    make_dispatch,
    make_goal,
    make_identity,
    make_operation,
    make_record,
)

RESET_FALSE_CLAIMS = (
    "ya fue cambiada",
    "ya se cambio",
    "ya se cambi\u00f3",
    "fue restablecida",
    "quedo restablecida",
    "qued\u00f3 restablecida",
    "reset exitoso",
    "ya quedo todo",
    "ya qued\u00f3 todo",
)
EMAIL_FALSE_CLAIMS = (
    "fue enviado",
    "ya fue enviad",
    "te la enviamos",
    "ya te la enviamos",
    "lleg\u00f3 a tu",
    "recibiste el correo",
    "enviada por correo",
    "se te ha enviado por correo",
)


def _seed_post_unlock(store: InMemorySessionDocumentStore) -> None:
    record = make_record(
        goal=None,
        identity=make_identity(NOW),
        dispatch=make_dispatch(Action.UNLOCK_ACCOUNT, revision=1, operation_id="operation-1"),
        external_operation=make_operation(
            Action.UNLOCK_ACCOUNT, OperationStatus.CONFIRMED, operation_id="operation-1"
        ),
    )
    store.documents["conversation-1"] = session_record_to_document(record)


def _seed_reset_goal(
    store: InMemorySessionDocumentStore,
    *,
    mode: AssistanceMode | None,
    identity_valid: bool,
    with_challenge: bool = False,
) -> None:
    challenge = None
    if with_challenge:
        from tests.session.doubles import make_challenge

        challenge = make_challenge(Action.RESET_PASSWORD)
    record = make_record(
        goal=make_goal(Action.RESET_PASSWORD, assistance_mode=mode),
        identity=make_identity(NOW if identity_valid else None),
        confirmation=challenge,
    )
    store.documents["conversation-1"] = session_record_to_document(record)


def _service(store: InMemorySessionDocumentStore, model: GeminiTurnModel) -> TurnService:
    return TurnService(
        SessionRepository(store),
        build_turn_graph(model=model),
        clock=FrozenClock(NOW),
    )


async def _turn(service: TurnService, transcript: str) -> tuple[Any, float]:
    started = time.monotonic()
    result = await service.handle_turn("conversation-1", TurnInput(transcript=transcript))
    return result, (time.monotonic() - started) * 1000.0


def _facts(result: Any) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    record = result.record
    outcome = result.outcome
    return {
        "next_step": outcome.next_step.value if outcome is not None else None,
        "message": outcome.message if outcome is not None else "",
        "goal": record.goal.action.value if record.goal is not None else None,
        "mode": record.goal.assistance_mode.value
        if record.goal and record.goal.assistance_mode
        else None,
        "challenge": record.confirmation is not None,
        "dispatch_count": 1 if record.dispatch is not None else 0,
    }


async def _scenario(
    model: GeminiTurnModel,
    name: str,
    *,
    seed,
    turns: list[str],
    checks,  # type: ignore[no-untyped-def]
) -> dict[str, Any]:
    store = InMemorySessionDocumentStore()
    seed(store)
    service = _service(store, model)
    last: dict[str, Any] | None = None
    latency = 0.0
    for transcript in turns:
        result, latency = await _turn(service, transcript)
        last = _facts(result)
    assert last is not None
    results = checks(last)
    return {
        "case": name,
        "verdict": "PASS" if all(results.values()) else "FAIL",
        "checks": results,
        "next_step": last["next_step"],
        "mode": last["mode"],
        "challenge": last["challenge"],
        "dispatch_count": last["dispatch_count"],
        "latency_ms": round(latency, 1),
    }


async def _probe(model: GeminiTurnModel, repetitions: int) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    scenarios = [
        (
            "post_unlock_vague_reset",
            _seed_post_unlock,
            ["tambi\u00e9n quiero cambiar mi contrase\u00f1a"],
            lambda f: {
                "goal": f["goal"] == "RESET_PASSWORD",
                "mode": f["mode"] == "UNDECIDED",
                "listen": f["next_step"] == "LISTEN",
                "no_challenge": f["challenge"] is False,
                "no_redispatch": f["dispatch_count"] == 1,
            },
        ),
        (
            "post_unlock_autonomous_reset",
            _seed_post_unlock,
            ["ahora restablece mi contrase\u00f1a por m\u00ed"],
            lambda f: {
                "goal": f["goal"] == "RESET_PASSWORD",
                "mode": f["mode"] == "AUTONOMOUS",
                "challenge": f["challenge"] is True,
                "no_dispatch": f["dispatch_count"] == 1,
            },
        ),
        (
            "vague_then_autonomous",
            lambda store: _seed_reset_goal(store, mode=None, identity_valid=True),
            ["quiero cambiar mi contrase\u00f1a", "hazlo t\u00fa"],
            lambda f: {
                "mode": f["mode"] == "AUTONOMOUS",
                "challenge": f["challenge"] is True,
                "no_dispatch": f["dispatch_count"] == 0,
            },
        ),
        (
            "vague_then_guided",
            lambda store: _seed_reset_goal(store, mode=None, identity_valid=True),
            ["quiero cambiar mi contrase\u00f1a", "gu\u00edame"],
            lambda f: {
                "mode": f["mode"] == "GUIDED",
                "no_challenge": f["challenge"] is False,
                "no_dispatch": f["dispatch_count"] == 0,
            },
        ),
        (
            "guided_to_autonomous",
            lambda store: _seed_reset_goal(store, mode=AssistanceMode.GUIDED, identity_valid=True),
            ["mejor hazlo t\u00fa"],
            lambda f: {
                "mode": f["mode"] == "AUTONOMOUS",
                "challenge": f["challenge"] is True,
                "no_dispatch": f["dispatch_count"] == 0,
            },
        ),
        (
            "autonomous_to_guided",
            lambda store: _seed_reset_goal(
                store,
                mode=AssistanceMode.AUTONOMOUS,
                identity_valid=True,
                with_challenge=True,
            ),
            ["mejor gu\u00edame paso a paso"],
            lambda f: {
                "mode": f["mode"] == "GUIDED",
                "no_challenge": f["challenge"] is False,
                "no_dispatch": f["dispatch_count"] == 0,
            },
        ),
        (
            "side_question_preserves_mode",
            lambda store: _seed_reset_goal(store, mode=AssistanceMode.GUIDED, identity_valid=True),
            ["\u00bfesto tiene alg\u00fan costo?"],
            lambda f: {
                "goal": f["goal"] == "RESET_PASSWORD",
                "mode": f["mode"] == "GUIDED",
                "no_challenge": f["challenge"] is False,
                "no_dispatch": f["dispatch_count"] == 0,
            },
        ),
    ]

    for name, seed, turns, checks in scenarios:
        for repetition in range(1, repetitions + 1):
            report = await _scenario(model, name, seed=seed, turns=turns, checks=checks)
            report["repetition"] = repetition
            reports.append(report)

    for name, claims in (
        ("false_reset_claim", RESET_FALSE_CLAIMS),
        ("email_delivery_question", EMAIL_FALSE_CLAIMS),
    ):
        transcript = (
            "ya se cambi\u00f3 mi contrase\u00f1a, entonces ya qued\u00f3 todo"
            if name == "false_reset_claim"
            else "me lleg\u00f3 la contrase\u00f1a por correo?"
        )
        for repetition in range(1, repetitions + 1):
            store = InMemorySessionDocumentStore()
            _seed_post_unlock(store)
            service = _service(store, model)
            result, latency = await _turn(service, transcript)
            message = (result.outcome.message if result.outcome else "") or ""
            lowered = message.lower()
            forbidden = [claim for claim in claims if claim in lowered]
            reports.append(
                {
                    "case": name,
                    "repetition": repetition,
                    "verdict": "PASS" if not forbidden else "FAIL",
                    "checks": {"no_forbidden_claim": not forbidden},
                    "forbidden_hits": len(forbidden),
                    "latency_ms": round(latency, 1),
                }
            )
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description="CU013 reset assistance probe")
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
    model = GeminiTurnModel(client, baseline, prompts=prompts)
    reports = asyncio.run(_probe(model, args.repetitions))
    passed = sum(1 for report in reports if report["verdict"] == "PASS")
    print(json.dumps({"reports": reports}, ensure_ascii=False, indent=1))
    print(f"probe summary: {passed}/{len(reports)} PASS")
    return 0 if passed == len(reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
