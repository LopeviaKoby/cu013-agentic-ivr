"""Shared schema, oracles, fingerprints and statistics for the CU013 eval lab.

This module is pure and deterministic: it never imports the model adapter,
never opens a network connection and never touches credentials. The real-model
runner (`conversation_eval.py`) and the pure comparator
(`conversation_compare.py`) both build on it, and the deterministic tests under
`tests/evals/` exercise it with synthetic evidence.

Design rules materialized here:

- a corpus case has an explicit trial kind: `independent_trial` (every
  paraphrase/trial starts from the same fresh initial state) or `sequence`
  (state intentionally carries turn-to-turn and per-turn checkpoints are
  asserted);
- a present oracle key asserts a value, including an explicit null that means
  "expected absent"; an absent key is reported as NOT_ORACLED, so a missing
  oracle is never mistaken for a passing one;
- `state_delta`, `allowed_claims` and `forbidden_claims` are classified as
  descriptive metadata or human-review evidence, never as machine oracles;
- retained machine evidence carries IDs and allowlisted state projections
  only: never transcripts, messages, raw DTMF, document identity or secrets;
- missing token usage is `None` (missing), never 0.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = Path(__file__).resolve().parent / "conversation"
CORPUS_PATH = CORPUS_DIR / "cases.yaml"
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"

LAB_SCHEMA_VERSION = 1
RUN_ARTIFACT_KIND = "conversation_eval_run"
COMPARISON_ARTIFACT_KIND = "conversation_eval_comparison"

DEFAULT_REPETITIONS = 3
DEFAULT_WARMUPS = 1

MODEL_REVISION_UNAVAILABLE = "unavailable"
HISTORICAL_UNAVAILABLE = "unavailable_historical"
TOOLS_NONE = "none"


class TrialKind(StrEnum):
    """How a case's turns relate to each other during evaluation."""

    INDEPENDENT_TRIAL = "independent_trial"
    SEQUENCE = "sequence"


class OracleKind(StrEnum):
    """What kind of evidence an expected field really is."""

    MACHINE_ORACLE = "machine_oracle"
    HUMAN_REVIEW_EVIDENCE = "human_review_evidence"
    DESCRIPTIVE_METADATA = "descriptive_metadata"


class PropertyVerdict(StrEnum):
    """Verdict for one oracled property in one repetition."""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_ORACLED = "NOT_ORACLED"
    NOT_REPRESENTABLE = "NOT_REPRESENTABLE"


class RepetitionStatus(StrEnum):
    """A repetition is valid evidence or an infrastructure loss."""

    VALID = "valid"
    INFRA = "infra"


class Outcome(StrEnum):
    """Case or repetition classification."""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_ORACLED = "NOT_ORACLED"
    NOT_REPRESENTABLE = "NOT_REPRESENTABLE"
    MODEL_FAILURE = "MODEL_FAILURE"
    INFRA = "INFRA"


class CriticalClass(StrEnum):
    """Executed critical violations; any new one forces REJECT."""

    UNAUTHORIZED_DISPATCH = "unauthorized_dispatch"
    DUPLICATE_SIDE_EFFECT = "duplicate_side_effect"
    FALSE_BUSINESS_RESULT = "false_business_result"
    PII_OR_DTMF_LEAK = "pii_or_dtmf_leak"
    INVALID_IDENTITY_AUTHORIZATION = "invalid_identity_authorization"
    STALE_CHALLENGE_REUSE = "stale_challenge_reuse"
    ILLEGAL_HANDOFF = "illegal_handoff"
    UNKNOWN_REDISPATCH = "unknown_redispatch"


CRITICAL_CLASSES = tuple(item.value for item in CriticalClass)

ROUTES = ("CONTINUE", "COLLECT_IDENTITY", "COMPLETE", "ESCALATE")
UNSPECIFIED_ROUTE = "UNSPECIFIED"
NOT_ORACLED = "not_oracled"
NOT_VALID = "not_valid"

CASE_ORACLE_FIELDS: dict[str, OracleKind] = {
    "route": OracleKind.MACHINE_ORACLE,
    "conversation_goal": OracleKind.MACHINE_ORACLE,
    "confirmation_state": OracleKind.MACHINE_ORACLE,
    "action_eligibility": OracleKind.MACHINE_ORACLE,
    "dispatch_count": OracleKind.MACHINE_ORACLE,
    "escalation_eligibility": OracleKind.MACHINE_ORACLE,
    "handoff_cause": OracleKind.MACHINE_ORACLE,
    "state_delta": OracleKind.DESCRIPTIVE_METADATA,
    "allowed_claims": OracleKind.HUMAN_REVIEW_EVIDENCE,
    "forbidden_claims": OracleKind.HUMAN_REVIEW_EVIDENCE,
}

TURN_ORACLE_FIELDS: dict[str, OracleKind] = {
    "route": OracleKind.MACHINE_ORACLE,
    "goal": OracleKind.MACHINE_ORACLE,
    "goal_transition": OracleKind.MACHINE_ORACLE,
    "revision_transition": OracleKind.MACHINE_ORACLE,
    "confirmation": OracleKind.MACHINE_ORACLE,
    "identity_valid": OracleKind.MACHINE_ORACLE,
    "dispatch_count_unchanged": OracleKind.MACHINE_ORACLE,
    "operation": OracleKind.MACHINE_ORACLE,
    "obsolete_goal_absent": OracleKind.MACHINE_ORACLE,
    # Exp 0009 experimental memory/procedure oracles (synthetic lane only).
    "procedure_current": OracleKind.MACHINE_ORACLE,
    "procedure_last_completed": OracleKind.MACHINE_ORACLE,
    "window_pairs": OracleKind.MACHINE_ORACLE,
}

