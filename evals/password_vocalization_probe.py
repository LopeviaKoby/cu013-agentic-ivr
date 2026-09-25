"""Focused real-model probe for the ephemeral voice password presentation.

The synthetic passwords are generated at runtime from a per-profile seed and
are never written to a fixture, artifact or log. The probe reports only closed,
non-sensitive facts: case id, verdict, next_step, presentation state, delivery
match class, dispatch count, latency and tokens. It never prints the secret or
the spoken message.

Usage:
    python -B evals/password_vocalization_probe.py [--profile mixed] [--repetitions 1]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import string
import sys
import time
from datetime import UTC, datetime
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
    OperationStatus,
    PasswordPresentation,
    PlaybackVoice,
    session_record_to_document,
)
from app.session.repository import SessionRepository
from app.session.service import TurnService
from app.session.turns import (
    TurnInput,
    build_turn_graph,
)
from evals.password_oracle import decode_match, match_count
from tests.session.doubles import (
    FrozenClock,
    InMemorySessionDocumentStore,
    make_dispatch,
    make_identity,
    make_operation,
    make_record,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)

_SYMBOLS = "!@#$%?"
_ALNUM = string.ascii_letters + string.digits

PROFILES: tuple[str, ...] = (
    "upper",
    "lower",
    "digits",
    "symbols",
    "repeated",
    "mixed",
    "symbol_start",
    "symbol_end",
)


def synthetic_password(profile: str) -> str:
    """Deterministic synthetic secret generated at runtime from a profile.

    No credential literal exists anywhere: each profile is a generation rule
    over the standard character classes and the closed synthetic symbol set.
    """
    rng = random.Random(f"cu013-password-{profile}")
    if profile == "upper":
        return "".join(rng.choice(string.ascii_uppercase) for _ in range(8))
    if profile == "lower":
        return "".join(rng.choice(string.ascii_lowercase) for _ in range(8))
    if profile == "digits":
        return "".join(rng.choice(string.digits) for _ in range(6))
    if profile == "symbols":
        return "".join(rng.choice(_SYMBOLS) for _ in range(6))
    if profile == "repeated":
        letter = rng.choice(string.ascii_uppercase)
        digit = rng.choice(string.digits)
        return (letter + digit) * 4
    if profile == "symbol_start":
        return rng.choice(_SYMBOLS) + "".join(rng.choice(_ALNUM) for _ in range(4))
    if profile == "symbol_end":
        return "".join(rng.choice(_ALNUM) for _ in range(4)) + rng.choice(_SYMBOLS)
    return "".join(rng.choice(_ALNUM + _SYMBOLS) for _ in range(10))


def _seed(store: InMemorySessionDocumentStore, *, plane: bool) -> None:
    presentation = (
        PasswordPresentation(
            operation_id="operation-1",
            action=Action.RESET_PASSWORD,
            goal_revision=1,
            voice=PlaybackVoice.PLAYBACK_RETURNED,
            caller_finished=False,
            presented_at=NOW,
        )
        if plane
        else None
    )
    record = make_record(
        goal=None,
        identity=make_identity(NOW),
        dispatch=make_dispatch(Action.RESET_PASSWORD, revision=1, operation_id="operation-1"),
        external_operation=make_operation(
            Action.RESET_PASSWORD, OperationStatus.CONFIRMED, operation_id="operation-1"
        ),
        password_presentation=presentation,
    )
    store.documents["conversation-1"] = session_record_to_document(record)


def _suffix_from_anchor(secret: str, anchor_index: int) -> str:
    return secret[anchor_index:]


async def _run_case(
    service: TurnService,
    store: InMemorySessionDocumentStore,
    *,
    transcript: str | None,
    secret: str | None,
) -> dict[str, Any]:
    started = time.monotonic()
    result = await service.handle_turn(
        "conversation-1",
        TurnInput(
            transcript=transcript,
            temporary_password=secret,
        ),
    )
    latency = (time.monotonic() - started) * 1000.0
    outcome = result.outcome
    record = result.record
    assert outcome is not None
    presentation = record.password_presentation
    dispatch_count = 1 if record.dispatch is not None else 0
    return {
        "next_step": outcome.next_step.value,
        "presentation_finished": bool(presentation.caller_finished) if presentation else False,
        "presentation_present": presentation is not None,
        "goal": record.goal.action.value if record.goal is not None else None,
        "dispatch_count": dispatch_count,
        "operation_status": (
            record.external_operation.status.value if record.external_operation else None
        ),
        "latency_ms": round(latency, 1),
        "_message": outcome.message,
    }


def _verdicts(case: dict[str, Any], secret: str) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    checks["next_step"] = case["next_step"] == case["expect_next_step"]
    if case.get("expect_delivery") is not None:
        checks["delivery"] = case["delivery"] == case["expect_delivery"]
    if case.get("expect_finished") is not None:
        checks["finished"] = case["presentation_finished"] is case["expect_finished"]
    if case.get("expect_goal") is not None:
        checks["goal"] = case["goal"] == case["expect_goal"]
    checks["no_redispatch"] = case["dispatch_count"] == 1
    return {
        "case": case["case"],
        "verdict": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "next_step": case["next_step"],
        "presentation_finished": case["presentation_finished"],
        "delivery": case.get("delivery"),
        "goal": case["goal"],
        "latency_ms": case["latency_ms"],
    }


async def _probe(model: GeminiTurnModel, profile: str, repetitions: int) -> list[dict[str, Any]]:
    secret = synthetic_password(profile)
    anchor_index = max(1, len(secret) // 2)
    suffix = _suffix_from_anchor(secret, anchor_index)
    anchor_name = secret[anchor_index]
    reports: list[dict[str, Any]] = []

    scenarios: list[dict[str, Any]] = [
        {
            "case": "initial_dictation",
            "plane": False,
            "transcript": None,
            "send_secret": True,
            "expect_next_step": "DELIVER_PASSWORD",
            "expect_delivery": "full",
        },
        {
            "case": "repeat_whole",
            "plane": True,
            "transcript": "repítela completa, por favor",
            "send_secret": True,
            "expect_next_step": "DELIVER_PASSWORD",
            "expect_delivery": "full",
        },
        {
            "case": "repeat_from_anchor",
            "plane": True,
            "transcript": f"repítela desde {anchor_name}",
            "send_secret": True,
            "expect_next_step": "DELIVER_PASSWORD",
            "expect_suffix": suffix,
        },
        {
            "case": "continue_after_prefix",
            "plane": True,
            "transcript": f"llevo {secret[:anchor_index]}, ¿qué sigue?",
            "send_secret": True,
            "expect_next_step": "DELIVER_PASSWORD",
            "expect_suffix": suffix,
        },
        {
            "case": "uppercase_clarification",
            "plane": True,
            "transcript": f"¿la {secret[0]} era mayúscula?",
            "send_secret": True,
            "expect_next_step": "DELIVER_PASSWORD",
            "expect_char": secret[0],
        },
        {
            "case": "symbol_clarification",
            "plane": True,
            "transcript": "¿qué símbolo va después de los números?",
            "send_secret": True,
            "expect_next_step": "DELIVER_PASSWORD",
        },
        {
            "case": "multiple_repeats",
            "plane": True,
            "transcript": "otra vez, y luego otra vez si hace falta",
            "send_secret": True,
            "expect_next_step": "DELIVER_PASSWORD",
            "expect_delivery": "full",
        },
        {
            "case": "caller_finished",
            "plane": True,
            "transcript": "ya está, la anoté completa",
            "send_secret": True,
            "expect_next_step": "LISTEN",
            "expect_finished": True,
        },
        {
            "case": "side_question_during_presentation",
            "plane": True,
            "transcript": "¿esta contraseña es segura?",
            "send_secret": True,
            "expect_next_step": "DELIVER_PASSWORD",
        },
        {
            "case": "password_absent_during_presentation",
            "plane": True,
            "transcript": "repítela otra vez",
            "send_secret": False,
            "expect_next_step": "LISTEN",
            "expect_finished": False,
        },
    ]

    for scenario in scenarios:
        for repetition in range(1, repetitions + 1):
            store = InMemorySessionDocumentStore()
            _seed(store, plane=bool(scenario["plane"]))
            service = TurnService(
                SessionRepository(store),
                build_turn_graph(model=model),
                clock=FrozenClock(NOW),
            )
            sent_secret = secret if scenario["send_secret"] else None
            case = await _run_case(
                service,
                store,
                transcript=scenario["transcript"],
                secret=sent_secret,
            )
            message = case.pop("_message")
            delivery = None
            if sent_secret is not None:
                delivery = decode_match(secret, message)
            case["delivery"] = delivery
            if "expect_suffix" in scenario:
                case["expect_next_step"] = scenario["expect_next_step"]
                case["expect_delivery"] = None
                suffix_ok = match_count(scenario["expect_suffix"], message) >= len(
                    scenario["expect_suffix"]
                )
                checks = {
                    "next_step": case["next_step"] == scenario["expect_next_step"],
                    "suffix": suffix_ok,
                    "no_redispatch": case["dispatch_count"] == 1,
                }
                report = {
                    "case": scenario["case"],
                    "repetition": repetition,
                    "verdict": "PASS" if all(checks.values()) else "FAIL",
                    "checks": checks,
                    "next_step": case["next_step"],
                    "latency_ms": case["latency_ms"],
                }
            elif "expect_char" in scenario:
                case["expect_next_step"] = scenario["expect_next_step"]
                case["expect_delivery"] = None
                char_ok = match_count(scenario["expect_char"], message) >= 1
                checks = {
                    "next_step": case["next_step"] == scenario["expect_next_step"],
                    "clarified_char": char_ok,
                    "no_redispatch": case["dispatch_count"] == 1,
                }
                report = {
                    "case": scenario["case"],
                    "repetition": repetition,
                    "verdict": "PASS" if all(checks.values()) else "FAIL",
                    "checks": checks,
                    "next_step": case["next_step"],
                    "latency_ms": case["latency_ms"],
                }
            else:
                case["case"] = scenario["case"]
                case["expect_next_step"] = scenario["expect_next_step"]
                case["expect_delivery"] = scenario.get("expect_delivery")
                case["expect_finished"] = scenario.get("expect_finished")
                report = _verdicts(case, secret)
                report["repetition"] = repetition
            reports.append(report)
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description="CU013 password vocalization probe")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="mixed")
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
    reports = asyncio.run(_probe(model, args.profile, args.repetitions))
    passed = sum(1 for report in reports if report["verdict"] == "PASS")
    print(json.dumps({"profile": args.profile, "reports": reports}, ensure_ascii=False, indent=1))
    print(f"probe summary: {passed}/{len(reports)} PASS")
    return 0 if passed == len(reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
