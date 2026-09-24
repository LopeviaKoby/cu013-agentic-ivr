"""CU013 conversation evaluation runner (real model, manual, outside CI).

Replays the versioned corpus (`evals/conversation/cases.yaml`) against the
real `GeminiTurnModel` and the deterministic runtime (ADR-0010), then records
sanitized structured evidence at run, case/repetition and turn level.

Rules materialized here:

- `independent_trial` paraphrases each start from the same fresh initial state;
  `sequence` cases carry state turn-to-turn and may assert per-turn checkpoints;
- a null expected value asserts absence; an absent oracle key is NOT_ORACLED;
- `state_delta`, `allowed_claims` and `forbidden_claims` are never machine
  oracles: claims and prose belong to the manual spoken-quality review;
- repetitions are classified individually: INFRA is infrastructure, invalid
  structured model output is a model failure, and a focused rerun never erases
  the original full-corpus evidence;
- retained evidence contains IDs and allowlisted state projections only, never
  transcripts, messages, raw DTMF or document identity;
- missing token usage is recorded as missing (null), never 0.

Usage:
    python evals/conversation_eval.py [--families fam1,fam2] [--repetitions 3]
    python evals/conversation_eval.py --validate-only
    python evals/conversation_eval.py --scope focused --focused-reason "..."
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from google.genai import Client
from google.genai.types import HttpOptions

from app.conversation import gemini as gemini_module
from app.conversation.errors import (
    InvalidModelOutputError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.conversation.gemini import (
    GeminiBaseline,
    GeminiTurnModel,
    response_schema_for,
)
from app.conversation.prompt_loader import (
    PromptBundleError,
    load_prompt_bundle,
    normalize_prompt_text,
)
from app.conversation.prompt_renderer import (
    PROMPT_COMPOSITION_NONE,
    PROMPT_COMPOSITION_PROTOCOLS,
    PROMPT_COMPOSITION_SINGLE_BASELINE,
    PromptBundle,
    PromptSource,
    StaticPrompt,
    hash_prompt_text,
)
from app.session.memory import (
    DEFAULT_PROMPT_POLICY,
    GUIDED_PROCEDURE_ID,
    GUIDED_STEPS,
    MEMORY_VARIANTS,
    NO_RECENT_MEMORY,
    PROCEDURE_PROGRESS_ONLY,
    PROMPT_POLICIES,
    RECENT_CONVERSATION_MEMORY,
    SESSION_BYTES_GUARD,
    ExperimentalMemoryConfig,
    ExperimentalProcedureState,
    ExperimentalTurnPair,
    memory_variant_identity,
    render_memory_block,
    session_document_bytes,
    window_bytes,
)
from app.session.metrics import RecordingTurnMetrics
from app.session.outcome import legacy_route_value
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
    session_record_to_document,
)
from app.session.repository import SessionRepository
from app.session.service import TurnService, consolidate
from app.session.turns import (
    ConfirmationEvent,
    ConfirmationObservation,
    ExternalEvent,
    ExternalEventKind,
    IdentityOutcome,
    ModelTurnDecision,
    Route,
    TurnInput,
    TurnOutcomeState,
    advance_turn,
    build_turn_graph,
    initial_graph_state,
)
from evals.conversation_lab import (
    CASE_ORACLE_FIELDS,
    DEFAULT_REPETITIONS,
    DEFAULT_RESULTS_DIR,
    DEFAULT_WARMUPS,
    LAB_SCHEMA_VERSION,
    MODEL_REVISION_UNAVAILABLE,
    REPO_ROOT,
    RUN_ARTIFACT_KIND,
    TOOLS_NONE,
    Outcome,
    PropertyVerdict,
    RepetitionObservation,
    RepetitionStatus,
    StateProjection,
    TrialKind,
    TurnObservation,
    case_property_observations,
    case_property_verdicts,
    classify_verdicts,
    corpus_digest,
    describe_failures,
    detect_executed_criticals,
    git_identity,
    hash_file,
    hash_files,
    hash_json,
    hash_text,
    iter_trials,
    load_corpus,
    make_run_id,
    sanitization_findings,
    summarize_tokens,
    summarize_values,
    summarize_verdicts,
    trial_kind,
    turn_events,
    turn_property_observations,
    turn_property_verdicts,
    utc_now,
    validate_corpus,
    variant_digest,
)

OPERATION_ID = "operation-1"
FIXTURE_IDENTITY_BACKDATE = timedelta(minutes=1)
WARMUP_INPUT_ID = "warmup"
WARMUP_TRANSCRIPT = "hola"
ENVIRONMENT_CLASS_DEFAULT = "local_dev_host_adc"
PROMPT_VARIANT_PROTOCOLS = PROMPT_COMPOSITION_PROTOCOLS
PROMPT_VARIANT_SNAPSHOT = PROMPT_COMPOSITION_SINGLE_BASELINE
SNAPSHOT_BASELINE_PATH = REPO_ROOT / "evals/conversation/baselines/129c793-system.md"
SNAPSHOT_FIXTURE_MARKER = "EVALUATION FIXTURE — NOT PRODUCT DOCUMENTATION"
SNAPSHOT_HEADER_TERMINATOR = "-->"
TOKEN_BREAKDOWN_METHOD = "provider count_tokens after the timed replay; numbers only, never text"
TOKEN_SAMPLE_TRANSCRIPT = "necesito restablecer mi contrasena"
TOKEN_SAMPLE_CALLER = "no puedo acceder a mi cuenta"
TOKEN_SAMPLE_ASSISTANT = "¿Quieres restablecerla o desbloquearla?"
PROMPT_RENDERER_FILE = Path("app/conversation/prompt_renderer.py")
PROMPT_LOADER_FILE = Path("app/conversation/prompt_loader.py")
RUNTIME_SEMANTIC_FILES = (
    Path("app/session/turns.py"),
    Path("app/session/service.py"),
    Path("app/session/record.py"),
)
FAIL_LIKE = {
    Outcome.FAIL.value,
    Outcome.MODEL_FAILURE.value,
    Outcome.NOT_REPRESENTABLE.value,
}


# ---------------------------------------------------------------------------
# Corpus fixture mapping
# ---------------------------------------------------------------------------


def build_initial_record(case: dict[str, Any], now: datetime) -> SessionRecord:
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


def build_turn_input(events: list[dict[str, Any]], transcript: str | None) -> TurnInput:
    values: dict[str, Any] = {"transcript": transcript if transcript else None}
    if events:
        event = events[0]
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
        # goal_revision is represented by the fixture pair (goal_revision vs
        # confirmation_goal_revision): nothing to replay.
    return TurnInput.model_validate(values)


# ---------------------------------------------------------------------------
# State projection and measurement helpers
# ---------------------------------------------------------------------------


def project_record(record: SessionRecord, now: datetime) -> StateProjection:
    goal = record.goal
    identity = record.identity
    challenge = record.confirmation
    dispatch = record.dispatch
    operation = record.external_operation
    procedure = record.experimental_procedure
    window = record.experimental_window
    return StateProjection(
        goal_action=goal.action.value if goal else None,
        goal_revision=goal.revision if goal else None,
        identity_validated=identity.is_valid_at(now),
        identity_validated_at=identity.validated_at.isoformat() if identity.validated_at else None,
        identity_expires_at=(
            identity.expires_at().isoformat() if identity.expires_at() is not None else None
        ),
        identity_caller_failures=identity.caller_failures,
        challenge_id=challenge.challenge_id if challenge else None,
        challenge_action=challenge.action.value if challenge else None,
        challenge_goal_revision=challenge.goal_revision if challenge else None,
        challenge_identity_validated_at=(
            challenge.identity_validated_at.isoformat() if challenge else None
        ),
        dispatch_operation_id=dispatch.operation_id if dispatch else None,
        dispatch_goal_revision=dispatch.goal_revision if dispatch else None,
        dispatch_challenge_id=dispatch.challenge_id if dispatch else None,
        operation_id=operation.operation_id if operation else None,
        operation_action=operation.action.value if operation else None,
        operation_status=operation.status.value if operation else None,
        operation_delivery=(
            operation.delivery.value if operation and operation.delivery is not None else None
        ),
        procedure_id=procedure.procedure_id if procedure else None,
        procedure_current=procedure.current_step if procedure else None,
        procedure_last_completed=(procedure.last_completed_step if procedure else None),
        procedure_goal_revision=procedure.goal_revision if procedure else None,
        procedure_suspended=record.experimental_suspended is not None,
        memory_pairs=len(window),
        memory_bytes=window_bytes(window),
        memory_omitted=sum(1 for pair in window if pair.omitted),
    )


def dispatch_eligible(state: StateProjection) -> bool:
    if not state.identity_validated or state.goal_action is None:
        return False
    if state.challenge_id is None:
        return False
    if state.challenge_action != state.goal_action:
        return False
    if state.challenge_goal_revision != state.goal_revision:
        return False
    if state.challenge_identity_validated_at != state.identity_validated_at:
        return False
    if state.dispatch_challenge_id == state.challenge_id:
        return False
    return state.operation_status not in {"pending", "unknown"}


def goal_transition(before: StateProjection, after: StateProjection) -> str:
    """Goal lifecycle: a revision bump on the same action stays `retained`."""
    if before.goal_action is None and after.goal_action is None:
        return "absent"
    if before.goal_action is None:
        return "created"
    if after.goal_action is None:
        return "cleared"
    if before.goal_action == after.goal_action:
        return "retained"
    return "changed"


def revision_transition(before: StateProjection, after: StateProjection) -> str:
    if before.goal_revision is None and after.goal_revision is None:
        return "none"
    if before.goal_revision is None:
        return "created"
    if after.goal_revision is None:
        return "cleared"
    if after.goal_revision == before.goal_revision:
        return "same"
    return "incremented"


def confirmation_transition(
    before: StateProjection,
    after: StateProjection,
    *,
    dispatched: bool,
    observation: ConfirmationObservation | None,
) -> tuple[str, str | None]:
    if after.challenge_id is not None:
        if before.challenge_id is None:
            return ("opened", None)
        if before.challenge_id == after.challenge_id:
            return ("pending", None)
        # A replacement still ends the previous challenge: keep both facts.
        conclusion = (
            "cancelled"
            if observation in {ConfirmationObservation.NEGATIVE, ConfirmationObservation.CANCEL}
            else "invalidated"
        )
        return ("changed", conclusion)
    if before.challenge_id is None:
        return ("absent", None)
    if dispatched:
        return ("authorized", None)
    if observation in {ConfirmationObservation.NEGATIVE, ConfirmationObservation.CANCEL}:
        return ("cancelled", "cancelled")
    return ("invalidated", "invalidated")


def handoff_cause_of(runtime_route: str | None, decision: ModelTurnDecision | None) -> str | None:
    if runtime_route != Route.ESCALATE.value:
        return None
    if decision is not None and decision.handoff_cause is not None:
        return decision.handoff_cause.value
    return "TERMINAL_FAILURE"


def _drain_usage(
    metrics: RecordingTurnMetrics,
) -> tuple[int | None, int | None, int | None, bool]:
    """Read this call's counters; absent usage stays missing, never zero.

    The emission flag is True when the raw JSON carried the procedure cue
    and False when the NONE default filled it (or no counter was recorded).
    Callers map it to None when the turn made no model call at all.
    """
    prompt: int | None = None
    completion: int | None = None
    reasoning: int | None = None
    emitted = False
    for name, value in metrics.drain_counters():
        if name == "prompt_tokens":
            prompt = (prompt or 0) + value
        elif name == "completion_tokens":
            completion = (completion or 0) + value
        elif name == "reasoning_tokens":
            reasoning = (reasoning or 0) + value
        elif name == "procedure_observation_emitted":
            emitted = True
    return prompt, completion, reasoning, emitted


def _drain_segment(metrics: RecordingTurnMetrics, name: str) -> float | None:
    """Last recorded value of one segment in this turn, if any."""
    value: float | None = None
    for segment_name, duration in metrics.drain_segments():
        if segment_name == name:
            value = duration
    return value


def _observe_turn(
    *,
    turn_position: int,
    trial_id: str,
    events: list[dict[str, Any]],
    turn_input: TurnInput,
    decision: ModelTurnDecision | None,
    outcome: TurnOutcomeState | None,
    blocked: list[str],
    model_latency_ms: float | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    reasoning_tokens: int | None,
    procedure_observation_emitted: bool | None,
    runtime_semantic_ms: float,
    total_turn_ms: float,
    state_before: StateProjection,
    state_after: StateProjection,
    record_after: SessionRecord,
    dispatched: bool,
    dispatch_count_before: int,
    dispatch_count_after: int,
    duplicate_operation: bool,
    eligible_before: bool,
    session_bytes: int | None,
    session_bytes_over_guard: bool,
    memory_encode_ms: float | None,
    memory_decode_ms: float | None,
    memory_render_ms: float | None,
) -> TurnObservation:
    # The corpus oracles use the legacy route vocabulary; the domain outcome
    # speaks NextStep and this projection is the single mapping between them.
    runtime_route = legacy_route_value(outcome.next_step) if outcome is not None else None
    confirmation_state, conclusion = confirmation_transition(
        state_before,
        state_after,
        dispatched=dispatched,
        observation=decision.confirmation_observation if decision else None,
    )
    handoff = handoff_cause_of(runtime_route, decision)
    critical = detect_executed_criticals(
        dispatched=dispatched,
        dispatch_eligible_before=eligible_before,
        state_before=state_before,
        dispatch_count_after=dispatch_count_after,
        runtime_route=runtime_route,
        handoff_cause=handoff,
        duplicate_operation=duplicate_operation,
    )
    return TurnObservation(
        turn_index=turn_position,
        input_id=(
            f"{trial_id}:turn{turn_position + 1}" if turn_input.transcript is not None else None
        ),
        event_id=(f"{trial_id}:turn{turn_position + 1}:{events[0]['event']}" if events else None),
        event_kind=str(events[0]["event"]) if events else None,
        model_called=turn_input.transcript is not None,
        proposed_route=decision.route.value if decision else None,
        proposed_goal_intent=(decision.goal.intent.value if decision and decision.goal else None),
        proposed_goal_action=(
            decision.goal.action.value
            if decision and decision.goal and decision.goal.action
            else None
        ),
        proposed_confirmation_request=(decision.confirmation_request if decision else None),
        proposed_confirmation_observation=(
            decision.confirmation_observation.value if decision else None
        ),
        proposed_handoff_cause=(
            decision.handoff_cause.value if decision and decision.handoff_cause else None
        ),
        proposed_claim_kinds=([claim.kind.value for claim in decision.claims] if decision else []),
        proposed_procedure_observation=(decision.procedure_observation.value if decision else None),
        procedure_observation_emitted=procedure_observation_emitted,
        runtime_route=runtime_route,
        goal_transition=goal_transition(state_before, state_after),
        revision_transition=revision_transition(state_before, state_after),
        confirmation_state=confirmation_state,
        confirmation_conclusion=conclusion,
        handoff_cause=handoff,
        identity_valid=state_after.identity_validated,
        identity_requires_handoff=record_after.identity.requires_handoff(),
        operation_state=state_after.operation_status or "none",
        dispatch_eligible=eligible_before,
        dispatched=dispatched,
        dispatch_count_before=dispatch_count_before,
        dispatch_count_after=dispatch_count_after,
        critical_findings=critical,
        blocked_proposals=blocked,
        state_before=state_before,
        state_after=state_after,
        model_latency_ms=model_latency_ms,
        runtime_semantic_ms=runtime_semantic_ms,
        total_turn_ms=total_turn_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
        session_bytes=session_bytes,
        session_bytes_over_guard=session_bytes_over_guard,
        memory_encode_ms=memory_encode_ms,
        memory_decode_ms=memory_decode_ms,
        memory_render_ms=memory_render_ms,
        memory_pairs=state_after.memory_pairs,
        error_class=None,
    )


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


@dataclass
class TrialReplay:
    status: str = RepetitionStatus.VALID.value
    error_class: str | None = None
    model_failure: bool = False
    turns: list[TurnObservation] = field(default_factory=list)

    @property
    def dispatch_count(self) -> int:
        return self.turns[-1].dispatch_count_after if self.turns else 0


def _selected_turns(case: dict[str, Any], turn_index: int | None) -> list[dict[str, Any]]:
    turns = list(case.get("turns") or [])
    if trial_kind(case) is TrialKind.SEQUENCE:
        return turns or [{}]
    if turn_index is None:
        return [{}]
    return [turns[turn_index]]


async def replay_trial(
    model: GeminiTurnModel,
    metrics: RecordingTurnMetrics,
    case: dict[str, Any],
    trial_id: str,
    turn_index: int | None,
    *,
    now: datetime,
    experimental: ExperimentalMemoryConfig | None = None,
) -> TrialReplay:
    """Replay one trial: one paraphrase turn or the whole intentional sequence."""
    replay = TrialReplay()
    record = build_initial_record(case, now)
    selected = _selected_turns(case, turn_index)
    known_operation_ids: set[str] = (
        {record.dispatch.operation_id} if record.dispatch is not None else set()
    )
    dispatch_count = 0
    try:
        for index, turn in enumerate(selected):
            is_last = index == len(selected) - 1
            events = turn_events(case, turn, is_last=is_last)
            transcript = turn.get("transcript")
            turn_input = build_turn_input(events, transcript)
            turn_start = time.monotonic()
            state_before = project_record(record, now)
            eligible_before = dispatch_eligible(state_before) if transcript is not None else False
            decision: ModelTurnDecision | None = None
            model_latency: float | None = None
            prompt_tokens: int | None = None
            completion_tokens: int | None = None
            reasoning_tokens: int | None = None
            emitted: bool | None = None
            render_ms: float | None = None
            memory_context: str | None = None
            if turn_input.transcript is not None:
                if experimental is not None:
                    memory_context, render_ms = render_memory_block(
                        record.experimental_window,
                        record.experimental_procedure,
                        record.experimental_suspended,
                        window_n=experimental.window_n,
                        strategy=experimental.strategy,
                    )
                procedure = record.experimental_procedure
                model_start = time.monotonic()
                decision = await model.decide(
                    transcript=turn_input.transcript,
                    goal=record.goal,
                    identity_validated=record.identity_is_valid(now),
                    confirmation=record.confirmation,
                    external_operation=record.external_operation,
                    memory_context=memory_context,
                    procedure_current=(procedure.current_step if procedure is not None else None),
                )
                model_latency = (time.monotonic() - model_start) * 1000.0
                prompt_tokens, completion_tokens, reasoning_tokens, emitted_flag = _drain_usage(
                    metrics
                )
                emitted = emitted_flag
            runtime_start = time.monotonic()
            state = initial_graph_state(record, turn_input, now=now, experimental=experimental)
            state["model_decision"] = decision
            if state["memory_render_ms"] is None:
                state["memory_render_ms"] = render_ms
            delta = advance_turn(state)
            record = consolidate(record, delta, now=now)
            runtime_latency = (time.monotonic() - runtime_start) * 1000.0
            total_latency = (time.monotonic() - turn_start) * 1000.0
            state_after = project_record(record, now)

            outcome = delta["outcome"]
            blocked = list(outcome.violations) if outcome is not None else []
            dispatched = False
            if record.dispatch is not None:
                operation_id = record.dispatch.operation_id
                if operation_id not in known_operation_ids:
                    known_operation_ids.add(operation_id)
                    dispatch_count += 1
                    dispatched = True
            duplicate_operation = dispatched and state_before.operation_status in {
                "pending",
                "unknown",
            }
            document = session_record_to_document(record)
            session_bytes = session_document_bytes(document)
            replay.turns.append(
                _observe_turn(
                    turn_position=len(replay.turns),
                    trial_id=trial_id,
                    events=events,
                    turn_input=turn_input,
                    decision=decision,
                    outcome=outcome,
                    blocked=blocked,
                    model_latency_ms=model_latency,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    reasoning_tokens=reasoning_tokens,
                    procedure_observation_emitted=emitted,
                    runtime_semantic_ms=runtime_latency,
                    total_turn_ms=total_latency,
                    state_before=state_before,
                    state_after=state_after,
                    record_after=record,
                    dispatched=dispatched,
                    dispatch_count_before=dispatch_count - (1 if dispatched else 0),
                    dispatch_count_after=dispatch_count,
                    duplicate_operation=duplicate_operation,
                    eligible_before=eligible_before,
                    session_bytes=session_bytes,
                    session_bytes_over_guard=session_bytes > SESSION_BYTES_GUARD,
                    memory_encode_ms=delta["memory_encode_ms"],
                    memory_decode_ms=state["memory_decode_ms"],
                    memory_render_ms=state["memory_render_ms"],
                )
            )
    except (ModelTimeoutError, ModelUnavailableError) as exc:
        replay.status = RepetitionStatus.INFRA.value
        replay.error_class = type(exc).__name__
    except InvalidModelOutputError as exc:
        replay.model_failure = True
        replay.error_class = type(exc).__name__
    return replay


class _LaneStore:
    """Deterministic in-memory document seam for the repository replay lane."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, object]] = {}
        self.reads = 0
        self.writes = 0

    async def read(self, conversation_id: str) -> Mapping[str, object] | None:
        self.reads += 1
        document = self.documents.get(conversation_id)
        return dict(document) if document is not None else None

    async def write(self, conversation_id: str, document: Mapping[str, object]) -> None:
        self.writes += 1
        self.documents[conversation_id] = dict(document)


