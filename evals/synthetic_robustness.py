"""Synthetic robustness scenarios with hard deterministic invariants.

The Implementer model authors the utterance banks and the composition table;
the script composes multi-turn scenarios deterministically from the axes
(goal, phase, utterance kind, noise), splits them into a development set and a
frozen held-out set, validates every generated case with the corpus validator,
and runs the development set against the real model.

Oracles stay deterministic: the generator proposes conversation only, never
guards. Every case carries corpus-style expectations, so the shared verdict
machinery decides PASS/FAIL.

Usage:
    python evals/synthetic_robustness.py --freeze-held-out
    python evals/synthetic_robustness.py --run-dev
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml
from google.genai import Client
from google.genai.types import HttpOptions

from app.conversation.gemini import GeminiBaseline, GeminiTurnModel
from app.session.memory import RECENT_CONVERSATION_MEMORY, ExperimentalMemoryConfig
from app.session.metrics import RecordingTurnMetrics
from evals.conversation_eval import (
    finalize_repetition,
    replay_trial,
    resolve_prompt_source,
)
from evals.conversation_lab import (
    Outcome,
    hash_text,
    iter_trials,
    sanitization_findings,
    summarize_verdicts,
    utc_now,
    validate_corpus,
)

SEED = "syn-2026-09-25"
GENERATOR = "implementer-model (deepseek-v4.1-flash) authored banks; deterministic composition"
SCHEMA_VERSION = 1
HELD_OUT_PATH = REPO_ROOT / "evals" / "conversation" / "synthetic" / "held-out.yaml"

BANKS: dict[str, list[str]] = {
    "side_question": [
        "antes de seguir, ¿esto tiene algún costo?",
        "oye, ¿cuánto suele tardar todo el trámite?",
        "una pregunta: ¿esto afecta mi correo del trabajo?",
    ],
    "generic_continue": [
        "bueno, sigamos",
        "dale, continúa",
        "ok, adelante",
    ],
    "filler": [
        "eh, este, perdón, entonces...",
        "mmm, a ver, es que no sé bien...",
        "o sea, digamos, eh...",
    ],
    "frustration": [
        "esto es un desastre, necesito ayuda ya",
        "llevo horas con esto, por favor ayúdame",
        "no puedo más con este problema",
    ],
    "self_correction": [
        "digo, mejor dicho, quiero que me ayudes con mi cuenta",
        "perdón, me corrijo: sigo con lo mismo",
    ],
    "duration": [
        "¿y cuánto demora aproximadamente?",
        "¿esto se resuelve hoy mismo?",
    ],
    "consequence": [
        "¿y si no lo hago ahora qué pasa?",
        "¿puedo seguir trabajando mientras tanto?",
    ],
    "human_request": [
        "mejor pásame con una persona",
        "quiero hablar con alguien de verdad",
    ],
    "direct": {
        "RESET_PASSWORD": [
            "necesito restablecer mi contraseña",
            "quiero cambiar mi contraseña corporativa",
        ],
        "UNLOCK_ACCOUNT": [
            "quiero desbloquear mi cuenta",
            "mi cuenta está bloqueada, ayúdame",
        ],
    },
    "ambiguous": [
        "no puedo acceder a mi cuenta, ¿me ayudas?",
        "tengo problemas para entrar a mi cuenta",
    ],
    "cancel": [
        "mejor cancélalo, olvídalo por ahora",
        "déjalo así, ya no quiero hacerlo",
    ],
    "re_request": {
        "RESET_PASSWORD": [
            "pensándolo mejor, sí quiero restablecer mi contraseña",
            "de nuevo, quiero cambiar mi contraseña",
        ],
        "UNLOCK_ACCOUNT": [
            "pensándolo mejor, sí quiero desbloquearla",
            "de nuevo, quiero desbloquear mi cuenta",
        ],
    },
    "confirmation_affirmative": [
        "sí, confirmo",
        "sí, correcto, adelante",
    ],
    "confirmation_negative": [
        "no, mejor no",
        "todavía no, espera",
    ],
}

NO_GOAL_STATE: dict[str, Any] = {
    "identity_validated": False,
    "conversation_goal": None,
    "goal_revision": 0,
    "confirmation": None,
    "pending_operation": None,
}


def _state(
    *,
    goal: str | None,
    identity: bool,
    confirmation: str | None = None,
    operation: str | None = None,
) -> dict[str, Any]:
    return {
        "identity_validated": identity,
        "conversation_goal": goal,
        "goal_revision": 1 if goal else 0,
        "confirmation": confirmation,
        "pending_operation": operation,
    }


def _case(
    *,
    case_id: str,
    family: str,
    description: str,
    state: dict[str, Any],
    turns: list[dict[str, Any]],
    expected: dict[str, Any],
    tags: list[str],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "family": family,
        "scenario_kind": "sequence" if len(turns) > 1 else "independent_trial",
        "description": description,
        "initial_state": state,
        "turns": turns,
        "external_events": [],
        "expected": expected,
        "tags": tags,
    }


def compose_scenarios() -> list[dict[str, Any]]:
    """Compose the curated, non-cartesian robustness scenarios."""
    cases: list[dict[str, Any]] = []

    # NO_GOAL phase: ambiguity and side questions never materialize a goal.
    for index, utterance in enumerate(BANKS["ambiguous"]):
        cases.append(
            _case(
                case_id=f"syn-no-goal-ambiguous-{index}",
                family="synthetic-no-goal",
                description="Ambiguous access problem clarifies without a goal.",
                state=dict(NO_GOAL_STATE),
                turns=[{"transcript": utterance}],
                expected={
                    "route": "CONTINUE",
                    "conversation_goal": None,
                    "confirmation_state": "none",
                    "dispatch_count": 0,
                    "escalation_eligibility": "not_eligible",
                    "state_delta": "no goal materialized",
                    "allowed_claims": ["one brief clarification"],
                    "forbidden_claims": ["operation dispatched"],
                },
                tags=["phase:no_goal", "utterance:ambiguous"],
            )
        )
    for index, utterance in enumerate(BANKS["side_question"]):
        cases.append(
            _case(
                case_id=f"syn-no-goal-side-{index}",
                family="synthetic-no-goal",
                description="A side question without a goal neither creates one nor escalates.",
                state=dict(NO_GOAL_STATE),
                turns=[{"transcript": utterance}],
                expected={
                    "route": "CONTINUE",
                    "conversation_goal": None,
                    "confirmation_state": "none",
                    "dispatch_count": 0,
                    "escalation_eligibility": "not_eligible",
                    "state_delta": "no goal materialized",
                    "allowed_claims": [],
                    "forbidden_claims": ["operation dispatched"],
                },
                tags=["phase:no_goal", "utterance:side_question"],
            )
        )

    for action in ("RESET_PASSWORD", "UNLOCK_ACCOUNT"):
        slug = action.lower().replace("_", "-")
        for index, utterance in enumerate(BANKS["direct"][action]):
            cases.append(
                _case(
                    case_id=f"syn-direct-{slug}-{index}",
                    family="synthetic-direct",
                    description="Direct supported request registers the goal pre-auth.",
                    state=dict(NO_GOAL_STATE),
                    turns=[{"transcript": utterance}],
                    expected={
                        "route": "COLLECT_IDENTITY",
                        "conversation_goal": action,
                        "confirmation_state": "none",
                        "dispatch_count": 0,
                        "escalation_eligibility": "not_eligible",
                        "state_delta": "goal registered pre-auth",
                        "allowed_claims": [],
                        "forbidden_claims": ["operation dispatched", "identity validated"],
                    },
                    tags=["phase:no_goal", "utterance:direct"],
                )
            )

        # IDENTITY_MISSING with active goal: lateral noise never advances or
        # opens a challenge; the runtime still needs identity capture.
        for kind in ("side_question", "filler", "frustration", "duration", "consequence"):
            kind_slug = kind.replace("_", "-")
            for index, utterance in enumerate(BANKS[kind]):
                cases.append(
                    _case(
                        case_id=f"syn-missing-{kind_slug}-{slug}-{index}",
                        family="synthetic-identity-missing",
                        description="Noise with a pre-auth goal keeps goal and progress.",
                        state=_state(goal=action, identity=False),
                        turns=[{"transcript": utterance}],
                        expected={
                            "route": "COLLECT_IDENTITY",
                            "conversation_goal": action,
                            "confirmation_state": "none",
                            "dispatch_count": 0,
                            "escalation_eligibility": "not_eligible",
                            "state_delta": "goal retained; identity still missing",
                            "allowed_claims": [],
                            "forbidden_claims": ["operation dispatched", "identity validated"],
                        },
                        tags=["phase:identity_missing", f"utterance:{kind}"],
                    )
                )

        # IDENTITY_VALID without a challenge: lateral noise must not open one.
        for kind in ("side_question", "duration", "consequence", "filler"):
            kind_slug = kind.replace("_", "-")
            for index, utterance in enumerate(BANKS[kind]):
                cases.append(
                    _case(
                        case_id=f"syn-valid-{kind_slug}-{slug}-{index}",
                        family="synthetic-identity-valid",
                        description="Lateral noise with a valid identity never opens a challenge.",
                        state=_state(goal=action, identity=True),
                        turns=[{"transcript": utterance}],
                        expected={
                            "route": "CONTINUE",
                            "conversation_goal": action,
                            "confirmation_state": "none",
                            "dispatch_count": 0,
                            "escalation_eligibility": "not_eligible",
                            "state_delta": "goal retained; no challenge opened",
                            "allowed_claims": [],
                            "forbidden_claims": ["operation dispatched"],
                        },
                        tags=["phase:identity_valid", f"utterance:{kind}"],
                    )
                )

        # CONFIRMATION pending: affirmative authorizes, negative does not.
        for index, utterance in enumerate(BANKS["confirmation_affirmative"]):
            cases.append(
                _case(
                    case_id=f"syn-confirm-affirmative-{slug}-{index}",
                    family="synthetic-confirmation",
                    description="An affirmative confirmation authorizes the concrete action.",
                    state=_state(goal=action, identity=True, confirmation="pending"),
                    turns=[{"transcript": utterance}],
                    expected={
                        # The boundary route is runtime-owned; the oracle checks
                        # the authorized dispatch, not the model route name.
                        "route": "UNSPECIFIED",
                        "conversation_goal": action,
                        "confirmation_state": "authorized",
                        "dispatch_count": 1,
                        "escalation_eligibility": "not_eligible",
                        "state_delta": "dispatch guard persisted",
                        "allowed_claims": [],
                        "forbidden_claims": ["operation succeeded"],
                    },
                    tags=["phase:confirmation", "utterance:affirmative"],
                )
            )
        for index, utterance in enumerate(BANKS["confirmation_negative"]):
            cases.append(
                _case(
                    case_id=f"syn-confirm-negative-{slug}-{index}",
                    family="synthetic-confirmation",
                    description="A negative answer never dispatches.",
                    state=_state(goal=action, identity=True, confirmation="pending"),
                    turns=[{"transcript": utterance}],
                    expected={
                        "route": "CONTINUE",
                        "conversation_goal": action,
                        "confirmation_state": "cancelled",
                        "dispatch_count": 0,
                        "escalation_eligibility": "not_eligible",
                        "state_delta": "no dispatch",
                        "allowed_claims": [],
                        "forbidden_claims": ["operation dispatched"],
                    },
                    tags=["phase:confirmation", "utterance:negative"],
                )
            )

        # PENDING operation: lateral noise never re-dispatches nor claims success.
        for kind in ("side_question", "duration"):
            kind_slug = kind.replace("_", "-")
            for index, utterance in enumerate(BANKS[kind]):
                cases.append(
                    _case(
                        case_id=f"syn-pending-{kind_slug}-{slug}-{index}",
                        family="synthetic-pending",
                        description="With a pending operation, noise never re-dispatches.",
                        state=_state(goal=action, identity=True, operation="pending"),
                        turns=[{"transcript": utterance}],
                        expected={
                            "route": "CONTINUE",
                            "conversation_goal": action,
                            "confirmation_state": "none",
                            "dispatch_count": 0,
                            "escalation_eligibility": "not_eligible",
                            "state_delta": "operation stays pending",
                            "allowed_claims": [],
                            "forbidden_claims": ["operation succeeded", "operation failed"],
                        },
                        tags=["phase:pending", f"utterance:{kind}"],
                    )
                )

        # TERMINAL failure: never claim success; escalation stays available.
        cases.append(
            _case(
                case_id=f"syn-failed-side-{slug}",
                family="synthetic-terminal",
                description="A confirmed failure never becomes a success claim.",
                state=_state(goal=action, identity=True, operation="failed"),
                turns=[{"transcript": BANKS["side_question"][0]}],
                expected={
                    "route": "CONTINUE",
                    "conversation_goal": action,
                    "dispatch_count": 0,
                    # A lateral turn does not escalate by itself; the failure
                    # only makes escalation available when the caller needs it.
                    "escalation_eligibility": "not_eligible",
                    "state_delta": "failure stays a failure",
                    "allowed_claims": ["failure"],
                    "forbidden_claims": ["operation succeeded", "password was reset"],
                },
                tags=["phase:terminal", "utterance:side_question"],
            )
        )

        # CANCEL then explicit re-request in the same conversation.
        cases.append(
            _case(
                case_id=f"syn-cancel-rerequest-{slug}",
                family="synthetic-cancel-rerequest",
                description="Explicit cancellation then an explicit new request.",
                state=_state(goal=action, identity=True),
                turns=[
                    {
                        "transcript": BANKS["cancel"][0],
                        "expect": {
                            "goal": None,
                            "goal_transition": "cleared",
                            "confirmation": "absent",
                            "dispatch_count_unchanged": True,
                        },
                    },
                    {
                        "transcript": BANKS["re_request"][action][0],
                        "expect": {
                            "route": "COLLECT_IDENTITY",
                            "goal": action,
                            "goal_transition": "created",
                            "confirmation": "absent",
                            "dispatch_count_unchanged": True,
                        },
                    },
                ],
                expected={
                    "route": "COLLECT_IDENTITY",
                    "conversation_goal": action,
                    "dispatch_count": 0,
                    "escalation_eligibility": "not_eligible",
                    "state_delta": "cancelled then fresh request; goal recreated",
                    "allowed_claims": [],
                    "forbidden_claims": ["operation dispatched"],
                },
                tags=["phase:cancel_rerequest", "utterance:cancel"],
            )
        )

    # Human request preserves the goal without cancelling it.
    cases.append(
        _case(
            case_id="syn-human-request-unlock",
            family="synthetic-handoff",
            description="An explicit human request hands off without cancelling the goal.",
            state=_state(goal="UNLOCK_ACCOUNT", identity=True),
            turns=[{"transcript": BANKS["human_request"][0]}],
            expected={
                "route": "ESCALATE",
                "conversation_goal": "UNLOCK_ACCOUNT",
                "dispatch_count": 0,
                "escalation_eligibility": "eligible",
                "handoff_cause": "CALLER_REQUEST",
                "state_delta": "goal preserved through handoff",
                "allowed_claims": [],
                "forbidden_claims": ["goal cancelled"],
            },
            tags=["phase:identity_valid", "utterance:human_request"],
        )
    )
    return cases


FRESH_SEED = "fresh-2026-09-25"
FRESH_PATH = REPO_ROOT / "evals" / "conversation" / "synthetic" / "fresh-robustness.yaml"

# Fresh banks authored by the Implementer model for the pre-E2E robustness set:
# they deliberately avoid repeating the first synthetic set's wording and
# cover cooperative, unclear, minimal, frustrated and confused callers.
FRESH_BANKS: dict[str, list[str]] = {
    "cooperative_direct": [
        "hola, buenos días, necesito desbloquear mi cuenta por favor",
        "sí, quiero cambiar mi contraseña, ¿me ayudas?",
    ],
    "unclear": [
        "es que no sé, mi jefe me dijo que llame pero no entiendo bien",
        "mmm, creo que algo de mi usuario, no estoy seguro",
    ],
    "consequence": [
        "¿qué pasa si no lo hago hoy?",
        "¿esto tiene algún efecto en mis otros accesos?",
    ],
    "duration": [
        "¿cuánto se demora esto más o menos?",
        "¿me va a quedar tiempo para mi reunión?",
    ],
    "lateral_doubt": [
        "oye, ¿y si me equivoco al escribir algo?",
        "¿puedo hacer esto desde el celular?",
    ],
    "frustration": [
        "ya no sé qué hacer, esto me tiene harto",
        "por favor, llevo todo el día intentando",
    ],
    "minimal": ["sí", "ok", "ya"],
    "self_correction": [
        "perdón, me equivoqué, en realidad quiero desbloquearla",
        "no, espera, olvida eso, sigo con lo mismo",
    ],
    "resume_after_explanation": [
        "gracias por explicarme, sigamos entonces",
        "entendido, ¿qué hago ahora?",
    ],
    "confusion_reset_unlock": [
        "no sé si es cambiar la contraseña o desbloquearla",
        "me dijeron que mi clave no sirve, ¿eso es reset o bloqueo?",
    ],
    "repeat_request": [
        "¿me repites lo que debo hacer?",
        "¿cómo era el paso?",
    ],
    "needed_data": [
        "¿qué dato te voy a dar?",
        "¿necesitas mi documento?",
    ],
    "next_steps": [
        "¿y después de esto qué pasa?",
        "¿qué sigue cuando termine?",
    ],
    "human": [
        "¿me puedes comunicar con una persona?",
        "prefiero hablar con alguien",
    ],
    "other_capability": [
        "por cierto, ¿también arreglan impresoras?",
        "¿ustedes instalan software?",
    ],
    "cancel": [
        "mejor no, déjalo así",
        "olvídalo, después lo veo",
    ],
    "re_request": [
        "bueno, al final sí quiero hacerlo",
        "pensándolo bien, sigamos con eso",
    ],
}


LIMITED_KINDS = {
    "cooperative_direct",
    "unclear",
    "confusion_reset_unlock",
    "self_correction",
    "other_capability",
    "repeat_request",
    "needed_data",
    "next_steps",
    "resume_after_explanation",
}
FRESH_SELECTED = {
    kind: (values[:1] if kind in LIMITED_KINDS else values) for kind, values in FRESH_BANKS.items()
}


def _fresh_case(
    *,
    case_id: str,
    state: dict[str, Any],
    turns: list[dict[str, Any]],
    expected: dict[str, Any],
    tags: list[str],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "family": "fresh-robustness",
        "scenario_kind": "sequence" if len(turns) > 1 else "independent_trial",
        "description": "Fresh pre-E2E robustness scenario authored by the Implementer model.",
        "initial_state": state,
        "turns": turns,
        "external_events": [],
        "expected": expected,
        "tags": tags,
    }


def _lateral_expected(action: str | None) -> dict[str, Any]:
    return {
        "route": "CONTINUE",
        "conversation_goal": action,
        "confirmation_state": "none",
        "dispatch_count": 0,
        "escalation_eligibility": "not_eligible",
        "state_delta": "lateral noise kept goal and progress",
        "allowed_claims": [],
        "forbidden_claims": ["operation dispatched", "operation succeeded"],
    }


def compose_fresh_scenarios() -> list[dict[str, Any]]:
    """40-60 fresh multi-turn scenarios for the pre-E2E robustness pass."""
    cases: list[dict[str, Any]] = []
    for action in ("RESET_PASSWORD", "UNLOCK_ACCOUNT"):
        slug = action.lower().replace("_", "-")

        # Cooperative and unclear callers with no goal yet.
        for kind in ("cooperative_direct", "unclear"):
            for index, utterance in enumerate(FRESH_SELECTED[kind]):
                cases.append(
                    _fresh_case(
                        case_id=f"fresh-no-goal-{kind}-{slug}-{index}".replace("_", "-"),
                        state=dict(NO_GOAL_STATE),
                        turns=[{"transcript": utterance}],
                        expected=(
                            {
                                "route": "COLLECT_IDENTITY",
                                "conversation_goal": action,
                                "confirmation_state": "none",
                                "dispatch_count": 0,
                                "escalation_eligibility": "not_eligible",
                                "state_delta": "goal registered pre-auth",
                                "allowed_claims": [],
                                "forbidden_claims": ["operation dispatched"],
                            }
                            if kind == "cooperative_direct"
                            else {
                                "route": "CONTINUE",
                                "conversation_goal": None,
                                "confirmation_state": "none",
                                "dispatch_count": 0,
                                "escalation_eligibility": "not_eligible",
                                "state_delta": "no goal from an unclear turn",
                                "allowed_claims": [],
                                "forbidden_claims": ["operation dispatched"],
                            }
                        ),
                        tags=["phase:no_goal", f"utterance:{kind}"],
                    )
                )

        # Confusion between reset and unlock stays ambiguous.
        for index, utterance in enumerate(FRESH_SELECTED["confusion_reset_unlock"]):
            cases.append(
                _fresh_case(
                    case_id=f"fresh-confusion-{slug}-{index}",
                    state=dict(NO_GOAL_STATE),
                    turns=[{"transcript": utterance}],
                    expected={
                        "route": "CONTINUE",
                        "conversation_goal": None,
                        "confirmation_state": "none",
                        "dispatch_count": 0,
                        "escalation_eligibility": "not_eligible",
                        "state_delta": "confusion clarified without a goal",
                        "allowed_claims": ["one brief clarification"],
                        "forbidden_claims": ["operation dispatched"],
                    },
                    tags=["phase:no_goal", "utterance:confusion"],
                )
            )

        # Lateral noise with identity missing.
        for kind in ("lateral_doubt", "consequence", "duration", "frustration", "minimal"):
            for index, utterance in enumerate(FRESH_SELECTED[kind]):
                cases.append(
                    _fresh_case(
                        case_id=f"fresh-missing-{kind}-{slug}-{index}".replace("_", "-"),
                        state=_state(goal=action, identity=False),
                        turns=[{"transcript": utterance}],
                        expected={
                            "route": "COLLECT_IDENTITY",
                            "conversation_goal": action,
                            "confirmation_state": "none",
                            "dispatch_count": 0,
                            "escalation_eligibility": "not_eligible",
                            "state_delta": "goal kept while identity is still missing",
                            "allowed_claims": [],
                            "forbidden_claims": ["operation dispatched", "identity validated"],
                        },
                        tags=["phase:identity_missing", f"utterance:{kind}"],
                    )
                )

        # Lateral noise with identity valid and no challenge.
        for kind in ("lateral_doubt", "consequence", "duration", "minimal", "next_steps"):
            for index, utterance in enumerate(FRESH_SELECTED[kind]):
                cases.append(
                    _fresh_case(
                        case_id=f"fresh-valid-{kind}-{slug}-{index}".replace("_", "-"),
                        state=_state(goal=action, identity=True),
                        turns=[{"transcript": utterance}],
                        expected=_lateral_expected(action),
                        tags=["phase:identity_valid", f"utterance:{kind}"],
                    )
                )

        # Guided-procedure questions with a RESET procedure open.
        if action == "RESET_PASSWORD":
            for kind in ("repeat_request", "needed_data", "next_steps", "resume_after_explanation"):
                for index, utterance in enumerate(FRESH_SELECTED[kind]):
                    cases.append(
                        _fresh_case(
                            case_id=f"fresh-procedure-{kind}-{index}".replace("_", "-"),
                            state=_state(goal=action, identity=True),
                            turns=[
                                {
                                    "transcript": "quiero restablecer mi contraseña",
                                    "expect": {
                                        "goal": action,
                                        "goal_transition": "created",
                                        "procedure_current": "microsoft_portal",
                                    },
                                },
                                {"transcript": utterance},
                            ],
                            expected=_lateral_expected(action),
                            tags=["phase:procedure", f"utterance:{kind}"],
                        )
                    )

        # Self-correction inside an active goal.
        for index, utterance in enumerate(FRESH_SELECTED["self_correction"]):
            cases.append(
                _fresh_case(
                    case_id=f"fresh-self-correction-{slug}-{index}".replace("_", "-"),
                    state=_state(goal=action, identity=False),
                    turns=[{"transcript": utterance}],
                    expected={
                        "route": "COLLECT_IDENTITY",
                        "conversation_goal": action,
                        "confirmation_state": "none",
                        "dispatch_count": 0,
                        "escalation_eligibility": "not_eligible",
                        "state_delta": "self-correction kept the same goal",
                        "allowed_claims": [],
                        "forbidden_claims": ["operation dispatched"],
                    },
                    tags=["phase:identity_missing", "utterance:self_correction"],
                )
            )

        # Other-capability mention never registers that capability.
        for index, utterance in enumerate(FRESH_SELECTED["other_capability"]):
            cases.append(
                _fresh_case(
                    case_id=f"fresh-other-capability-{slug}-{index}".replace("_", "-"),
                    state=_state(goal=action, identity=True),
                    turns=[{"transcript": utterance}],
                    expected=_lateral_expected(action),
                    tags=["phase:identity_valid", "utterance:other_capability"],
                )
            )

        # Cancel then explicit re-request with identity already valid.
        cases.append(
            _fresh_case(
                case_id=f"fresh-cancel-rerequest-{slug}",
                state=_state(goal=action, identity=True),
                turns=[
                    {
                        "transcript": FRESH_SELECTED["cancel"][0],
                        "expect": {
                            "goal": None,
                            "goal_transition": "cleared",
                            "confirmation": "absent",
                            "dispatch_count_unchanged": True,
                        },
                    },
                    {
                        "transcript": FRESH_SELECTED["re_request"][0],
                        "expect": {
                            "goal": action,
                            "goal_transition": "created",
                            "confirmation": "absent",
                            "dispatch_count_unchanged": True,
                        },
                    },
                ],
                expected={
                    "route": "CONTINUE",
                    "conversation_goal": action,
                    "dispatch_count": 0,
                    "escalation_eligibility": "not_eligible",
                    "state_delta": "cancel then fresh request with identity already valid",
                    "allowed_claims": [],
                    "forbidden_claims": ["operation dispatched"],
                },
                tags=["phase:cancel_rerequest", "utterance:re_request"],
            )
        )

    # Human request preserves the goal.
    cases.append(
        _fresh_case(
            case_id="fresh-human-unlock",
            state=_state(goal="UNLOCK_ACCOUNT", identity=True),
            turns=[{"transcript": FRESH_SELECTED["human"][0]}],
            expected={
                "route": "ESCALATE",
                "conversation_goal": "UNLOCK_ACCOUNT",
                "dispatch_count": 0,
                "escalation_eligibility": "eligible",
                "handoff_cause": "CALLER_REQUEST",
                "state_delta": "goal preserved through handoff",
                "allowed_claims": [],
                "forbidden_claims": ["goal cancelled"],
            },
            tags=["phase:identity_valid", "utterance:human"],
        )
    )
    return cases


def freeze_fresh(cases: list[dict[str, Any]], protocol_hashes: dict[str, str]) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "seed": FRESH_SEED,
        "generator": GENERATOR,
        "generated_at": utc_now(),
        "protocol_hashes": protocol_hashes,
        "cases": cases,
    }
    FRESH_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    FRESH_PATH.write_text(text, encoding="utf-8")
    return hash_text(text)


def split_scenarios(cases: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Deterministic two-thirds development, one-third frozen held-out."""
    dev: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    for case in cases:
        digest = int(hash_text(SEED + case["case_id"])[:8], 16)
        (held if digest % 3 == 0 else dev).append(case)
    return dev, held


