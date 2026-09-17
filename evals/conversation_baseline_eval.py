"""Runtime semantic evaluation of the corpus against the real model.

Manual DEV runner, outside CI: it replays the versioned conversation corpus
(`evals/conversation/cases.yaml`) against the real `GeminiTurnModel` and the
deterministic runtime (ADR-0010), then compares the observed semantic planes
per family: route, conversation goal, confirmation state, action and
escalation eligibility and dispatch count. It replaced the pre-implementation
baseline runner once the structured model contract changed; the recorded
baseline results live in `CONTEXT.md` and Experiment 0005.

Boundary events in the corpus (identity validation, confirmation timeout,
dispatch timeout, results, delivery) are simulated domain events because the
XCALLY/AD wire contract is still open (ID-001, XC-001..XC-006): the runner
never invents or calls an HTTP payload. Only routes, state and claims are
compared, never wording. Event-only cases (no conversational turn) are
evaluated on state, and their route is reported as NOT EVALUATED.

Usage:
    python evals/conversation_baseline_eval.py [--families fam1,fam2] [--repetitions 3]
    python evals/conversation_baseline_eval.py --validate-only
"""

import argparse
import asyncio
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from google.genai import Client
from google.genai.types import HttpOptions

from app.conversation.errors import ModelTimeoutError, ModelUnavailableError
from app.conversation.gemini import GeminiBaseline, GeminiTurnModel
from app.session.metrics import RecordingTurnMetrics
from app.session.record import (
    Action,
    AuthorizedDispatch,
    ConfirmationChallenge,
    ConversationGoal,
    DeliveryStatus,
    ExternalOperation,
    IdentityState,
    OperationStatus,
    SessionRecord,
)
from app.session.service import consolidate
from app.session.turns import (
    ConfirmationEvent,
    ConfirmationObservation,
    ExternalEvent,
    ExternalEventKind,
    IdentityOutcome,
    Route,
    TurnInput,
    advance_turn,
    initial_graph_state,
)

CORPUS_PATH = Path(__file__).parent / "conversation" / "cases.yaml"
DEFAULT_REPETITIONS = 3
FIXTURE_IDENTITY_BACKDATE = timedelta(minutes=1)
OPERATION_ID = "operation-1"

UNSPECIFIED_ROUTE = "UNSPECIFIED"
NOT_VALID_CONFIRMATION = "not_valid"

KNOWN_EXPECTED_KEYS = {
    "route",
    "conversation_goal",
    "confirmation_state",
    "action_eligibility",
    "dispatch_count",
    "state_delta",
    "escalation_eligibility",
    "allowed_claims",
    "forbidden_claims",
}
KNOWN_ROUTES = {"CONTINUE", "COLLECT_IDENTITY", "COMPLETE", "ESCALATE", UNSPECIFIED_ROUTE}
KNOWN_CONFIRMATION_STATES = {
    "pending",
    "authorized",
    "invalidated",
    "cancelled",
    "none",
    NOT_VALID_CONFIRMATION,
    "not_oracled",
}
KNOWN_ELIGIBILITIES = {"eligible", "not_eligible"}
KNOWN_EVENT_RESULTS: dict[str, set[str]] = {
    "identity_validation": {"caller_failure", "technical_failure"},
    "result": {"pending", "unknown", "confirmed", "failed"},
    "late_result": {"pending", "unknown", "confirmed", "failed"},
    "delivery": {"pending", "confirmed", "failed"},
    "confirmation_timeout": set(),
    "dispatch_timeout": set(),
    "goal_revision": set(),
}


@dataclass
class Observation:
    """What the runtime actually produced for one corpus replay."""

    route: str | None = None
    routes: list[str] = field(default_factory=list)
    goal: str | None = None
    goal_revision: int | None = None
    confirmation_state: str = "none"
    confirmation_conclusion: str | None = None
    action_eligibility: str = "not_eligible"
    dispatch_count: int = 0
    escalation_eligibility: str = "not_eligible"
    violations: list[str] = field(default_factory=list)
    declared_claims: list[str] = field(default_factory=list)
    model_latencies_ms: list[float] = field(default_factory=list)
    runtime_latencies_ms: list[float] = field(default_factory=list)
    turn_latencies_ms: list[float] = field(default_factory=list)
    prompt_tokens_per_call: list[int] = field(default_factory=list)
    completion_tokens_per_call: list[int] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    turns_replayed: int = 0