async def replay_trial_repository(
    model: GeminiTurnModel,
    metrics: RecordingTurnMetrics,
    case: dict[str, Any],
    trial_id: str,
    turn_index: int | None,
    *,
    now: datetime,
    experimental: ExperimentalMemoryConfig | None = None,
) -> TrialReplay:
    """Replay one trial through TurnService + repository (save/reload/restart).

    The service (and its graph) is recreated for every turn over the same
    store, so each turn proves restart continuity from the durable record.
    Oracle, sanitizer and INFRA-versus-FAIL semantics match the direct lane.
    """
    from app.session.repository import SessionPersistenceError

    replay = TrialReplay()
    store = _LaneStore()
    repository = SessionRepository(store)
    record = build_initial_record(case, now)
    # Seed under the trial's conversation id: paraphrase trials replay under
    # "<case>#t<N>", so seeding under the bare case id would start every
    # independent trial from a blank record instead of the fixture state.
    record = record.model_copy(update={"conversation_id": trial_id})
    await repository.save(record)
    selected = _selected_turns(case, turn_index)
    known_operation_ids: set[str] = (
        {record.dispatch.operation_id} if record.dispatch is not None else set()
    )
    dispatch_count = 0
    try:
        for index, turn in enumerate(selected):
            is_last = index == len(selected) - 1
            events = turn_events(case, turn, is_last=is_last)
            transcript = turn.get("transcript")
            turn_input = build_turn_input(events, transcript)
            state_before = project_record(record, now)
            eligible_before = dispatch_eligible(state_before) if transcript is not None else False
            turn_start = time.monotonic()
            service = TurnService(
                repository,
                build_turn_graph(model),
                metrics=metrics,
                clock=lambda: now,
            )
            result = await service.handle_turn(trial_id, turn_input, experimental=experimental)
            total_latency = (time.monotonic() - turn_start) * 1000.0
            record = result.record
            decision = result.decision
            outcome = result.outcome
            model_latency = _drain_segment(metrics, "model")
            graph_ms = _drain_segment(metrics, "graph")
            _drain_segment(metrics, "session_load")
            _drain_segment(metrics, "session_save")
            prompt_tokens, completion_tokens, reasoning_tokens, emitted_flag = _drain_usage(metrics)
            runtime_latency = max((graph_ms or 0.0) - (model_latency or 0.0), 0.0)
            state_after = project_record(record, now)
            blocked = list(outcome.violations) if outcome is not None else []
            dispatched = False
            if record.dispatch is not None:
                operation_id = record.dispatch.operation_id
                if operation_id not in known_operation_ids:
                    known_operation_ids.add(operation_id)
                    dispatch_count += 1
                    dispatched = True
            duplicate_operation = dispatched and state_before.operation_status in {
                "pending",
                "unknown",
            }
            memory = result.memory
            if memory is not None:
                session_bytes_value: int | None = memory.session_bytes
                over_guard = memory.session_bytes_over_guard
                encode_ms: float | None = memory.encode_ms
                decode_ms: float | None = memory.decode_ms
                render_ms_value: float | None = memory.render_ms
            else:
                # The no-recent-memory path carries no experimental plane, but
                # the serialized session size is still baseline evidence for
                # the paired comparison.
                session_bytes_value = session_document_bytes(session_record_to_document(record))
                over_guard = session_bytes_value > SESSION_BYTES_GUARD
                encode_ms = None
                decode_ms = None
                render_ms_value = None
            replay.turns.append(
                _observe_turn(
                    turn_position=len(replay.turns),
                    trial_id=trial_id,
                    events=events,
                    turn_input=turn_input,
                    decision=decision,
                    outcome=outcome,
                    blocked=blocked,
                    model_latency_ms=model_latency,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    reasoning_tokens=reasoning_tokens,
                    procedure_observation_emitted=(
                        emitted_flag if turn_input.transcript is not None else None
                    ),
                    runtime_semantic_ms=runtime_latency,
                    total_turn_ms=total_latency,
                    state_before=state_before,
                    state_after=state_after,
                    record_after=record,
                    dispatched=dispatched,
                    dispatch_count_before=dispatch_count - (1 if dispatched else 0),
                    dispatch_count_after=dispatch_count,
                    duplicate_operation=duplicate_operation,
                    eligible_before=eligible_before,
                    session_bytes=session_bytes_value,
                    session_bytes_over_guard=over_guard,
                    memory_encode_ms=encode_ms,
                    memory_decode_ms=decode_ms,
                    memory_render_ms=render_ms_value,
                )
            )
    except (ModelTimeoutError, ModelUnavailableError, SessionPersistenceError) as exc:
        replay.status = RepetitionStatus.INFRA.value
        replay.error_class = type(exc).__name__
    except InvalidModelOutputError as exc:
        replay.model_failure = True
        replay.error_class = type(exc).__name__
    return replay