# Guided RESET steps accepted for the Exp 0009 synthetic trial, mirrored
# from app/session/memory.py (the lab never imports the runtime).
EXPERIMENTAL_GUIDED_STEPS = ("microsoft_portal", "tivit_portal", "service_desk")

CASE_CONFIRMATION_STATES = {
    "pending",
    "authorized",
    "invalidated",
    "cancelled",
    "none",
    NOT_VALID,
    NOT_ORACLED,
}
TURN_CONFIRMATION_STATES = {
    "absent",
    "pending",
    "changed",
    "new_challenge",
    "authorized",
    "invalidated",
    "cancelled",
    NOT_VALID,
    NOT_ORACLED,
}
GOAL_TRANSITIONS = {"absent", "created", "retained", "changed", "cleared", "not_oracled"}
REVISION_TRANSITIONS = {"created", "same", "incremented", "cleared", "not_oracled"}
OPERATION_STATES = {"none", "active", "pending", "unknown", "confirmed", "failed", NOT_ORACLED}
KNOWLEDGE_ELIGIBILITIES = {"eligible", "not_eligible"}
HANDOFF_CAUSES = {"CALLER_REQUEST", "TERMINAL_FAILURE", NOT_ORACLED}

KNOWN_EVENT_RESULTS: dict[str, set[str]] = {
    "identity_validation": {"caller_failure", "technical_failure", "validated"},
    "result": {"pending", "unknown", "confirmed", "failed"},
    "late_result": {"pending", "unknown", "confirmed", "failed"},
    "delivery": {"pending", "confirmed", "failed"},
    "confirmation_timeout": set(),
    "dispatch_timeout": set(),
    "goal_revision": set(),
}

ORACLE_PROSE_FIELDS = tuple(
    name for name, kind in CASE_ORACLE_FIELDS.items() if kind is not OracleKind.MACHINE_ORACLE
)

SPOKEN_QUALITY_CRITERIA = (
    "relevance",
    "voice_brevity",
    "answer_first_clarity",
    "non_repetition",
    "factual_restraint",
    "natural_transition_back_to_active_goal",
    "appropriate_transfer_wording",
)
SPOKEN_QUALITY_RATINGS = ("MEETS", "CONCERN", "NOT EVIDENCED")

FORBIDDEN_ARTIFACT_KEYS = frozenset(
    {
        "transcript",
        "transcripts",
        "message",
        "messages",
        "caller_text",
        "assistant_text",
        "memory_context",
        "document_id",
        "date_of_birth",
        "dob",
        "dtmf",
        "password",
        "secret",
        "api_key",
    }
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\b\d{8,}\b"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
)


class LabError(Exception):
    """Raised when evidence cannot be trusted or compared."""


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------


def load_corpus(path: Path = CORPUS_PATH) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data: list[dict[str, Any]] = yaml.safe_load(handle)["cases"]
        return data