@dataclass
class Verdict:
    """Per-case comparison result."""

    case_id: str
    family: str
    event_only: bool
    turns_count: int
    route_stable: bool
    mismatches: list[str]
    observations: list[Observation]
    route_not_oracled: bool = False
    not_representable_fields: list[str] = field(default_factory=list)
    infrastructure_error: str | None = None

    @property
    def ok(self) -> bool:
        return (
            self.infrastructure_error is None
            and not self.not_representable_fields
            and (self.route_not_oracled or self.route_stable)
            and not self.mismatches
        )

    @property
    def classification(self) -> str:
        """PASS / FAIL / NOT ORACLED / NOT REPRESENTABLE / INFRA per case."""
        if self.infrastructure_error is not None:
            return "INFRA"
        if self.not_representable_fields:
            return "NOT REPRESENTABLE"
        if not self.route_not_oracled and not self.route_stable:
            return "FAIL"
        if self.mismatches:
            return "FAIL"
        if self.route_not_oracled:
            return "NOT ORACLED"
        return "PASS"


def load_corpus() -> list[dict[str, Any]]:
    with CORPUS_PATH.open("r", encoding="utf-8") as handle:
        data: list[dict[str, Any]] = yaml.safe_load(handle)["cases"]
        return data


def build_initial_record(case: dict[str, Any], now: datetime) -> SessionRecord:
    """Map the corpus initial_state onto the durable v2 contract."""
    state = case["initial_state"]
    action_value = state.get("conversation_goal")
    goal = (
        ConversationGoal(action=Action(action_value), revision=int(state.get("goal_revision", 0)))
        if action_value
        else None
    )
    validated_at: datetime | None = None
    if state.get("identity_validated"):
        validated_at = (
            now - timedelta(minutes=31)
            if state.get("identity_validated_at_expired")
            else now - FIXTURE_IDENTITY_BACKDATE
        )
    identity = IdentityState(
        validated_at=validated_at,
        caller_failures=int(state.get("identity_failure_count") or 0),
    )
    confirmation = None
    if state.get("confirmation") == "pending" and goal is not None:
        confirmation = ConfirmationChallenge(
            challenge_id="fixture-challenge",
            action=goal.action,
            goal_revision=int(state.get("confirmation_goal_revision", goal.revision)),
            identity_validated_at=validated_at or now,
            issued_at=now,
        )
    operation = None
    if state.get("pending_operation") and goal is not None:
        operation = ExternalOperation(
            operation_id=OPERATION_ID,
            action=goal.action,
            status=OperationStatus(state["pending_operation"]),
        )
    dispatch = None
    if state.get("confirmation") == "authorized" and goal is not None:
        dispatch = AuthorizedDispatch(
            operation_id=OPERATION_ID,
            action=goal.action,
            goal_revision=goal.revision,
            challenge_id="fixture-challenge",
            authorized_at=now,
        )
    return SessionRecord(
        conversation_id=case["case_id"],
        turn_count=0,
        revision=0,
        goal=goal,
        identity=identity,
        confirmation=confirmation,
        dispatch=dispatch,
        external_operation=operation,
        created_at=now,
        updated_at=now,
    )