def accumulate(turns: list[TurnObservation]) -> dict[str, float | int | None]:
    def total(values: list[float]) -> float:
        return round(sum(values), 3) if values else 0.0

    model_values = [turn.model_latency_ms for turn in turns if turn.model_latency_ms is not None]
    runtime_values = [
        turn.runtime_semantic_ms for turn in turns if turn.runtime_semantic_ms is not None
    ]
    prompt = [turn.prompt_tokens for turn in turns if turn.prompt_tokens is not None]
    completion = [turn.completion_tokens for turn in turns if turn.completion_tokens is not None]
    return {
        "turns": len(turns),
        "model_calls": sum(1 for turn in turns if turn.model_called),
        "model_latency_ms": total(model_values),
        "runtime_semantic_ms": total(runtime_values),
        "total_turn_ms": total([turn.total_turn_ms for turn in turns]),
        "prompt_tokens": sum(prompt) if prompt else 0,
        "completion_tokens": sum(completion) if completion else 0,
        "missing_usage_calls": sum(
            1 for turn in turns if turn.model_called and turn.prompt_tokens is None
        ),
    }


def finalize_repetition(
    case: dict[str, Any], replay: TrialReplay, *, repetition_id: int
) -> RepetitionObservation:
    """Turn a raw replay into a repetition record with per-property verdicts."""
    if replay.status == RepetitionStatus.INFRA.value:
        return RepetitionObservation(
            repetition_id=repetition_id,
            status=replay.status,
            error_class=replay.error_class,
            classification=Outcome.INFRA.value,
            case_verdicts={},
            turn_verdicts=[],
            first_divergent_turn=None,
            goal_continuity="not_available",
            authorization_result="not_available",
            dispatch_count=replay.dispatch_count,
            critical_findings=[],
            blocked_proposals=[],
            accumulated=accumulate(replay.turns),
            failure_details=[],
            turns=replay.turns,
        )
    if not replay.turns:
        return RepetitionObservation(
            repetition_id=repetition_id,
            status=replay.status,
            error_class=replay.error_class,
            classification=Outcome.MODEL_FAILURE.value
            if replay.model_failure
            else Outcome.FAIL.value,
            case_verdicts={},
            turn_verdicts=[],
            first_divergent_turn=None,
            goal_continuity="not_available",
            authorization_result="not_available",
            dispatch_count=0,
            critical_findings=[],
            blocked_proposals=[],
            accumulated=accumulate(replay.turns),
            failure_details=[f"model failure: {replay.error_class}"] if replay.error_class else [],
            turns=replay.turns,
        )
    final = replay.turns[-1]
    case_verdicts = case_property_verdicts(case, final, dispatch_count=replay.dispatch_count)
    expected = case.get("expected") or {}
    observed = case_property_observations(final, dispatch_count=replay.dispatch_count)
    failures = describe_failures(expected, case_verdicts, observed)
    turn_verdicts: list[dict[str, str]] = []
    turn_failures: list[str] = []
    turns = list(case.get("turns") or [])
    for index, turn_observation in enumerate(replay.turns):
        turn_spec = turns[index] if index < len(turns) else {}
        expect = turn_spec.get("expect") or {}
        verdicts = turn_property_verdicts(expect, turn_observation)
        turn_verdicts.append(verdicts)
        turn_failures.extend(
            describe_failures(
                expect,
                verdicts,
                turn_property_observations(turn_observation),
                prefix=f"turn{index + 1}.",
            )
        )
    first_divergent: int | None = None
    for index, verdicts in enumerate(turn_verdicts):
        if PropertyVerdict.FAIL.value in verdicts.values():
            first_divergent = index + 1
            break
    if first_divergent is None and (failures or turn_failures):
        first_divergent = len(replay.turns)
    criticals = sorted({item for turn in replay.turns for item in turn.critical_findings})
    blocked = sorted({item for turn in replay.turns for item in turn.blocked_proposals})
    before = replay.turns[0].state_before.goal_action
    after = final.state_after.goal_action
    if before is None and after is None:
        continuity = "not_applicable"
    elif before is None:
        continuity = "created"
    elif after is None:
        continuity = "cleared"
    elif before == after:
        continuity = "retained"
    else:
        continuity = "changed"
    if replay.dispatch_count > 0:
        authorization = "dispatched"
    elif blocked:
        authorization = "blocked"
    else:
        authorization = "not_authorized"
    classification = classify_verdicts(case_verdicts, model_failure=replay.model_failure)
    if replay.model_failure:
        classification = Outcome.MODEL_FAILURE.value
    if replay.error_class and not replay.model_failure:
        failures.append(f"infra interrupted at turn {len(replay.turns)}")
    return RepetitionObservation(
        repetition_id=repetition_id,
        status=replay.status,
        error_class=replay.error_class,
        classification=classification,
        case_verdicts=case_verdicts,
        turn_verdicts=turn_verdicts,
        first_divergent_turn=first_divergent,
        goal_continuity=continuity,
        authorization_result=authorization,
        dispatch_count=replay.dispatch_count,
        critical_findings=criticals,
        blocked_proposals=blocked,
        accumulated=accumulate(replay.turns),
        failure_details=sorted(set(failures + turn_failures)),
        turns=replay.turns,
    )