def corpus_digest(path: Path = CORPUS_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trial_kind(case: Mapping[str, Any]) -> TrialKind:
    return TrialKind(case["scenario_kind"])


def iter_trials(case: Mapping[str, Any]) -> list[tuple[str, int | None]]:
    """Return (trial_id, turn_index) pairs; independent trials replay one turn each."""
    if trial_kind(case) is TrialKind.SEQUENCE:
        return [(str(case["case_id"]), None)]
    turns = list(case.get("turns") or [])
    if not turns:
        return [(_trial_id(case, None), None)]
    if len(turns) == 1:
        return [(_trial_id(case, 0), 0)]
    return [(_trial_id(case, index), index) for index in range(len(turns))]


def _trial_id(case: Mapping[str, Any], index: int | None) -> str:
    if index is None:
        return str(case["case_id"])
    return f"{case['case_id']}#t{index + 1}"


def turn_events(case: Mapping[str, Any], turn: Mapping[str, Any], *, is_last: bool) -> list[dict]:
    """Per-turn events take precedence; otherwise case events attach to the last turn."""
    own = turn.get("events")
    if own:
        return list(own)
    return list(case.get("external_events") or []) if is_last else []


def validate_corpus(cases: Sequence[Mapping[str, Any]]) -> list[str]:
    """Static corpus validation: no model, no ADC, no network."""
    problems: list[str] = []
    case_ids = {case.get("case_id") for case in cases}
    for case in cases:
        problems.extend(_validate_case(case, cases, case_ids))
    return problems


def _validate_case(
    case: Mapping[str, Any], cases: Sequence[Mapping[str, Any]], case_ids: set[Any]
) -> list[str]:
    problems: list[str] = []
    case_id = case.get("case_id")
    if not isinstance(case_id, str) or not case_id.replace("-", "").isalnum():
        return [f"invalid case_id: {case_id!r}"]
    if sum(1 for candidate in cases if candidate.get("case_id") == case_id) > 1:
        problems.append(f"duplicate case_id: {case_id}")
    if not isinstance(case.get("family"), str) or not case.get("family"):
        problems.append(f"{case_id}: missing family")
    if case.get("scenario_kind") not in {kind.value for kind in TrialKind}:
        kind = case.get("scenario_kind")
        problems.append(f"{case_id}: missing or unknown scenario_kind {kind!r}")
    if not isinstance(case.get("initial_state"), dict):
        problems.append(f"{case_id}: initial_state must be a mapping")
    turns = case.get("turns", [])
    if not isinstance(turns, list):
        problems.append(f"{case_id}: turns must be a list")
        turns = []
    for index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            problems.append(f"{case_id}: turn {index + 1} must be a mapping")
            continue
        expect = turn.get("expect")
        if expect is None:
            continue
        if not isinstance(expect, dict):
            problems.append(f"{case_id}: turn {index + 1} expect must be a mapping")
            continue
        problems.extend(_validate_expect(case_id, expect, index + 1, turn=True))
        problems.extend(_validate_turn_events(case_id, turn.get("events") or [], index + 1))
    expected = case.get("expected")
    if not isinstance(expected, dict):
        problems.append(f"{case_id}: missing expected")
    else:
        problems.extend(_validate_expect(case_id, expected, None, turn=False))
    problems.extend(_validate_turn_events(case_id, case.get("external_events") or [], None))
    for group in (case.get("controls") or {}).values():
        for control in group:
            reference = control.get("case_id")
            if reference not in case_ids:
                problems.append(f"{case_id}: control references unknown case {reference!r}")
    return problems


def _validate_expect(
    case_id: str, expect: Mapping[str, Any], turn_index: int | None, *, turn: bool
) -> list[str]:
    problems: list[str] = []
    known = TURN_ORACLE_FIELDS if turn else CASE_ORACLE_FIELDS
    where = f"{case_id}: turn {turn_index} expect" if turn else f"{case_id}: expected"
    for name in expect:
        if name not in known:
            problems.append(f"{where}: field not representable: {name}")
    route = expect.get("route")
    if route is not None and route not in set(ROUTES) | {UNSPECIFIED_ROUTE}:
        problems.append(f"{where}: unknown route {route!r}")
    confirmation = expect.get("confirmation_state" if not turn else "confirmation")
    allowed_confirmation = CASE_CONFIRMATION_STATES if not turn else TURN_CONFIRMATION_STATES
    if confirmation is not None and confirmation not in allowed_confirmation:
        problems.append(f"{where}: unknown confirmation {confirmation!r}")
    for name, allowed in (
        ("action_eligibility", KNOWLEDGE_ELIGIBILITIES),
        ("escalation_eligibility", KNOWLEDGE_ELIGIBILITIES),
    ):
        value = expect.get(name)
        if value is not None and value not in allowed:
            problems.append(f"{where}: unknown {name} {value!r}")
    if not turn:
        dispatch = expect.get("dispatch_count")
        if dispatch is not None and (not isinstance(dispatch, int) or dispatch not in {0, 1}):
            problems.append(f"{where}: dispatch_count must be 0 or 1")
        handoff = expect.get("handoff_cause")
        if handoff is not None and handoff not in HANDOFF_CAUSES:
            problems.append(f"{where}: unknown handoff_cause {handoff!r}")
        for name in ("allowed_claims", "forbidden_claims"):
            value = expect.get(name)
            if value is not None and not isinstance(value, list):
                problems.append(f"{where}: {name} must be a list")
    else:
        transition = expect.get("goal_transition")
        if transition is not None and transition not in GOAL_TRANSITIONS:
            problems.append(f"{where}: unknown goal_transition {transition!r}")
        revision = expect.get("revision_transition")
        if revision is not None and revision not in REVISION_TRANSITIONS:
            problems.append(f"{where}: unknown revision_transition {revision!r}")
        operation = expect.get("operation")
        if operation is not None and operation not in OPERATION_STATES:
            problems.append(f"{where}: unknown operation {operation!r}")
        identity = expect.get("identity_valid")
        if identity is not None and not isinstance(identity, bool):
            problems.append(f"{where}: identity_valid must be a boolean")
        unchanged = expect.get("dispatch_count_unchanged")
        if unchanged is not None and unchanged is not True:
            problems.append(f"{where}: dispatch_count_unchanged only supports true")
        obsolete = expect.get("obsolete_goal_absent")
        if obsolete is not None and obsolete is not True:
            problems.append(f"{where}: obsolete_goal_absent only supports true")
        for step_key in ("procedure_current", "procedure_last_completed"):
            step = expect.get(step_key)
            if step is not None and step != NOT_ORACLED and step not in EXPERIMENTAL_GUIDED_STEPS:
                problems.append(f"{where}: unknown {step_key} {step!r}")
        window_pairs = expect.get("window_pairs")
        if (
            window_pairs is not None
            and window_pairs != NOT_ORACLED
            and (not isinstance(window_pairs, int) or window_pairs < 0)
        ):
            problems.append(f"{where}: window_pairs must be a non-negative int")
    return problems


def _validate_turn_events(
    case_id: str, events: Sequence[Mapping[str, Any]], turn_index: int | None
) -> list[str]:
    problems: list[str] = []
    where = f"{case_id}: turn {turn_index} events" if turn_index else f"{case_id}: events"
    for event in events:
        kind = event.get("event")
        if kind not in KNOWN_EVENT_RESULTS:
            problems.append(f"{where}: unknown event {kind!r}")
            continue
        result = event.get("result")
        if result is not None and result not in KNOWN_EVENT_RESULTS[kind]:
            problems.append(f"{where}: unknown result {result!r} for {kind}")
    return problems


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------


def sanitization_findings(payload: Any, *, path: str = "$") -> list[str]:
    """Report forbidden keys or sensitive-looking values in retained evidence."""
    findings: list[str] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            location = f"{path}.{key}"
            if isinstance(key, str) and key.lower() in FORBIDDEN_ARTIFACT_KEYS:
                findings.append(f"forbidden key {location}")
            findings.extend(sanitization_findings(value, path=location))
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            findings.extend(sanitization_findings(item, path=f"{path}[{index}]"))
    elif isinstance(payload, str):
        for pattern in SENSITIVE_VALUE_PATTERNS:
            if pattern.search(payload):
                findings.append(f"sensitive value pattern in {path}")
                break
    return findings


# ---------------------------------------------------------------------------
# State projection
# ---------------------------------------------------------------------------


@dataclass
class StateProjection:
    """Allowlisted, PII-free projection of the durable semantic planes."""

    goal_action: str | None = None
    goal_revision: int | None = None
    identity_validated: bool = False
    identity_validated_at: str | None = None
    identity_expires_at: str | None = None
    identity_caller_failures: int = 0
    challenge_id: str | None = None
    challenge_action: str | None = None
    challenge_goal_revision: int | None = None
    challenge_identity_validated_at: str | None = None
    dispatch_operation_id: str | None = None
    dispatch_goal_revision: int | None = None
    dispatch_challenge_id: str | None = None
    operation_id: str | None = None
    operation_action: str | None = None
    operation_status: str | None = None
    operation_delivery: str | None = None
    # Exp 0009 experimental facts: identifiers, steps and counts only, never
    # caller/assistant text.
    procedure_id: str | None = None
    procedure_current: str | None = None
    procedure_last_completed: str | None = None
    procedure_goal_revision: int | None = None
    procedure_suspended: bool = False
    memory_pairs: int = 0
    memory_bytes: int = 0
    memory_omitted: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def state_delta(before: StateProjection, after: StateProjection) -> dict[str, dict[str, Any]]:
    """Changed allowlisted fields between two projections."""
    delta: dict[str, dict[str, Any]] = {}
    for name, before_value in before.to_dict().items():
        after_value = after.to_dict()[name]
        if before_value != after_value:
            delta[name] = {"before": before_value, "after": after_value}
    return delta


# ---------------------------------------------------------------------------
# Turn observation
# ---------------------------------------------------------------------------


@dataclass
class ToolObservation:
    """Future tool-choice evidence; no product tool exists yet.

    The schema exists so a later capability can be observed without
    redesigning the lab. The current baseline records `tools = none` and no
    tool observations.
    """

    selected_capability: str | None = None
    arguments_semantic_result: str | None = None
    required_arguments_present: bool | None = None
    forbidden_sensitive_arguments_absent: bool | None = None
    prerequisites_satisfied: bool | None = None
    runtime_execution: str | None = None
    duplicate_tool_decision: bool | None = None
    result_operation_attribution: str | None = None
    communicated_truth_supported: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TurnObservation:
    """Sanitized evidence for one evaluated turn; never transcript text."""

    turn_index: int
    input_id: str | None
    event_id: str | None
    event_kind: str | None
    model_called: bool
    proposed_route: str | None
    proposed_goal_intent: str | None
    proposed_goal_action: str | None
    proposed_confirmation_request: bool | None
    proposed_confirmation_observation: str | None
    proposed_handoff_cause: str | None
    proposed_claim_kinds: list[str]
    runtime_route: str | None
    goal_transition: str
    revision_transition: str
    confirmation_state: str
    confirmation_conclusion: str | None
    handoff_cause: str | None
    identity_valid: bool
    identity_requires_handoff: bool
    operation_state: str
    dispatch_eligible: bool
    dispatched: bool
    dispatch_count_before: int
    dispatch_count_after: int
    critical_findings: list[str]
    blocked_proposals: list[str]
    state_before: StateProjection
    state_after: StateProjection
    model_latency_ms: float | None
    runtime_semantic_ms: float | None
    total_turn_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None = None
    session_bytes: int | None = None
    session_bytes_over_guard: bool = False
    memory_encode_ms: float | None = None
    memory_decode_ms: float | None = None
    memory_render_ms: float | None = None
    memory_pairs: int = 0
    error_class: str | None = None
    tools: list[ToolObservation] = field(default_factory=list)
    proposed_procedure_observation: str | None = None
    procedure_observation_emitted: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state_delta"] = state_delta(self.state_before, self.state_after)
        return payload


@dataclass
class RepetitionObservation:
    """One complete replay of a trial: per-property verdicts and evidence."""

    repetition_id: int
    status: str
    error_class: str | None
    classification: str
    case_verdicts: dict[str, str]
    turn_verdicts: list[dict[str, str]]
    first_divergent_turn: int | None
    goal_continuity: str
    authorization_result: str
    dispatch_count: int
    critical_findings: list[str]
    blocked_proposals: list[str]
    accumulated: dict[str, float | int | None]
    failure_details: list[str] = field(default_factory=list)
    turns: list[TurnObservation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repetition_id": self.repetition_id,
            "status": self.status,
            "error_class": self.error_class,
            "classification": self.classification,
            "case_verdicts": dict(self.case_verdicts),
            "turn_verdicts": [dict(item) for item in self.turn_verdicts],
            "first_divergent_turn": self.first_divergent_turn,
            "goal_continuity": self.goal_continuity,
            "authorization_result": self.authorization_result,
            "dispatch_count": self.dispatch_count,
            "critical_findings": list(self.critical_findings),
            "blocked_proposals": list(self.blocked_proposals),
            "failure_details": list(self.failure_details),
            "accumulated": dict(self.accumulated),
            "turns": [turn.to_dict() for turn in self.turns],
        }


# ---------------------------------------------------------------------------
# Oracles
# ---------------------------------------------------------------------------


def classify_verdicts(verdicts: Mapping[str, str], *, model_failure: bool = False) -> str:
    """Aggregate per-property verdicts into one repetition classification."""
    if model_failure:
        return Outcome.MODEL_FAILURE.value
    values = set(verdicts.values())
    if PropertyVerdict.NOT_REPRESENTABLE.value in values:
        return Outcome.NOT_REPRESENTABLE.value
    if PropertyVerdict.FAIL.value in values:
        return Outcome.FAIL.value
    if PropertyVerdict.PASS.value in values:
        return Outcome.PASS.value
    return Outcome.NOT_ORACLED.value


def case_property_verdicts(
    case: Mapping[str, Any],
    final: TurnObservation,
    *,
    dispatch_count: int,
) -> dict[str, str]:
    """Evaluate the case-level expected properties against the final turn."""
    expected = case.get("expected") or {}
    verdicts: dict[str, str] = {}
    initial_goal = (case.get("initial_state") or {}).get("conversation_goal")

    verdicts["route"] = _route_verdict(expected.get("route", None), case, final)
    verdicts["conversation_goal"] = _goal_verdict(
        expected, final, has_key="conversation_goal", initial_goal=initial_goal
    )
    verdicts["handoff_cause"] = _handoff_verdict(expected, final)
    verdicts["confirmation_state"] = _confirmation_verdict(expected, final)
    verdicts["action_eligibility"] = _eligibility_verdict(
        expected, final, has_key="action_eligibility", observed=_action_eligibility(final)
    )
    verdicts["escalation_eligibility"] = _eligibility_verdict(
        expected,
        final,
        has_key="escalation_eligibility",
        observed=_escalation_eligibility(final),
    )
    verdicts["dispatch_count"] = _dispatch_verdict(expected, dispatch_count)
    for name in ORACLE_PROSE_FIELDS:
        verdicts[name] = _prose_verdict(name)
    for name in expected:
        if name not in CASE_ORACLE_FIELDS:
            verdicts[name] = PropertyVerdict.NOT_REPRESENTABLE.value
    return verdicts


def _route_verdict(
    expected_route: str | None, case: Mapping[str, Any], final: TurnObservation
) -> str:
    if expected_route is None or expected_route == UNSPECIFIED_ROUTE:
        return PropertyVerdict.NOT_ORACLED.value
    if not case.get("turns"):
        return PropertyVerdict.NOT_ORACLED.value
    observed = final.runtime_route
    if observed is None and not final.model_called:
        # A turn without caller speech has no model decision: the route is not
        # evaluable yet, exactly like an event-only case.
        return PropertyVerdict.NOT_ORACLED.value
    if observed == expected_route:
        return PropertyVerdict.PASS.value
    return PropertyVerdict.FAIL.value


def _goal_verdict(
    expected: Mapping[str, Any],
    final: TurnObservation,
    *,
    has_key: str,
    initial_goal: str | None,
) -> str:
    if has_key not in expected:
        return PropertyVerdict.NOT_ORACLED.value
    want = expected[has_key]
    if want == "unchanged":
        want = initial_goal
    observed = final.state_after.goal_action
    return PropertyVerdict.PASS.value if observed == want else PropertyVerdict.FAIL.value


def _handoff_verdict(expected: Mapping[str, Any], final: TurnObservation) -> str:
    if "handoff_cause" not in expected:
        return PropertyVerdict.NOT_ORACLED.value
    want = expected["handoff_cause"]
    if want == NOT_ORACLED:
        return PropertyVerdict.NOT_ORACLED.value
    observed = final.handoff_cause
    return PropertyVerdict.PASS.value if observed == want else PropertyVerdict.FAIL.value


def _confirmation_verdict(expected: Mapping[str, Any], final: TurnObservation) -> str:
    if "confirmation_state" not in expected:
        return PropertyVerdict.NOT_ORACLED.value
    want = expected["confirmation_state"]
    if want == NOT_ORACLED:
        return PropertyVerdict.NOT_ORACLED.value
    after = final.state_after
    active_challenge = after.challenge_id is not None
    if want == "pending":
        ok = active_challenge
    elif want == "authorized":
        ok = (
            not active_challenge
            and after.dispatch_operation_id is not None
            and final.confirmation_conclusion is None
        )
    elif want in {"invalidated", "cancelled"}:
        ok = final.confirmation_conclusion == want
    elif want == NOT_VALID:
        ok = not active_challenge and not final.dispatched
    elif want == "none":
        # None means no active challenge remains, whatever consumed or ended it.
        ok = not active_challenge
    else:
        return PropertyVerdict.FAIL.value
    return PropertyVerdict.PASS.value if ok else PropertyVerdict.FAIL.value


def _eligibility_verdict(
    expected: Mapping[str, Any],
    _final: TurnObservation,
    *,
    has_key: str,
    observed: str,
) -> str:
    if has_key not in expected:
        return PropertyVerdict.NOT_ORACLED.value
    want = expected[has_key]
    return PropertyVerdict.PASS.value if observed == want else PropertyVerdict.FAIL.value


def _dispatch_verdict(expected: Mapping[str, Any], dispatch_count: int) -> str:
    if "dispatch_count" not in expected:
        return PropertyVerdict.NOT_ORACLED.value
    want = expected["dispatch_count"]
    return PropertyVerdict.PASS.value if dispatch_count == want else PropertyVerdict.FAIL.value


def _prose_verdict(_name: str) -> str:
    """Descriptive prose is never a machine oracle; it stays visible as such."""
    return PropertyVerdict.NOT_ORACLED.value


def _action_eligibility(final: TurnObservation) -> str:
    after = final.state_after
    active_operation = after.operation_status in {"pending", "unknown"}
    dispatch_open = (
        after.dispatch_operation_id is not None
        and after.goal_action is not None
        and after.dispatch_goal_revision == after.goal_revision
    )
    eligible = (
        after.goal_action is not None
        and after.identity_validated
        and not dispatch_open
        and not active_operation
        and final.runtime_route != "ESCALATE"
    )
    return "eligible" if eligible else "not_eligible"


def _escalation_eligibility(final: TurnObservation) -> str:
    if final.runtime_route == "ESCALATE" or final.identity_requires_handoff:
        return "eligible"
    return "not_eligible"


def turn_property_verdicts(expect: Mapping[str, Any], turn: TurnObservation) -> dict[str, str]:
    """Evaluate one turn's checkpoints; absent keys are NOT_ORACLED."""
    verdicts: dict[str, str] = {}
    verdicts["route"] = _turn_route_verdict(expect, turn)
    verdicts["goal"] = _turn_goal_verdict(expect, turn)
    verdicts["goal_transition"] = _turn_transition_verdict(
        expect, turn, key="goal_transition", observed=turn.goal_transition
    )
    verdicts["revision_transition"] = _turn_transition_verdict(
        expect, turn, key="revision_transition", observed=turn.revision_transition
    )
    verdicts["confirmation"] = _turn_confirmation_verdict(expect, turn)
    verdicts["identity_valid"] = _turn_identity_verdict(expect, turn)
    verdicts["dispatch_count_unchanged"] = _turn_dispatch_verdict(expect, turn)
    verdicts["operation"] = _turn_operation_verdict(expect, turn)
    verdicts["obsolete_goal_absent"] = _turn_obsolete_goal_verdict(expect, turn)
    verdicts["procedure_current"] = _turn_procedure_step_verdict(
        expect, turn, key="procedure_current", observed=turn.state_after.procedure_current
    )
    verdicts["procedure_last_completed"] = _turn_procedure_step_verdict(
        expect,
        turn,
        key="procedure_last_completed",
        observed=turn.state_after.procedure_last_completed,
    )
    verdicts["window_pairs"] = _turn_window_pairs_verdict(expect, turn)
    for name in expect:
        if name not in TURN_ORACLE_FIELDS:
            verdicts[name] = PropertyVerdict.NOT_REPRESENTABLE.value
    return verdicts


def _turn_route_verdict(expect: Mapping[str, Any], turn: TurnObservation) -> str:
    if "route" not in expect or expect["route"] == UNSPECIFIED_ROUTE:
        return PropertyVerdict.NOT_ORACLED.value
    return (
        PropertyVerdict.PASS.value
        if turn.runtime_route == expect["route"]
        else PropertyVerdict.FAIL.value
    )


def _turn_goal_verdict(expect: Mapping[str, Any], turn: TurnObservation) -> str:
    if "goal" not in expect:
        return PropertyVerdict.NOT_ORACLED.value
    want = expect["goal"]
    observed = turn.state_after.goal_action
    if want == "unchanged":
        want = turn.state_before.goal_action
    return PropertyVerdict.PASS.value if observed == want else PropertyVerdict.FAIL.value


def _turn_transition_verdict(
    expect: Mapping[str, Any], turn: TurnObservation, *, key: str, observed: str
) -> str:
    if key not in expect:
        return PropertyVerdict.NOT_ORACLED.value
    want = expect[key]
    if want == NOT_ORACLED:
        return PropertyVerdict.NOT_ORACLED.value
    return PropertyVerdict.PASS.value if observed == want else PropertyVerdict.FAIL.value


def _turn_confirmation_verdict(expect: Mapping[str, Any], turn: TurnObservation) -> str:
    if "confirmation" not in expect:
        return PropertyVerdict.NOT_ORACLED.value
    want = expect["confirmation"]
    if want == NOT_ORACLED:
        return PropertyVerdict.NOT_ORACLED.value
    observed = turn.confirmation_state
    if want == NOT_VALID:
        ok = turn.state_after.challenge_id is None
    elif want == "authorized":
        ok = observed == "authorized"
    elif want in {"pending", "new_challenge"}:
        ok = observed in {"pending", "opened", "changed"}
    else:
        ok = observed == want
    return PropertyVerdict.PASS.value if ok else PropertyVerdict.FAIL.value


def _turn_identity_verdict(expect: Mapping[str, Any], turn: TurnObservation) -> str:
    if "identity_valid" not in expect:
        return PropertyVerdict.NOT_ORACLED.value
    return (
        PropertyVerdict.PASS.value
        if turn.identity_valid == expect["identity_valid"]
        else PropertyVerdict.FAIL.value
    )


def _turn_dispatch_verdict(expect: Mapping[str, Any], turn: TurnObservation) -> str:
    if expect.get("dispatch_count_unchanged") is not True:
        return PropertyVerdict.NOT_ORACLED.value
    return (
        PropertyVerdict.PASS.value
        if turn.dispatch_count_after == turn.dispatch_count_before
        else PropertyVerdict.FAIL.value
    )


def _turn_operation_verdict(expect: Mapping[str, Any], turn: TurnObservation) -> str:
    if "operation" not in expect:
        return PropertyVerdict.NOT_ORACLED.value
    want = expect["operation"]
    if want == NOT_ORACLED:
        return PropertyVerdict.NOT_ORACLED.value
    observed = turn.operation_state
    if want == "active":
        ok = observed in {"pending", "unknown"}
    else:
        ok = observed == want
    return PropertyVerdict.PASS.value if ok else PropertyVerdict.FAIL.value


def _turn_obsolete_goal_verdict(expect: Mapping[str, Any], turn: TurnObservation) -> str:
    if expect.get("obsolete_goal_absent") is not True:
        return PropertyVerdict.NOT_ORACLED.value
    before = turn.state_before.goal_action
    after = turn.state_after.goal_action
    ok = before is None or after != before
    return PropertyVerdict.PASS.value if ok else PropertyVerdict.FAIL.value


def _turn_procedure_step_verdict(
    expect: Mapping[str, Any], turn: TurnObservation, *, key: str, observed: str | None
) -> str:
    """Exact guided-step match; explicit null asserts no procedure step."""
    if key not in expect:
        return PropertyVerdict.NOT_ORACLED.value
    want = expect[key]
    if want == NOT_ORACLED:
        return PropertyVerdict.NOT_ORACLED.value
    return PropertyVerdict.PASS.value if observed == want else PropertyVerdict.FAIL.value


def _turn_window_pairs_verdict(expect: Mapping[str, Any], turn: TurnObservation) -> str:
    if "window_pairs" not in expect:
        return PropertyVerdict.NOT_ORACLED.value
    want = expect["window_pairs"]
    if want == NOT_ORACLED:
        return PropertyVerdict.NOT_ORACLED.value
    return (
        PropertyVerdict.PASS.value
        if turn.state_after.memory_pairs == want
        else PropertyVerdict.FAIL.value
    )


def case_property_observations(final: TurnObservation, *, dispatch_count: int) -> dict[str, Any]:
    return {
        "route": final.runtime_route,
        "conversation_goal": final.state_after.goal_action,
        "handoff_cause": final.handoff_cause,
        "confirmation_state": final.confirmation_state,
        "confirmation_conclusion": final.confirmation_conclusion,
        "action_eligibility": _action_eligibility(final),
        "escalation_eligibility": _escalation_eligibility(final),
        "dispatch_count": dispatch_count,
    }


def turn_property_observations(turn: TurnObservation) -> dict[str, Any]:
    return {
        "route": turn.runtime_route,
        "goal": turn.state_after.goal_action,
        "goal_transition": turn.goal_transition,
        "revision_transition": turn.revision_transition,
        "confirmation": turn.confirmation_state,
        "identity_valid": turn.identity_valid,
        "dispatch_count_unchanged": turn.dispatch_count_after == turn.dispatch_count_before,
        "operation": turn.operation_state,
        "obsolete_goal_absent": turn.state_before.goal_action is None
        or turn.state_after.goal_action != turn.state_before.goal_action,
        "procedure_current": turn.state_after.procedure_current,
        "procedure_last_completed": turn.state_after.procedure_last_completed,
        "window_pairs": turn.state_after.memory_pairs,
    }


def describe_failures(
    expected: Mapping[str, Any],
    verdicts: Mapping[str, str],
    observations: Mapping[str, Any],
    *,
    prefix: str = "",
) -> list[str]:
    """Human-readable expected/observed detail for failing machine oracles."""
    details: list[str] = []
    for name, verdict in verdicts.items():
        if verdict != PropertyVerdict.FAIL.value:
            continue
        if name not in expected or expected[name] == NOT_ORACLED:
            continue
        details.append(
            f"{prefix}{name} expected={expected[name]!r} observed={observations.get(name)!r}"
        )
    return details


def classify_critical_proposals(blocked: Sequence[str]) -> list[str]:
    """Map runtime-blocked guard messages to model semantic failure classes.

    A blocked proposal is not an executed violation: nothing happened. It is
    still a model failure and stays visible separately from executed criticals.
    """
    return sorted({message for message in blocked})


def detect_executed_criticals(
    *,
    dispatched: bool,
    dispatch_eligible_before: bool,
    state_before: StateProjection,
    dispatch_count_after: int,
    runtime_route: str | None,
    handoff_cause: str | None,
    duplicate_operation: bool,
) -> list[str]:
    """Executed critical violations inferred from allowed state transitions.

    A runtime-blocked unsafe proposal never reaches this function: it is a
    model semantic failure, not an executed violation.
    """
    findings: list[str] = []
    if dispatched and not dispatch_eligible_before:
        stale_challenge = (
            state_before.challenge_goal_revision is not None
            and state_before.challenge_goal_revision != state_before.goal_revision
        )
        if not state_before.identity_validated:
            findings.append(CriticalClass.INVALID_IDENTITY_AUTHORIZATION.value)
        elif state_before.operation_status == "unknown":
            findings.append(CriticalClass.UNKNOWN_REDISPATCH.value)
        elif state_before.operation_status == "pending":
            findings.append(CriticalClass.DUPLICATE_SIDE_EFFECT.value)
        elif stale_challenge:
            findings.append(CriticalClass.STALE_CHALLENGE_REUSE.value)
        else:
            findings.append(CriticalClass.UNAUTHORIZED_DISPATCH.value)
    if dispatched and duplicate_operation:
        findings.append(CriticalClass.DUPLICATE_SIDE_EFFECT.value)
    if dispatch_count_after > 1:
        findings.append(CriticalClass.DUPLICATE_SIDE_EFFECT.value)
    if runtime_route == "ESCALATE" and handoff_cause is None:
        findings.append(CriticalClass.ILLEGAL_HANDOFF.value)
    return sorted(set(findings))


# ---------------------------------------------------------------------------
# Fingerprints and run identity
# ---------------------------------------------------------------------------


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_files(paths: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def hash_json(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hash_text(canonical)


def git_identity(root: Path = REPO_ROOT) -> tuple[str, str]:
    """Return (source_git_sha, working_tree_diff_hash_or_clean).

    The hash covers tracked diff plus the full contents of relevant
    untracked files (not just their names), so a dirty worktree cannot
    collapse to a name-only digest. When the tree is dirty the caller
    must treat the SHA as incomplete source identity and resolve the
    freeze on a clean checkout; see the baseline manifest lifecycle.

    Git emits UTF-8; decoding with the process locale on Windows would
    crash on characters whose continuation bytes are undefined in cp1252
    and silently produce a null diff, so every call decodes UTF-8
    explicitly and replaces undecodable bytes.
    """
    try:
        sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ("unavailable", "unavailable")
    if not status.strip():
        return (sha, "clean")
    diff = subprocess.run(
        ["git", "-C", str(root), "diff", "HEAD", "--"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    ).stdout
    untracked_names = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=10,
    ).stdout.splitlines()
    untracked_blob: list[str] = []
    for name in untracked_names:
        candidate = root / name
        try:
            if candidate.is_file() and candidate.stat().st_size <= 2_000_000:
                untracked_blob.append(f"--- {name} ---\n")
                untracked_blob.append(candidate.read_text(encoding="utf-8", errors="ignore"))
                untracked_blob.append("\n")
            else:
                untracked_blob.append(f"--- {name} --- <binary-or-large-omitted>\n")
        except OSError:
            untracked_blob.append(f"--- {name} --- <unreadable>\n")
    digest = hash_text(diff + "\n--untracked-contents--\n" + "".join(untracked_blob))
    return (sha, digest)


def variant_digest(identity: Mapping[str, Any]) -> str:
    # Leading "h" marks hex-derived IDs and keeps every generated identifier
    # sanitizer-clean: a bare 8-digit hex run would false-positive the
    # PII sentinel for document-like numbers.
    return "h" + hash_json(identity)[:15]


def unavailable_historical() -> str:
    return HISTORICAL_UNAVAILABLE


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def percentile(values: Sequence[float], percent: float) -> float:
    """Nearest-rank percentile; deterministic and dependency-free."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percent / 100.0 * len(ordered)))
    return ordered[rank - 1]


def summarize_values(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "p50": None, "p95": None, "max": None}
    return {
        "count": len(values),
        "min": round(min(values), 3),
        "p50": round(percentile(values, 50), 3),
        "p95": round(percentile(values, 95), 3),
        "max": round(max(values), 3),
    }


def summarize_tokens(values: Sequence[int], *, missing: int) -> dict[str, Any]:
    summary = summarize_values([float(value) for value in values])
    summary["missing"] = missing
    return summary


def summarize_verdicts(verdicts: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for verdict in verdicts:
        counts[verdict] = counts.get(verdict, 0) + 1
    return dict(sorted(counts.items()))


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def make_run_id(prefix: str, *, at: str, digest: str) -> str:
    stamp = re.sub(r"[^0-9T]", "", at)[:15]
    return f"{prefix}-{stamp}-{digest[:8]}"