def build_turn_input(
    case: dict[str, Any], transcript: str | None, *, with_events: bool
) -> TurnInput:
    """Translate one synthetic event into the domain seam, never into a payload."""
    values: dict[str, Any] = {"transcript": transcript if transcript else None}
    if with_events and case.get("external_events"):
        event = case["external_events"][0]
        kind = event["event"]
        if kind == "identity_validation":
            values["identity_outcome"] = IdentityOutcome(event["result"].upper())
        elif kind == "confirmation_timeout":
            values["confirmation_event"] = ConfirmationEvent.ASR_TIMEOUT
        elif kind == "dispatch_timeout":
            values["external_event"] = ExternalEvent(
                kind=ExternalEventKind.DISPATCH_UNKNOWN, operation_id=OPERATION_ID
            )
        elif kind in {"result", "late_result"}:
            values["external_event"] = ExternalEvent(
                kind=ExternalEventKind(kind.upper()),
                operation_id=OPERATION_ID,
                status=OperationStatus(event["result"]),
            )
        elif kind == "delivery":
            values["external_event"] = ExternalEvent(
                kind=ExternalEventKind.DELIVERY,
                operation_id=OPERATION_ID,
                delivery=DeliveryStatus(event["result"]),
            )
        # A goal_revision event is already represented by the fixture pair
        # (goal_revision vs confirmation_goal_revision): nothing to replay.
    return TurnInput.model_validate(values)


def _drain_usage(metrics: RecordingTurnMetrics) -> tuple[int, int, int]:
    """Read this call's token counters once, without double counting totals."""
    prompt = completion = total = 0
    for name, value in metrics.drain_counters():
        if name == "prompt_tokens":
            prompt += value
        elif name == "completion_tokens":
            completion += value
        elif name == "total_tokens":
            total += value
    return prompt, completion, total


async def replay_case(
    model: GeminiTurnModel,
    metrics: RecordingTurnMetrics,
    case: dict[str, Any],
    *,
    now: datetime,
) -> Observation:
    """Replay one corpus case through the real model and the real runtime."""
    record = build_initial_record(case, now)
    observation = Observation()
    turns: list[dict[str, Any]] = case.get("turns", [])
    transcripts: list[str | None] = [turn.get("transcript") for turn in turns] or [None]
    known_operation_ids: set[str] = (
        {record.dispatch.operation_id} if record.dispatch is not None else set()
    )
    new_dispatches = 0
    initial_challenge_id = record.confirmation.challenge_id if record.confirmation else None

    for index, transcript in enumerate(transcripts):
        turn_start = time.monotonic()
        turn_input = build_turn_input(case, transcript, with_events=index == len(transcripts) - 1)
        decision = None
        if turn_input.transcript is not None:
            model_start = time.monotonic()
            decision = await model.decide(
                transcript=turn_input.transcript,
                goal=record.goal,
                identity_validated=record.identity_is_valid(now),
                confirmation=record.confirmation,
                external_operation=record.external_operation,
            )
            observation.model_latencies_ms.append((time.monotonic() - model_start) * 1000.0)
            prompt, completion, total = _drain_usage(metrics)
            observation.prompt_tokens_per_call.append(prompt)
            observation.completion_tokens_per_call.append(completion)
            observation.prompt_tokens += prompt
            observation.completion_tokens += completion
            observation.total_tokens += total
            observation.declared_claims.extend(claim.kind.value for claim in decision.claims)
        runtime_start = time.monotonic()
        state = initial_graph_state(record, turn_input, now=now)
        state["model_decision"] = decision
        delta = advance_turn(state)
        record = consolidate(record, delta, now=now)
        observation.runtime_latencies_ms.append((time.monotonic() - runtime_start) * 1000.0)
        observation.turn_latencies_ms.append((time.monotonic() - turn_start) * 1000.0)
        observation.turns_replayed += 1

        outcome = delta["outcome"]
        if outcome is not None:
            observation.route = outcome.route.value
            observation.routes.append(outcome.route.value)
            observation.violations.extend(outcome.violations)
        if record.dispatch is not None and record.dispatch.operation_id not in (
            known_operation_ids
        ):
            known_operation_ids.add(record.dispatch.operation_id)
            new_dispatches += 1
        active_challenge_id = record.confirmation.challenge_id if record.confirmation else None
        if (
            initial_challenge_id is not None
            and active_challenge_id != initial_challenge_id
            and observation.confirmation_conclusion is None
            and new_dispatches == 0
        ):
            observation.confirmation_conclusion = (
                "cancelled"
                if decision is not None
                and decision.confirmation_observation
                in {ConfirmationObservation.NEGATIVE, ConfirmationObservation.CANCEL}
                else "invalidated"
            )

    observation.dispatch_count = new_dispatches
    if record.confirmation is not None:
        observation.confirmation_state = "pending"
    elif record.dispatch is not None and observation.confirmation_conclusion is None:
        observation.confirmation_state = "authorized"
    else:
        observation.confirmation_state = observation.confirmation_conclusion or "none"
    observation.goal = record.goal.action.value if record.goal is not None else None
    observation.goal_revision = record.goal.revision if record.goal is not None else None
    active_operation = (
        record.external_operation is not None and record.external_operation.is_active()
    )
    dispatch_open = (
        record.dispatch is not None
        and record.goal is not None
        and record.dispatch.goal_revision == record.goal.revision
    )
    observation.action_eligibility = (
        "eligible"
        if (
            record.goal is not None
            and record.identity_is_valid(now)
            and not dispatch_open
            and not active_operation
            and observation.route != Route.ESCALATE.value
        )
        else "not_eligible"
    )
    observation.escalation_eligibility = (
        "eligible"
        if observation.route == Route.ESCALATE.value or record.identity.requires_handoff()
        else "not_eligible"
    )
    return observation