# ---------------------------------------------------------------------------
# Run orchestration
# ---------------------------------------------------------------------------


@dataclass
class TrialRecord:
    case_id: str
    family: str
    trial_id: str
    scenario_kind: str
    expected: dict[str, Any]
    expected_kinds: dict[str, str]
    controls: dict[str, list[str]]
    repetitions: list[RepetitionObservation]

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for repetition in self.repetitions:
            counts[repetition.classification] = counts.get(repetition.classification, 0) + 1
        if any(repetition.classification in FAIL_LIKE for repetition in self.repetitions):
            return Outcome.FAIL.value
        if counts and set(counts) == {Outcome.INFRA.value}:
            return Outcome.INFRA.value
        if counts.get(Outcome.PASS.value):
            return Outcome.PASS.value
        return Outcome.NOT_ORACLED.value

    def to_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for repetition in self.repetitions:
            counts[repetition.classification] = counts.get(repetition.classification, 0) + 1
        return {
            "case_id": self.case_id,
            "family": self.family,
            "trial_id": self.trial_id,
            "scenario_kind": self.scenario_kind,
            "expected": dict(self.expected),
            "expected_property_kinds": dict(self.expected_kinds),
            "controls": {key: list(value) for key, value in self.controls.items()},
            "summary": {"classification": self.summary(), "verdicts": dict(sorted(counts.items()))},
            "repetitions": [repetition.to_dict() for repetition in self.repetitions],
        }


