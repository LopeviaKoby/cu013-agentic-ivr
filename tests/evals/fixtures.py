"""Synthetic fixtures for the evaluation-lab tests.

No model, network, ADC or credentials are involved: the scripted doubles
return canned decisions or raise the production error classes, and the
artifacts are minimal dictionaries with the same shape the evaluator writes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.session.memory import ProcedureObservation
from app.session.metrics import RecordingTurnMetrics
from app.session.record import ConfirmationChallenge, ConversationGoal, ExternalOperation
from app.session.turns import (
    Claim,
    ClaimKind,
    ConfirmationObservation,
    GoalIntent,
    GoalProposal,
    HandoffCause,
    ModelTurnDecision,
    Route,
)

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


class ScriptedModel:
    """TurnModel double: each call pops the next scripted item.

    An item is either a `ModelTurnDecision` or an exception instance; the last
    item repeats forever once the script is exhausted.
    """

    def __init__(self, script: list[Any], *, metrics: RecordingTurnMetrics | None = None) -> None:
        self.script = list(script)
        self.metrics = metrics
        self.calls: list[dict[str, Any]] = []

    async def decide(
        self,
        *,
        transcript: str,
        goal: ConversationGoal | None,
        identity_validated: bool,
        confirmation: ConfirmationChallenge | None,
        external_operation: ExternalOperation | None,
        memory_context: str | None = None,
        procedure_current: str | None = None,
        state_projection: object | None = None,
        delivery_secret: str | None = None,
    ) -> ModelTurnDecision:
        self.calls.append(
            {
                "transcript": transcript,
                "goal": goal,
                "identity_validated": identity_validated,
                "confirmation": confirmation,
                "external_operation": external_operation,
                "memory_context": memory_context,
                "procedure_current": procedure_current,
                "state_projection": state_projection,
            }
        )
        item = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        if self.metrics is not None:
            self.metrics.record_counter("prompt_tokens", 1234)
            self.metrics.record_counter("completion_tokens", 56)
        return item


def make_decision(
    *,
    route: str = "CONTINUE",
    goal_intent: str | None = None,
    goal_action: str | None = None,
    confirmation_request: bool = False,
    confirmation_observation: str = "NONE",
    procedure_observation: str = "NONE",
    handoff_cause: str | None = None,
    claim_kinds: tuple[str, ...] = (),
    message: str = "synthetic message",
) -> ModelTurnDecision:
    goal = None
    if goal_intent is not None:
        goal = GoalProposal(intent=GoalIntent(goal_intent), action=goal_action)
    return ModelTurnDecision(
        message=message,
        route=Route(route),
        goal=goal,
        confirmation_request=confirmation_request,
        confirmation_observation=ConfirmationObservation(confirmation_observation),
        procedure_observation=ProcedureObservation(procedure_observation),
        handoff_cause=HandoffCause(handoff_cause) if handoff_cause else None,
        claims=tuple(Claim(kind=ClaimKind(kind)) for kind in claim_kinds),
    )


def make_case(
    *,
    case_id: str = "case-a",
    family: str = "family-a",
    scenario_kind: str = "independent_trial",
    turns: list[dict[str, Any]] | None = None,
    expected: dict[str, Any] | None = None,
    initial_state: dict[str, Any] | None = None,
    external_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "family": family,
        "scenario_kind": scenario_kind,
        "description": "synthetic test case",
        "initial_state": initial_state
        or {
            "identity_validated": False,
            "conversation_goal": None,
            "goal_revision": 0,
            "confirmation": None,
            "pending_operation": None,
        },
        "turns": turns if turns is not None else [{"transcript": "hola"}],
        "external_events": external_events or [],
        "expected": expected if expected is not None else {"route": "CONTINUE"},
    }


def make_trial(
    *,
    case_id: str = "case-a",
    family: str = "family-a",
    trial_id: str | None = None,
    scenario_kind: str = "independent_trial",
    repetitions: list[dict[str, Any]] | None = None,
    expected: dict[str, Any] | None = None,
    controls: dict[str, list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "family": family,
        "trial_id": trial_id or case_id,
        "scenario_kind": scenario_kind,
        "expected": expected or {"route": "CONTINUE"},
        "expected_property_kinds": {},
        "controls": controls or {},
        "summary": {"classification": "PASS", "verdicts": {"PASS": 1}},
        "repetitions": repetitions or [make_repetition()],
    }


def make_repetition(
    *,
    repetition_id: int = 1,
    classification: str = "PASS",
    status: str = "valid",
    case_verdicts: dict[str, str] | None = None,
    turn_verdicts: list[dict[str, str]] | None = None,
    critical_findings: list[str] | None = None,
    failure_details: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "repetition_id": repetition_id,
        "status": status,
        "error_class": None,
        "classification": classification,
        "case_verdicts": case_verdicts or {"route": "PASS"},
        "turn_verdicts": turn_verdicts or [],
        "first_divergent_turn": None,
        "goal_continuity": "not_applicable",
        "authorization_result": "not_authorized",
        "dispatch_count": 0,
        "critical_findings": critical_findings or [],
        "blocked_proposals": [],
        "failure_details": failure_details or [],
        "accumulated": {},
        "turns": [],
    }


def make_artifact(
    *,
    run_id: str = "run-1",
    variant: dict[str, Any] | None = None,
    corpus_sha: str = "corpus-sha",
    evaluator_sha: str = "evaluator-sha",
    cases: list[dict[str, Any]] | None = None,
    infra_count: int = 0,
    prompt_p50: float = 1000.0,
    latency_p50: float = 100.0,
) -> dict[str, Any]:
    identity = variant or {
        "source_git_sha": "abc",
        "effective_prompt_hash": "prompt-hash",
        "model_id": "gemini-2.5-flash-lite",
        "working_tree_diff_hash": "clean",
    }
    return {
        "artifact_kind": "conversation_eval_run",
        "schema_version": 1,
        "run_id": run_id,
        "baseline_id": run_id,
        "candidate_id": run_id,
        "variant": identity,
        "variant_digest": f"digest-{run_id}",
        "corpus": {"sha256": corpus_sha},
        "evaluator": {"runner_sha256": evaluator_sha, "lab_sha256": "lab-sha"},
        "repetition_policy": {"valid_repetitions": 3, "warmups": 1},
        "aggregate": {
            "repetition_verdicts": {"PASS": 1},
            "case_summaries": {"PASS": 1},
            "case_properties": {"route": {"PASS": 1}},
            "turn_properties": {"route": {"PASS": 1}},
            "route_distribution": {"CONTINUE": 1},
            "families": {},
            "sequences": [],
        },
        "latency": {
            "model_latency_ms": {
                "count": 1,
                "min": 0.0,
                "p50": latency_p50,
                "p95": 0.0,
                "max": 0.0,
            },
            "runtime_semantic_ms": {"count": 1, "min": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0},
            "total_turn_ms": {"count": 1, "min": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0},
        },
        "tokens": {
            "prompt_tokens": {
                "count": 1,
                "min": 0,
                "p50": prompt_p50,
                "p95": 0,
                "max": 0,
                "missing": 0,
            },
            "completion_tokens": {
                "count": 1,
                "min": 0,
                "p50": 50,
                "p95": 0,
                "max": 0,
                "missing": 0,
            },
        },
        "warmups": [],
        "cases": cases if cases is not None else [make_trial()],
        "infra_count": infra_count,
    }