def compare(
    case: dict[str, Any], observation: Observation, *, event_only: bool
) -> tuple[list[str], bool, list[str]]:
    """Compare one observation against the case expectations, semantically.

    Returns the mismatches, whether the route is intentionally not oracled,
    and any expected fields the runner cannot represent.
    """
    expected = case["expected"]
    mismatches: list[str] = []
    expected_route = expected.get("route")
    route_not_oracled = expected_route == UNSPECIFIED_ROUTE
    if (
        expected_route is not None
        and not route_not_oracled
        and observation.routes
        and not event_only
    ):
        if case.get("turn_semantics") == "paraphrases":
            # Every paraphrase probes the same property, not only the last one.
            for index, route in enumerate(observation.routes):
                if route != expected_route:
                    mismatches.append(
                        f"route turn{index + 1} expected={expected_route} observed={route}"
                    )
        elif observation.route != expected_route:
            mismatches.append(f"route expected={expected_route} observed={observation.route}")
    expected_goal = expected.get("conversation_goal")
    if expected_goal == "unchanged":
        expected_goal = case["initial_state"].get("conversation_goal")
    if expected_goal is not None and observation.goal != expected_goal:
        mismatches.append(f"goal expected={expected_goal} observed={observation.goal}")
    expected_confirmation = expected.get("confirmation_state")
    if expected_confirmation is not None:
        if expected_confirmation == "pending":
            if observation.confirmation_state != "pending":
                mismatches.append(
                    f"confirmation expected=pending observed={observation.confirmation_state}"
                )
        elif expected_confirmation == "authorized":
            if observation.confirmation_state != "authorized":
                mismatches.append(
                    f"confirmation expected=authorized observed={observation.confirmation_state}"
                )
        elif expected_confirmation == "invalidated":
            if observation.confirmation_conclusion != "invalidated":
                mismatches.append(
                    f"confirmation expected=invalidated observed={observation.confirmation_state}"
                )
        elif expected_confirmation == "cancelled":
            if observation.confirmation_conclusion != "cancelled":
                mismatches.append(
                    f"confirmation expected=cancelled observed={observation.confirmation_state}"
                )
        elif expected_confirmation == NOT_VALID_CONFIRMATION:
            # The contract cares that no challenge remains usable, not which
            # internal conclusion (invalidated/cancelled) produced that effect.
            if observation.confirmation_state not in {"invalidated", "cancelled", "none"}:
                mismatches.append(
                    f"confirmation expected=not_valid observed={observation.confirmation_state}"
                )
        elif expected_confirmation == "not_oracled":
            # The case does not oracle whether HITL started in this turn.
            pass
        elif observation.confirmation_state == "pending" and (
            observation.confirmation_conclusion is None
        ):
            mismatches.append("confirmation expected no active challenge but one is pending")
    expected_eligibility = expected.get("action_eligibility")
    if expected_eligibility is not None and observation.action_eligibility != expected_eligibility:
        mismatches.append(
            f"action_eligibility expected={expected_eligibility} "
            f"observed={observation.action_eligibility}"
        )
    expected_dispatch = expected.get("dispatch_count")
    if expected_dispatch is not None and observation.dispatch_count != expected_dispatch:
        mismatches.append(
            f"dispatch_count expected={expected_dispatch} observed={observation.dispatch_count}"
        )
    expected_escalation = expected.get("escalation_eligibility")
    if (
        expected_escalation is not None
        and observation.escalation_eligibility != expected_escalation
    ):
        mismatches.append(
            f"escalation_eligibility expected={expected_escalation} "
            f"observed={observation.escalation_eligibility}"
        )
    not_representable = sorted(set(expected) - KNOWN_EXPECTED_KEYS)
    return mismatches, route_not_oracled, not_representable