def expected_kinds(expected: dict[str, Any]) -> dict[str, str]:
    return {name: CASE_ORACLE_FIELDS[name].value for name in expected if name in CASE_ORACLE_FIELDS}


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def sequence_series(
    case: dict[str, Any], repetitions: list[RepetitionObservation]
) -> list[dict[str, Any]]:
    """Per-turn tokens/latency and their cumulative growth for sequences."""
    if trial_kind(case) is not TrialKind.SEQUENCE:
        return []
    series: list[dict[str, Any]] = []
    turn_count = max((len(repetition.turns) for repetition in repetitions), default=0)
    for index in range(turn_count):
        model_values: list[float] = []
        turn_values: list[float] = []
        prompt_values: list[int] = []
        completion_values: list[int] = []
        prompt_cumulative: list[float] = []
        completion_cumulative: list[float] = []
        model_cumulative: list[float] = []
        turn_cumulative: list[float] = []
        missing = 0
        for repetition in repetitions:
            if index >= len(repetition.turns):
                continue
            turn = repetition.turns[index]
            so_far = repetition.turns[: index + 1]
            if turn.model_latency_ms is not None:
                model_values.append(turn.model_latency_ms)
            turn_values.append(turn.total_turn_ms)
            if turn.prompt_tokens is None:
                if turn.model_called:
                    missing += 1
            else:
                prompt_values.append(turn.prompt_tokens)
            if turn.completion_tokens is not None:
                completion_values.append(turn.completion_tokens)
            prompt_cumulative.append(float(sum(t.prompt_tokens or 0 for t in so_far)))
            completion_cumulative.append(float(sum(t.completion_tokens or 0 for t in so_far)))
            model_cumulative.append(float(sum(t.model_latency_ms or 0.0 for t in so_far)))
            turn_cumulative.append(float(sum(t.total_turn_ms for t in so_far)))
        series.append(
            {
                "turn_index": index + 1,
                "model_latency_ms": summarize_values(model_values),
                "turn_total_ms": summarize_values(turn_values),
                "prompt_tokens_per_call": summarize_tokens(prompt_values, missing=missing),
                "completion_tokens_per_call": summarize_tokens(completion_values, missing=missing),
                "prompt_tokens_cumulative_mean": _mean(prompt_cumulative),
                "completion_tokens_cumulative_mean": _mean(completion_cumulative),
                "model_latency_ms_cumulative_mean": _mean(model_cumulative),
                "total_turn_ms_cumulative_mean": _mean(turn_cumulative),
            }
        )
    return series


def load_snapshot_prompt(path: Path = SNAPSHOT_BASELINE_PATH) -> StaticPrompt:
    """Load the frozen 129c793 baseline text from its labeled fixture.

    The fixture is evaluation-only and must announce itself as such; the text
    after the header comment is used byte-for-byte so the baseline identity
    hash is reproducible.
    """
    text = path.read_text(encoding="utf-8")
    header, terminator, body = text.partition(SNAPSHOT_HEADER_TERMINATOR)
    if not terminator or SNAPSHOT_FIXTURE_MARKER not in header:
        raise ValueError(f"{path} is not a labeled evaluation fixture")
    if not body.startswith("\n"):
        raise ValueError(f"{path} must separate its header from the prompt text with a newline")
    snapshot = body[1:]
    if snapshot.endswith("\n"):
        snapshot = snapshot[:-1]
    # Checkout line endings never change the frozen text: normalize to LF.
    return StaticPrompt(text=normalize_prompt_text(snapshot))


def resolve_prompt_source(prompt_variant: str) -> PromptSource:
    """The declared experimental variable: modular composition or snapshot."""
    if prompt_variant == PROMPT_VARIANT_SNAPSHOT:
        return load_snapshot_prompt()
    if prompt_variant == PROMPT_VARIANT_PROTOCOLS:
        return load_prompt_bundle()
    raise ValueError(f"unknown prompt variant {prompt_variant!r}")


def prompt_composition_identity(prompt_source: PromptSource | None) -> dict[str, Any]:
    """Fingerprint the exact prompt composition used by this run."""
    renderer_hash = hash_file(REPO_ROOT / PROMPT_RENDERER_FILE)
    loader_hash = hash_file(REPO_ROOT / PROMPT_LOADER_FILE)
    if isinstance(prompt_source, PromptBundle):
        return {
            "mode": PROMPT_COMPOSITION_PROTOCOLS,
            "module_hashes": prompt_source.module_hashes(),
            "composition_orders": prompt_source.composition_orders(),
            "system_instruction_hashes": prompt_source.instruction_hashes(),
            "protocol_projection_mode": list(prompt_source.projection_modes),
            "projected_steps": prompt_source.projected_steps(),
            "few_shot_variant": prompt_source.few_shot.name,
            "bundle_fingerprint": prompt_source.fingerprint,
            "renderer_sha256": renderer_hash,
            "loader_sha256": loader_hash,
        }
    if isinstance(prompt_source, StaticPrompt):
        return {
            "mode": PROMPT_COMPOSITION_SINGLE_BASELINE,
            "module_hashes": {},
            "composition_orders": {"base": []},
            "system_instruction_hashes": {"base": hash_prompt_text(prompt_source.text)},
            "protocol_projection_mode": ["full"],
            "projected_steps": {},
            "few_shot_variant": "none",
            "bundle_fingerprint": None,
            "renderer_sha256": renderer_hash,
            "loader_sha256": loader_hash,
        }
    return {"mode": PROMPT_COMPOSITION_NONE}


def build_variant_identity(
    baseline: GeminiBaseline | None,
    *,
    memory_variant: str = NO_RECENT_MEMORY,
    memory_n: int = 3,
    lane: str = "direct",
    strategy: str = DEFAULT_PROMPT_POLICY,
    prompt_source: PromptSource | None = None,
    cache_mode: str = "none",
) -> dict[str, Any]:
    root = REPO_ROOT
    source_sha, working_tree = git_identity(root)
    decision_schema = ModelTurnDecision.model_json_schema()
    sent_schema = response_schema_for(baseline) if baseline is not None else ModelTurnDecision
    sent_schema_json = (
        sent_schema if isinstance(sent_schema, dict) else sent_schema.model_json_schema()
    )
    response_schema = {
        "response_mime_type": "application/json",
        "response_schema": sent_schema_json,
    }
    memory_identity = memory_variant_identity(memory_variant, memory_n, strategy)
    effective_prompt = prompt_source.system_instructions(None) if prompt_source is not None else ""
    model_location = baseline.location if baseline else "unknown"
    thinking_level = baseline.thinking_level if baseline else None
    # Gemini 3 sends only thinking_level; reporting budget 0 alongside a
    # level is descriptively false, so the identity carries null instead.
    # Historic 2.5 artifacts keep their recorded budget for replay.
    thinking_budget: int | None = None
    if baseline is not None and thinking_level is None:
        thinking_budget = baseline.thinking_budget
    identity: dict[str, Any] = {
        "source_git_sha": source_sha,
        "working_tree_diff_hash": working_tree,
        "effective_prompt_hash": hash_text(effective_prompt),
        "provider": baseline.provider if baseline else "vertex_ai",
        "model_id": baseline.model if baseline else "unknown",
        "region": model_location,
        "model_location": model_location,
        "api_version": baseline.api_version if baseline else "unknown",
        "thinking_budget": thinking_budget,
        "thinking_level": thinking_level,
        "strict_procedure_observation": (
            baseline.strict_procedure_observation if baseline else False
        ),
        "response_schema_hash": hash_json(response_schema),
        "streaming": False,
        "timeout_ms": baseline.timeout_ms if baseline else None,
        "attempts": baseline.attempts if baseline else None,
        "runtime_semantic_hash": hash_files([root / path for path in RUNTIME_SEMANTIC_FILES]),
        "decision_schema_hash": hash_json(decision_schema),
        "state_projection_hash": hash_text(inspect.getsource(gemini_module._state_block)),
        "dependency_lock_hash": hash_file(root / "requirements.lock"),
        "tools": TOOLS_NONE,
        "model_revision": MODEL_REVISION_UNAVAILABLE,
        "lane": lane,
        "cache_mode": cache_mode,
        "prompt_composition": prompt_composition_identity(prompt_source),
    }
    identity.update(memory_identity)
    return identity