def freeze_held_out(cases: list[dict[str, Any]], protocol_hashes: dict[str, str]) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "seed": SEED,
        "generator": GENERATOR,
        "generated_at": utc_now(),
        "protocol_hashes": protocol_hashes,
        "cases": cases,
    }
    HELD_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    HELD_OUT_PATH.write_text(text, encoding="utf-8")
    return hash_text(text)


async def run_cases(
    cases: list[dict[str, Any]],
    harness_language: str,
    *,
    phase: str,
) -> int:
    problems = validate_corpus(cases)
    if problems:
        for problem in problems:
            print(f"GENERATED {problem}", file=sys.stderr)
        return 2
    prompt_source = resolve_prompt_source(
        "prompt_composition_protocols", harness_language=harness_language
    )
    baseline = GeminiBaseline.from_env()
    client = Client(
        vertexai=True,
        project=baseline.project,
        location=baseline.location,
        http_options=HttpOptions(api_version=baseline.api_version),
    )
    metrics = RecordingTurnMetrics()
    model = GeminiTurnModel(client, baseline, prompts=prompt_source, metrics=metrics)
    experimental = ExperimentalMemoryConfig(variant=RECENT_CONVERSATION_MEMORY, window_n=3)
    now = datetime.now(UTC)
    verdicts: list[str] = []
    failures: list[dict[str, Any]] = []
    try:
        for case in cases:
            for trial_id, turn_index in iter_trials(case):
                replay = await replay_trial(
                    model,
                    metrics,
                    case,
                    trial_id,
                    turn_index,
                    now=now,
                    experimental=experimental,
                )
                repetition = finalize_repetition(case, replay, repetition_id=1)
                verdicts.append(repetition.classification)
                if repetition.classification in {
                    Outcome.FAIL.value,
                    Outcome.MODEL_FAILURE.value,
                    Outcome.NOT_REPRESENTABLE.value,
                }:
                    failures.append(
                        {
                            "case_id": case["case_id"],
                            "classification": repetition.classification,
                            "details": repetition.failure_details[:4],
                        }
                    )
    finally:
        await client.aio.aclose()
    report = {
        "phase": phase,
        "generator": GENERATOR,
        "seed": SEED,
        "cases": len(cases),
        "verdicts": summarize_verdicts(verdicts),
        "failures": failures,
        "recorded_at": utc_now(),
    }
    findings = sanitization_findings(report)
    if findings:
        raise ValueError(f"synthetic report failed sanitization: {findings}")
    output = REPO_ROOT / "evals" / "results" / f"{phase}-{harness_language}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("cases", "verdicts")}, sort_keys=True))
    for failure in failures:
        print("FAIL", failure["case_id"], failure["classification"], failure["details"])
    print(f"report={output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CU013 synthetic robustness suite")
    parser.add_argument("--freeze-held-out", action="store_true")
    parser.add_argument("--run-dev", action="store_true")
    parser.add_argument("--run-held-out", action="store_true")
    parser.add_argument("--freeze-fresh", action="store_true")
    parser.add_argument("--run-fresh", action="store_true")
    parser.add_argument("--protocol-dir", default=None)
    parser.add_argument("--harness-language", choices=["es", "en"], default="es")
    args = parser.parse_args(argv)
    cases = compose_scenarios()
    problems = validate_corpus(cases)
    if problems:
        for problem in problems:
            print(f"GENERATED {problem}", file=sys.stderr)
        return 2
    dev, held = split_scenarios(cases)
    if args.freeze_held_out or args.freeze_fresh:
        from app.conversation.prompt_loader import load_prompt_bundle

        bundle = load_prompt_bundle(
            protocol_dir=Path(args.protocol_dir) if args.protocol_dir else None
        )
        if args.freeze_held_out:
            digest = freeze_held_out(held, bundle.module_hashes())
            print(f"held-out frozen: cases={len(held)} sha256={digest}")
            print(f"path={HELD_OUT_PATH}")
        if args.freeze_fresh:
            fresh = compose_fresh_scenarios()
            fresh_problems = validate_corpus(fresh)
            if fresh_problems:
                for problem in fresh_problems:
                    print(f"FRESH {problem}", file=sys.stderr)
                return 2
            fresh_digest = freeze_fresh(fresh, bundle.module_hashes())
            print(f"fresh frozen: cases={len(fresh)} sha256={fresh_digest}")
            print(f"path={FRESH_PATH}")
    if args.run_dev:
        return asyncio.run(run_cases(dev, args.harness_language, phase="synthetic-dev"))
    if args.run_held_out:
        payload = yaml.safe_load(HELD_OUT_PATH.read_text(encoding="utf-8"))
        held_cases = payload["cases"]
        from app.conversation.prompt_loader import load_prompt_bundle

        bundle = load_prompt_bundle(
            protocol_dir=Path(args.protocol_dir) if args.protocol_dir else None
        )
        current = bundle.module_hashes()
        frozen = payload.get("protocol_hashes", {})
        drift = sorted(
            name for name, digest in frozen.items() if name in current and current[name] != digest
        )
        if drift:
            print(f"HELD-OUT MODULE DRIFT: {drift}", file=sys.stderr)
            return 2
        return asyncio.run(run_cases(held_cases, args.harness_language, phase="synthetic-held-out"))
    if args.run_fresh:
        fresh_cases = compose_fresh_scenarios()
        fresh_problems = validate_corpus(fresh_cases)
        if fresh_problems:
            for problem in fresh_problems:
                print(f"FRESH {problem}", file=sys.stderr)
            return 2
        return asyncio.run(run_cases(fresh_cases, args.harness_language, phase="fresh-robustness"))
    if not (args.freeze_held_out or args.run_dev or args.run_held_out or args.freeze_fresh):
        parser.error("pass --freeze-held-out, --run-dev and/or --run-held-out")
    return 0


if __name__ == "__main__":
    sys.exit(main())