async def run_case(
    model: GeminiTurnModel,
    metrics: RecordingTurnMetrics,
    case: dict[str, Any],
    repetitions: int,
    *,
    now: datetime,
) -> Verdict:
    event_only = not case.get("turns")
    try:
        observations = [
            await replay_case(model, metrics, case, now=now) for _ in range(repetitions)
        ]
    except (ModelTimeoutError, ModelUnavailableError) as exc:
        # A transient Vertex failure is infrastructure evidence, never a
        # semantic verdict: it is reported and excluded from the comparison.
        return Verdict(
            case_id=case["case_id"],
            family=case["family"],
            event_only=event_only,
            turns_count=1,
            route_stable=False,
            mismatches=[],
            observations=[Observation()],
            infrastructure_error=type(exc).__name__,
        )
    route_stable = len({observation.route for observation in observations}) == 1
    compared = [compare(case, observation, event_only=event_only) for observation in observations]
    mismatches = sorted({mismatch for verdict, _, _ in compared for mismatch in verdict})
    route_not_oracled = any(flag for _, flag, _ in compared)
    not_representable = sorted({field for _, _, fields in compared for field in fields})
    return Verdict(
        case_id=case["case_id"],
        family=case["family"],
        event_only=event_only,
        turns_count=len(case.get("turns", [])) or 1,
        route_stable=route_stable,
        mismatches=mismatches,
        observations=observations,
        route_not_oracled=route_not_oracled,
        not_representable_fields=not_representable,
    )