def build_evaluator_identity() -> dict[str, Any]:
    root = REPO_ROOT
    return {
        "runner": "evals/conversation_eval.py",
        "runner_sha256": hash_file(root / "evals/conversation_eval.py"),
        "lab": "evals/conversation_lab.py",
        "lab_sha256": hash_file(root / "evals/conversation_lab.py"),
        "comparator": "evals/conversation_compare.py",
        "comparator_sha256": hash_file(root / "evals/conversation_compare.py"),
        "critical_gate": "evals/conversation_lab.py:detect_executed_criticals",
        "schema_version": LAB_SCHEMA_VERSION,
    }


async def _count_tokens(client: Client, model: str, text: str) -> int | None:
    """Count tokens for one bucket; provider failure stays missing, never 0."""
    try:
        response = await client.aio.models.count_tokens(model=model, contents=text)
    except Exception:
        return None
    total = response.total_tokens
    return int(total) if total is not None else None


async def token_composition_breakdown(
    client: Client, baseline: GeminiBaseline, prompt_source: PromptSource
) -> dict[str, Any]:
    """Post-run token composition; never runs inside a timed turn or a call.

    It counts only numbers and stores only numbers: no module, state, memory
    or transcript text is retained. Dynamic buckets are representative
    synthetic constructions, not captured caller input.
    """
    buckets: dict[str, int] = {}
    missing: list[str] = []

    async def record(label: str, text: str) -> None:
        value = await _count_tokens(client, baseline.model, text)
        if value is None:
            missing.append(label)
        else:
            buckets[label] = value

    if isinstance(prompt_source, PromptBundle):
        await record("module:core", prompt_source.core.text)
        await record("module:catalog", prompt_source.catalog.text)
        await record(f"module:{prompt_source.few_shot.name}", prompt_source.few_shot.text)
        for protocol in prompt_source.protocols:
            await record(f"module:{protocol.name}", protocol.text)
        for instruction in prompt_source.instructions:
            await record(f"system_instruction:{instruction.key}", instruction.text)
    elif isinstance(prompt_source, StaticPrompt):
        await record("system_instruction:base", prompt_source.text)

    now = datetime.now(UTC)
    reset_goal = ConversationGoal(action=Action.RESET_PASSWORD, revision=1)
    challenge = ConfirmationChallenge(
        challenge_id="token-sample",
        action=Action.RESET_PASSWORD,
        goal_revision=1,
        identity_validated_at=now,
        issued_at=now,
    )
    operation = ExternalOperation(
        operation_id="token-sample",
        action=Action.RESET_PASSWORD,
        status=OperationStatus.PENDING,
    )
    await record("state_block:minimal", gemini_module._state_block(None, False, None, None))
    await record(
        "state_block:active_reset",
        gemini_module._state_block(reset_goal, True, challenge, operation),
    )
    procedure = ExperimentalProcedureState(
        procedure_id=GUIDED_PROCEDURE_ID,
        current_step=GUIDED_STEPS[0],
        last_completed_step=None,
        goal_revision=1,
        opened_at=now,
    )
    procedure_block, _ = render_memory_block((), procedure, None, window_n=3)
    await record("procedure_progress_block", procedure_block)
    memory_pair = ExperimentalTurnPair(
        caller_text=TOKEN_SAMPLE_CALLER,
        assistant_text=TOKEN_SAMPLE_ASSISTANT,
        sequence=1,
        goal_revision=1,
    )
    memory_block, _ = render_memory_block((memory_pair,), None, None, window_n=3)
    await record("recent_memory_block", memory_block)
    await record("transcript_sample", TOKEN_SAMPLE_TRANSCRIPT)
    return {
        "method": TOKEN_BREAKDOWN_METHOD,
        "model": baseline.model,
        "location": baseline.location,
        "buckets": dict(sorted(buckets.items())),
        "missing": sorted(missing),
    }


async def run_warmup(
    model: GeminiTurnModel, metrics: RecordingTurnMetrics, warmup_id: str
) -> dict[str, Any]:
    start = time.monotonic()
    error_class: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    try:
        await model.decide(
            transcript=WARMUP_TRANSCRIPT,
            goal=None,
            identity_validated=False,
            confirmation=None,
            external_operation=None,
        )
        prompt_tokens, completion_tokens, _, _ = _drain_usage(metrics)
    except (ModelTimeoutError, ModelUnavailableError) as exc:
        error_class = type(exc).__name__
    return {
        "warmup_id": warmup_id,
        "model_latency_ms": round((time.monotonic() - start) * 1000.0, 3),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "error_class": error_class,
        "excluded_from_verdicts": True,
    }


async def evaluate(
    model: GeminiTurnModel,
    metrics: RecordingTurnMetrics,
    cases: list[dict[str, Any]],
    repetitions: int,
    *,
    warmups: int,
    now: datetime,
    experimental: ExperimentalMemoryConfig | None = None,
    lane: str = "direct",
) -> tuple[list[TrialRecord], list[dict[str, Any]]]:
    warmup_records = [
        await run_warmup(model, metrics, f"{WARMUP_INPUT_ID}-{index + 1}")
        for index in range(warmups)
    ]
    records: list[TrialRecord] = []
    for case in cases:
        for trial_id, turn_index in iter_trials(case):
            repetitions_list: list[RepetitionObservation] = []
            for repetition_id in range(1, repetitions + 1):
                if lane == "repository":
                    replay = await replay_trial_repository(
                        model,
                        metrics,
                        case,
                        trial_id,
                        turn_index,
                        now=now,
                        experimental=experimental,
                    )
                else:
                    replay = await replay_trial(
                        model,
                        metrics,
                        case,
                        trial_id,
                        turn_index,
                        now=now,
                        experimental=experimental,
                    )
                repetitions_list.append(
                    finalize_repetition(case, replay, repetition_id=repetition_id)
                )
            records.append(
                TrialRecord(
                    case_id=case["case_id"],
                    family=case["family"],
                    trial_id=trial_id,
                    scenario_kind=trial_kind(case).value,
                    expected=dict(case.get("expected") or {}),
                    expected_kinds=expected_kinds(case.get("expected") or {}),
                    controls=dict(case.get("controls") or {}),
                    repetitions=repetitions_list,
                )
            )
    return records, warmup_records