def _percentile(values: list[float], percentile: float) -> float:
    """Nearest-rank percentile; deterministic and dependency-free."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100.0 * len(ordered)))
    return ordered[rank - 1]


def _print_latency_stats(label: str, values: list[float]) -> None:
    if not values:
        print(f"{label}: count=0")
        return
    print(
        f"{label}: count={len(values)} min={min(values):.1f} p50={_percentile(values, 50):.1f} "
        f"p95={_percentile(values, 95):.1f} max={max(values):.1f}"
    )


def _print_token_stats(label: str, values: list[int]) -> None:
    if not values:
        print(f"{label}: count=0")
        return
    floats = [float(value) for value in values]
    print(
        f"{label}: count={len(values)} min={min(values)} p50={_percentile(floats, 50):.0f} "
        f"p95={_percentile(floats, 95):.0f} max={max(values)}"
    )


def print_report(verdicts: list[Verdict], baseline: GeminiBaseline, repetitions: int) -> None:
    print("=== CU013 runtime semantic eval (manual, outside CI) ===")
    print(f"provider={baseline.provider} project={baseline.project}")
    print(f"location={baseline.location} model={baseline.model}")
    print(f"api_version={baseline.api_version} thinking_budget={baseline.thinking_budget}")
    print(f"repetitions={repetitions}")
    print("events are simulated domain events; the XCALLY/AD wire contract stays open")
    print()
    by_family: dict[str, list[Verdict]] = {}
    for verdict in verdicts:
        by_family.setdefault(verdict.family, []).append(verdict)
    families_ok = 0
    for family in sorted(by_family):
        items = by_family[family]
        counts: dict[str, int] = {}
        for item in items:
            counts[item.classification] = counts.get(item.classification, 0) + 1
        status = (
            "PASS"
            if counts.get("FAIL", 0) == 0 and counts.get("NOT REPRESENTABLE", 0) == 0
            else "FAIL"
        )
        if status == "PASS":
            families_ok += 1
        summary = " ".join(
            f"{key.lower().replace(' ', '_')}={counts[key]}" for key in sorted(counts)
        )
        print(f"[{status}] family={family} cases={len(items)} {summary}")
        for item in items:
            observation = item.observations[0]
            if item.infrastructure_error is not None:
                print(f"  {item.case_id}: INFRA {item.infrastructure_error} (not evaluated)")
                continue
            if item.route_not_oracled:
                route = UNSPECIFIED_ROUTE
            elif item.event_only or not observation.routes:
                route = "NOT EVALUATED"
            else:
                route = observation.route
            print(
                f"  {item.case_id}: route={route} goal={observation.goal} "
                f"revision={observation.goal_revision} "
                f"confirmation={observation.confirmation_state} "
                f"conclusion={observation.confirmation_conclusion} "
                f"eligibility={observation.action_eligibility} "
                f"dispatches={observation.dispatch_count} "
                f"model_max={max(observation.model_latencies_ms, default=0.0):.0f}ms "
                f"tokens={observation.total_tokens} "
                f"turns={observation.turns_replayed}"
            )
            for mismatch in item.mismatches:
                print(f"    MISMATCH {mismatch}")
            if item.not_representable_fields:
                print(f"    NOT REPRESENTABLE fields={item.not_representable_fields}")
            if observation.violations:
                print(f"    guard_violations={sorted(set(observation.violations))}")
            if not item.route_stable and not item.route_not_oracled:
                print("    route unstable across repetitions")
    print()
    _print_latency_stats(
        "latency_ms model",
        [
            value
            for item in verdicts
            for observation in item.observations
            for value in observation.model_latencies_ms
        ],
    )
    _print_latency_stats(
        "latency_ms runtime_semantic",
        [
            value
            for item in verdicts
            for observation in item.observations
            for value in observation.runtime_latencies_ms
        ],
    )
    _print_latency_stats(
        "latency_ms turn_total",
        [
            value
            for item in verdicts
            for observation in item.observations
            for value in observation.turn_latencies_ms
        ],
    )
    _print_token_stats(
        "tokens_prompt",
        [
            value
            for item in verdicts
            for observation in item.observations
            for value in observation.prompt_tokens_per_call
        ],
    )
    _print_token_stats(
        "tokens_completion",
        [
            value
            for item in verdicts
            for observation in item.observations
            for value in observation.completion_tokens_per_call
        ],
    )
    multi_turn = [item for item in verdicts if item.turns_count > 1]
    print(f"accumulated_tokens: multi-turn/paraphrase cases={len(multi_turn)} (mean per replay)")
    for item in multi_turn:
        observations = item.observations
        divisor = len(observations)
        prompt = sum(observation.prompt_tokens for observation in observations) / divisor
        completion = sum(observation.completion_tokens for observation in observations) / divisor
        total = sum(observation.total_tokens for observation in observations) / divisor
        print(
            f"  {item.case_id}: turns={observations[0].turns_replayed} "
            f"prompt={prompt:.0f} completion={completion:.0f} total={total:.0f}"
        )
    print()
    total = len(verdicts)
    classifications: dict[str, int] = {}
    for verdict in verdicts:
        classifications[verdict.classification] = classifications.get(verdict.classification, 0) + 1
    summary = " ".join(
        f"{key.lower().replace(' ', '_')}={classifications[key]}" for key in sorted(classifications)
    )
    print(f"families_pass={families_ok}/{len(by_family)} cases={total} {summary}")


def validate_corpus(cases: list[dict[str, Any]]) -> list[str]:
    """Static corpus validation: no model, no ADC, no network."""
    problems: list[str] = []
    case_ids = {case.get("case_id") for case in cases}
    for case in cases:
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.replace("-", "").isalnum():
            problems.append(f"invalid case_id: {case_id!r}")
            continue
        if sum(1 for candidate in cases if candidate.get("case_id") == case_id) > 1:
            problems.append(f"duplicate case_id: {case_id}")
        if not isinstance(case.get("family"), str) or not case.get("family"):
            problems.append(f"{case_id}: missing family")
        if not isinstance(case.get("initial_state"), dict):
            problems.append(f"{case_id}: initial_state must be a mapping")
        if not isinstance(case.get("turns", []), list):
            problems.append(f"{case_id}: turns must be a list")
        expected = case.get("expected")
        if not isinstance(expected, dict):
            problems.append(f"{case_id}: missing expected")
        else:
            route = expected.get("route")
            if route is not None and route not in KNOWN_ROUTES:
                problems.append(f"{case_id}: unknown route {route!r}")
            confirmation = expected.get("confirmation_state")
            if confirmation is not None and confirmation not in KNOWN_CONFIRMATION_STATES:
                problems.append(f"{case_id}: unknown confirmation_state {confirmation!r}")
            for field in ("action_eligibility", "escalation_eligibility"):
                value = expected.get(field)
                if value is not None and value not in KNOWN_ELIGIBILITIES:
                    problems.append(f"{case_id}: unknown {field} {value!r}")
            dispatch = expected.get("dispatch_count")
            if dispatch is not None and (not isinstance(dispatch, int) or dispatch not in {0, 1}):
                problems.append(f"{case_id}: dispatch_count must be 0 or 1")
            for field in sorted(set(expected) - KNOWN_EXPECTED_KEYS):
                problems.append(f"{case_id}: expected field not representable: {field}")
        for event in case.get("external_events", []):
            kind = event.get("event")
            if kind not in KNOWN_EVENT_RESULTS:
                problems.append(f"{case_id}: unknown event {kind!r}")
                continue
            result = event.get("result")
            if result is not None and result not in KNOWN_EVENT_RESULTS[kind]:
                problems.append(f"{case_id}: unknown result {result!r} for {kind}")
        for group in (case.get("controls") or {}).values():
            for control in group:
                reference = control.get("case_id")
                if reference not in case_ids:
                    problems.append(f"{case_id}: control references unknown case {reference!r}")
    return problems


async def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--families", default=None, help="comma-separated family filter")
    parser.add_argument(
        "--repetitions", type=int, default=DEFAULT_REPETITIONS, help="replays per case"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the corpus statically; no ADC and no model call",
    )
    args = parser.parse_args()

    cases = load_corpus()
    if args.families:
        wanted = {family.strip() for family in args.families.split(",")}
        cases = [case for case in cases if case["family"] in wanted]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2
    if args.validate_only:
        problems = validate_corpus(cases)
        for problem in problems:
            print(f"CORPUS {problem}", file=sys.stderr)
        print(f"corpus validated: cases={len(cases)} problems={len(problems)}")
        return 1 if problems else 0

    baseline = GeminiBaseline.from_env()
    client = Client(
        vertexai=True,
        project=baseline.project,
        location=baseline.location,
        http_options=HttpOptions(api_version=baseline.api_version),
    )
    metrics = RecordingTurnMetrics()
    model = GeminiTurnModel(client, baseline, metrics=metrics)
    now = datetime.now(UTC)
    try:
        verdicts = [
            await run_case(model, metrics, case, args.repetitions, now=now) for case in cases
        ]
        print_report(verdicts, baseline, args.repetitions)
    finally:
        await client.aio.aclose()
    failed = any(verdict.classification in {"FAIL", "NOT REPRESENTABLE"} for verdict in verdicts)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