def aggregate_run(
    records: list[TrialRecord], cases_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    repetition_verdicts: list[str] = []
    case_verdicts: dict[str, list[str]] = {}
    turn_verdicts: dict[str, list[str]] = {}
    routes: list[str] = []
    sequences: list[dict[str, Any]] = []
    for record in records:
        for repetition in record.repetitions:
            repetition_verdicts.append(repetition.classification)
            for name, verdict in repetition.case_verdicts.items():
                case_verdicts.setdefault(name, []).append(verdict)
            for verdicts in repetition.turn_verdicts:
                for name, verdict in verdicts.items():
                    turn_verdicts.setdefault(name, []).append(verdict)
            for turn in repetition.turns:
                if turn.runtime_route is not None:
                    routes.append(turn.runtime_route)
        case = cases_by_id[record.case_id]
        series = sequence_series(case, record.repetitions)
        if series:
            sequences.append({"case_id": record.case_id, "series": series})
    families: dict[str, dict[str, int]] = {}
    for record in records:
        summary = record.summary()
        families.setdefault(record.family, {})
        families[record.family][summary] = families[record.family].get(summary, 0) + 1
    return {
        "repetition_verdicts": summarize_verdicts(repetition_verdicts),
        "case_summaries": summarize_verdicts([record.summary() for record in records]),
        "case_properties": {
            name: summarize_verdicts(values) for name, values in sorted(case_verdicts.items())
        },
        "turn_properties": {
            name: summarize_verdicts(values) for name, values in sorted(turn_verdicts.items())
        },
        "route_distribution": summarize_verdicts(routes),
        "families": {
            name: dict(sorted(values.items())) for name, values in sorted(families.items())
        },
        "sequences": sequences,
    }


def build_artifact(
    records: list[TrialRecord],
    warmups: list[dict[str, Any]],
    cases_by_id: dict[str, dict[str, Any]],
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    identity: dict[str, Any],
    baseline_id: str,
    candidate_id: str,
    repetitions: int,
    warmup_count: int,
    environment_class: str,
    scope: str,
    focused_reason: str | None,
    rerun_of: str | None,
    token_composition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    valid_repetitions = sum(
        1
        for record in records
        for repetition in record.repetitions
        if repetition.status == RepetitionStatus.VALID.value
    )
    infra_count = sum(
        1
        for record in records
        for repetition in record.repetitions
        if repetition.status == RepetitionStatus.INFRA.value
    )
    model_failure_count = sum(
        1
        for record in records
        for repetition in record.repetitions
        if repetition.classification == Outcome.MODEL_FAILURE.value
    )
    aggregate = aggregate_run(records, cases_by_id)
    valid_turns = [
        turn
        for record in records
        for repetition in record.repetitions
        if repetition.status == RepetitionStatus.VALID.value
        for turn in repetition.turns
    ]
    prompt = [turn.prompt_tokens for turn in valid_turns if turn.prompt_tokens is not None]
    completion = [
        turn.completion_tokens for turn in valid_turns if turn.completion_tokens is not None
    ]
    reasoning = [turn.reasoning_tokens for turn in valid_turns if turn.reasoning_tokens is not None]
    missing_usage = sum(
        1 for turn in valid_turns if turn.model_called and turn.prompt_tokens is None
    )
    session_bytes_values = [
        turn.session_bytes for turn in valid_turns if turn.session_bytes is not None
    ]
    encode_values = [
        turn.memory_encode_ms for turn in valid_turns if turn.memory_encode_ms is not None
    ]
    decode_values = [
        turn.memory_decode_ms for turn in valid_turns if turn.memory_decode_ms is not None
    ]
    render_values = [
        turn.memory_render_ms for turn in valid_turns if turn.memory_render_ms is not None
    ]
    artifact: dict[str, Any] = {
        "artifact_kind": RUN_ARTIFACT_KIND,
        "schema_version": LAB_SCHEMA_VERSION,
        "run_id": run_id,
        "baseline_id": baseline_id,
        "candidate_id": candidate_id,
        "variant": dict(identity),
        "variant_digest": variant_digest(identity),
        "corpus": {
            "path": "evals/conversation/cases.yaml",
            "sha256": corpus_digest(),
            "cases": len(cases_by_id),
            "families": len({case["family"] for case in cases_by_id.values()}),
            "selected_cases": sorted(cases_by_id),
        },
        "evaluator": build_evaluator_identity(),
        "scope": scope,
        "focused_reason": focused_reason,
        "rerun_of": rerun_of,
        "repetition_policy": {
            "valid_repetitions": repetitions,
            "warmups": warmup_count,
            "warmups_excluded_from_verdicts": True,
            "infra_policy": "repetition_level; focused_rerun_only",
        },
        "warmup_policy": {"warmups": warmup_count, "identical_input_id": WARMUP_INPUT_ID},
        "environment_class": environment_class,
        "started_at": started_at,
        "finished_at": finished_at,
        "tools": TOOLS_NONE,
        "turn_count": len(valid_turns),
        "model_call_count": sum(1 for turn in valid_turns if turn.model_called),
        "event_only_turn_count": sum(1 for turn in valid_turns if not turn.model_called),
        "warmup_count": len(warmups),
        "valid_repetition_count": valid_repetitions,
        "infra_count": infra_count,
        "model_failure_count": model_failure_count,
        "missing_usage_count": missing_usage,
        "aggregate": aggregate,
        "latency": {
            "model_latency_ms": summarize_values(
                [value for value in (turn.model_latency_ms for turn in valid_turns) if value]
            ),
            "runtime_semantic_ms": summarize_values(
                [
                    value
                    for value in (turn.runtime_semantic_ms for turn in valid_turns)
                    if value is not None
                ]
            ),
            "total_turn_ms": summarize_values([turn.total_turn_ms for turn in valid_turns]),
        },
        "tokens": {
            "prompt_tokens": summarize_tokens(prompt, missing=missing_usage),
            "completion_tokens": summarize_tokens(completion, missing=missing_usage),
            "reasoning_tokens": summarize_tokens(reasoning, missing=0),
        },
        "token_composition": token_composition,
        "session": {
            "session_bytes": summarize_values([float(value) for value in session_bytes_values]),
            "session_bytes_over_guard": sum(
                1 for turn in valid_turns if turn.session_bytes_over_guard
            ),
            "memory_encode_ms": summarize_values(encode_values),
            "memory_decode_ms": summarize_values(decode_values),
            "memory_render_ms": summarize_values(render_values),
            "memory_pairs_last": (
                max(turn.memory_pairs for turn in valid_turns) if valid_turns else 0
            ),
        },
        "warmups": warmups,
        "cases": [record.to_dict() for record in records],
    }
    findings = sanitization_findings(artifact)
    if findings:
        raise ValueError(f"retained evidence failed sanitization: {findings}")
    return artifact


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(
    artifact: dict[str, Any],
    records: list[TrialRecord],
    baseline: GeminiBaseline,
    repetitions: int,
    *,
    output_path: Path | None,
) -> None:
    print("=== CU013 conversation evaluation (real model, manual, outside CI) ===")
    print(f"run_id={artifact['run_id']} scope={artifact['scope']}")
    print(f"provider={baseline.provider} project={baseline.project}")
    print(f"location={baseline.location} model={baseline.model}")
    print(f"api_version={baseline.api_version} thinking_budget={baseline.thinking_budget}")
    print(f"repetitions={repetitions} warmups={artifact['warmup_policy']['warmups']}")
    print(f"variant_digest={artifact['variant_digest']}")
    print("events are simulated domain events; the XCALLY/AD wire contract stays open")
    print()
    by_family: dict[str, list[TrialRecord]] = {}
    for record in records:
        by_family.setdefault(record.family, []).append(record)
    for family in sorted(by_family):
        items = by_family[family]
        summaries = summarize_verdicts([item.summary() for item in items])
        status = "PASS" if not any(item.summary() in FAIL_LIKE for item in items) else "FAIL"
        print(f"[{status}] family={family} trials={len(items)} {summaries}")
        for item in items:
            for repetition in item.repetitions:
                observed = {
                    "route": repetition.turns[-1].runtime_route if repetition.turns else None,
                    "goal": repetition.turns[-1].state_after.goal_action
                    if repetition.turns
                    else None,
                    "revision": repetition.turns[-1].state_after.goal_revision
                    if repetition.turns
                    else None,
                    "confirmation": repetition.turns[-1].confirmation_state
                    if repetition.turns
                    else None,
                    "dispatches": repetition.dispatch_count,
                }
                print(
                    f"  {item.trial_id} rep{repetition.repetition_id} "
                    f"{repetition.classification} {observed}"
                )
                for detail in repetition.failure_details:
                    print(f"    FAIL {detail}")
                if repetition.error_class:
                    print(f"    error_class={repetition.error_class}")
                blocked = sorted(set(repetition.blocked_proposals))
                if blocked:
                    print(f"    blocked_proposals={blocked}")
                criticals = sorted(set(repetition.critical_findings))
                if criticals:
                    print(f"    CRITICAL {criticals}")
                if repetition.first_divergent_turn is not None:
                    print(f"    first_divergent_turn={repetition.first_divergent_turn}")
    print()
    for label, key in (
        ("latency_ms model", "model_latency_ms"),
        ("latency_ms runtime_semantic", "runtime_semantic_ms"),
        ("latency_ms turn_total", "total_turn_ms"),
    ):
        print(f"{label}: {artifact['latency'][key]}")
    print(f"tokens_prompt: {artifact['tokens']['prompt_tokens']}")
    print(f"tokens_completion: {artifact['tokens']['completion_tokens']}")
    print(f"tokens_reasoning: {artifact['tokens']['reasoning_tokens']}")
    print(f"session_bytes: {artifact['session']['session_bytes']}")
    print(
        f"session_over_guard={artifact['session']['session_bytes_over_guard']} "
        f"memory_encode_ms={artifact['session']['memory_encode_ms']} "
        f"memory_decode_ms={artifact['session']['memory_decode_ms']} "
        f"memory_render_ms={artifact['session']['memory_render_ms']}"
    )
    print(
        f"lane={artifact['variant'].get('lane')} "
        f"memory_variant={artifact['variant'].get('memory_variant')} "
        f"memory_n={artifact['variant'].get('memory_n')} "
        f"strategy={artifact['variant'].get('prompt_strategy')} "
        f"thinking_level={artifact['variant'].get('thinking_level')}"
    )
    print(f"prompt_composition={artifact['variant'].get('prompt_composition', {}).get('mode')}")
    if artifact.get("token_composition"):
        print(f"token_composition={artifact['token_composition']}")
    for sequence in artifact["aggregate"]["sequences"]:
        print(f"sequence {sequence['case_id']}:")
        for point in sequence["series"]:
            print(
                f"  turn{point['turn_index']} model_p50={point['model_latency_ms']['p50']} "
                f"prompt_p50={point['prompt_tokens_per_call']['p50']} "
                f"prompt_cumulative_mean={point['prompt_tokens_cumulative_mean']} "
                f"completion_cumulative_mean={point['completion_tokens_cumulative_mean']} "
                f"latency_cumulative_mean={point['model_latency_ms_cumulative_mean']}"
            )
    print()
    print(f"aggregate.repetition_verdicts={artifact['aggregate']['repetition_verdicts']}")
    print(f"aggregate.case_summaries={artifact['aggregate']['case_summaries']}")
    print(f"aggregate.route_distribution={artifact['aggregate']['route_distribution']}")
    print(f"valid_repetitions={artifact['valid_repetition_count']} infra={artifact['infra_count']}")
    if output_path is not None:
        print(f"artifact={output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CU013 conversation evaluation runner")
    parser.add_argument("--families", default=None, help="comma-separated family filter")
    parser.add_argument(
        "--repetitions", type=int, default=DEFAULT_REPETITIONS, help="valid repetitions per trial"
    )
    parser.add_argument(
        "--warmups", type=int, default=DEFAULT_WARMUPS, help="warmup model calls, excluded"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the corpus statically; no ADC and no model call",
    )
    parser.add_argument("--baseline-id", default=None, help="label for the compared baseline")
    parser.add_argument("--candidate-id", default=None, help="label for this candidate")
    parser.add_argument(
        "--scope", choices=["full", "focused"], default="full", help="evidence scope"
    )
    parser.add_argument("--focused-reason", default=None, help="why this focused rerun exists")
    parser.add_argument("--rerun-of", default=None, help="run_id this focused rerun supersedes")
    parser.add_argument(
        "--environment-class", default=ENVIRONMENT_CLASS_DEFAULT, help="evidence environment"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_RESULTS_DIR, help="local results directory"
    )
    parser.add_argument("--no-write", action="store_true", help="do not write the run artifact")
    parser.add_argument(
        "--prompt-variant",
        choices=[PROMPT_VARIANT_PROTOCOLS, PROMPT_VARIANT_SNAPSHOT],
        default=PROMPT_VARIANT_PROTOCOLS,
        help="declared experimental variable: prompt_composition_protocols composes "
        "core+catalog+active private protocol; single_baseline_snapshot replays the "
        "frozen 129c793 baseline text for the paired comparison",
    )
    parser.add_argument(
        "--token-breakdown",
        action="store_true",
        help="after the timed replay, count tokens per composition bucket "
        "(provider count_tokens; numbers only, never on the turn path)",
    )
    parser.add_argument(
        "--lane",
        choices=["direct", "repository"],
        default="direct",
        help="direct invokes model+runtime; repository replays through TurnService "
        "with save/reload per turn and a fresh service per turn (restart proof)",
    )
    parser.add_argument(
        "--memory-variant",
        choices=[NO_RECENT_MEMORY, *MEMORY_VARIANTS],
        default=NO_RECENT_MEMORY,
        help="Exp 0009 arm: no_recent_memory (current behavior), "
        "procedure_progress_only (guided progress only), "
        "recent_conversation_memory (progress plus the recent-pair window)",
    )
    parser.add_argument(
        "--memory-n",
        type=int,
        default=3,
        help="experimental window pairs for the recent-memory arm (default 3; "
        "5 only as the conditional follow-up the experiment defines)",
    )
    parser.add_argument(
        "--prompt-strategy",
        choices=list(PROMPT_POLICIES),
        default=DEFAULT_PROMPT_POLICY,
        help="Exp 0009 Q12 prompt policy for the memory arms: "
        "default_prompt_policy (base wording), concise_prompt_policy (diet), "
        "contrastive_examples_prompt_policy (diet plus 2 few-shots), "
        "precedence_prompt_policy (precedence prefix plus the base criteria)",
    )
    return parser.parse_args(argv)


async def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases = load_corpus()
    problems = validate_corpus(cases)
    if problems:
        for problem in problems:
            print(f"CORPUS {problem}", file=sys.stderr)
        return 2
    if args.families:
        wanted = {family.strip() for family in args.families.split(",")}
        cases = [case for case in cases if case["family"] in wanted]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2
    if args.validate_only:
        print(f"corpus validated: cases={len(cases)} problems=0")
        return 0
    if args.repetitions < 1:
        print("repetitions must be >= 1", file=sys.stderr)
        return 2
    if args.warmups < 0:
        print("warmups must be >= 0", file=sys.stderr)
        return 2
    if args.memory_variant == NO_RECENT_MEMORY and args.memory_n != 3:
        print("memory-n only applies to the recent-memory variant", file=sys.stderr)
        return 2
    if not 1 <= args.memory_n <= 5:
        print("memory-n must be within 1..5", file=sys.stderr)
        return 2
    if args.prompt_strategy not in PROMPT_POLICIES:
        print("unknown prompt policy", file=sys.stderr)
        return 2
    if args.memory_variant == NO_RECENT_MEMORY and args.prompt_strategy != DEFAULT_PROMPT_POLICY:
        print("prompt-strategy only applies to the memory variants", file=sys.stderr)
        return 2
    experimental: ExperimentalMemoryConfig | None = None
    if args.memory_variant in (PROCEDURE_PROGRESS_ONLY, RECENT_CONVERSATION_MEMORY):
        experimental = ExperimentalMemoryConfig(
            variant=args.memory_variant,
            window_n=args.memory_n,
            strategy=args.prompt_strategy,
        )
    try:
        prompt_source = resolve_prompt_source(args.prompt_variant)
    except (PromptBundleError, OSError, ValueError) as exc:
        print(f"PROMPT {exc}", file=sys.stderr)
        return 2

    baseline = GeminiBaseline.from_env()
    client = Client(
        vertexai=True,
        project=baseline.project,
        location=baseline.location,
        http_options=HttpOptions(api_version=baseline.api_version),
    )
    metrics = RecordingTurnMetrics()
    model = GeminiTurnModel(client, baseline, prompts=prompt_source, metrics=metrics)
    now = datetime.now(UTC)
    started_at = utc_now()
    token_composition: dict[str, Any] | None = None
    try:
        records, warmups = await evaluate(
            model,
            metrics,
            cases,
            args.repetitions,
            warmups=args.warmups,
            now=now,
            experimental=experimental,
            lane=args.lane,
        )
        if args.token_breakdown:
            token_composition = await token_composition_breakdown(client, baseline, prompt_source)
    finally:
        await client.aio.aclose()
    finished_at = utc_now()
    identity = build_variant_identity(
        baseline,
        memory_variant=args.memory_variant,
        memory_n=args.memory_n,
        lane=args.lane,
        strategy=args.prompt_strategy,
        prompt_source=prompt_source,
    )
    digest = variant_digest(identity)
    run_id = make_run_id("conversation-eval", at=started_at, digest=digest)
    baseline_id = args.baseline_id or digest
    candidate_id = args.candidate_id or digest
    artifact = build_artifact(
        records,
        warmups,
        {case["case_id"]: case for case in cases},
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        identity=identity,
        baseline_id=baseline_id,
        candidate_id=candidate_id,
        repetitions=args.repetitions,
        warmup_count=args.warmups,
        environment_class=args.environment_class,
        scope=args.scope,
        focused_reason=args.focused_reason,
        rerun_of=args.rerun_of,
        token_composition=token_composition,
    )
    output_path: Path | None = None
    if not args.no_write:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = args.output_dir / f"{run_id}.json"
        output_path.write_text(
            json.dumps(artifact, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print_report(artifact, records, baseline, args.repetitions, output_path=output_path)
    failed = artifact["aggregate"]["case_summaries"].get(Outcome.FAIL.value, 0)
    infra = artifact["aggregate"]["case_summaries"].get(Outcome.INFRA.value, 0)
    return 1 if failed or infra else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
