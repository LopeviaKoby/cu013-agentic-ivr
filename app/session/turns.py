"""Ephemeral turn state, the typed model decision and the runtime legality turn.

LangGraph orchestrates one technical turn in RAM: the optional model node
produces semantic proposals and the deterministic runtime node owns legality,
durable state and truth. Nothing here is durable and no checkpointer is ever
compiled.

The model never sets identity, dispatch, external truth or delivery: those
fields do not exist in its contract. The runtime materializes the durable
dispatch guard a future XCALLY integration would consume; it never executes a
side effect, invents a wire payload or calls an external service.
"""

from datetime import datetime
from enum import StrEnum
from functools import partial
from typing import Protocol, Self, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.session.actions import Action
from app.session.memory import (
    ExperimentalMemoryConfig,
    ExperimentalProcedureState,
    ExperimentalSuspendedProcedure,
    ExperimentalTurnPair,
    ProcedureObservation,
    append_pair,
    apply_goal_lifecycle,
    apply_procedure_observation,
    decode_experimental,
    make_pair,
    render_memory_block,
)
from app.session.record import (
    AuthorizedDispatch,
    ConfirmationChallenge,
    ConversationGoal,
    DeliveryStatus,
    ExternalOperation,
    IdentityState,
    OperationStatus,
    SessionRecord,
)

SAFE_FALLBACK_MESSAGE = (
    "No puedo confirmar eso en este momento. ¿Quieres que revisemos juntos tu solicitud?"
)

ESCALATION_MESSAGE = "No pudimos completar la validación de identidad. Te comunico con una persona."

PROCESSING_MESSAGE = "Voy a procesar la solicitud. Puede tardar unos segundos."


class Route(StrEnum):
    """Route the turn decision carries for the Cally Square boundary."""

    CONTINUE = "CONTINUE"
    COLLECT_IDENTITY = "COLLECT_IDENTITY"
    COMPLETE = "COMPLETE"
    ESCALATE = "ESCALATE"


class BoundaryRoute(StrEnum):
    """Route the boundary emits: the model-facing routes plus EXECUTE_ACTION.

    The model-facing contract stays the closed four-value ``Route``; the
    runtime alone creates ``EXECUTE_ACTION`` when it persists a legal
    dispatch guard.
    """

    CONTINUE = "CONTINUE"
    COLLECT_IDENTITY = "COLLECT_IDENTITY"
    COMPLETE = "COMPLETE"
    ESCALATE = "ESCALATE"
    EXECUTE_ACTION = "EXECUTE_ACTION"


class GoalIntent(StrEnum):
    """Semantic delta the model proposes for the conversational plan."""

    NONE = "NONE"
    REQUEST = "REQUEST"
    CORRECT = "CORRECT"
    CANCEL = "CANCEL"


class GoalProposal(BaseModel):
    """Plan proposal: what the model understood the caller wants now."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: GoalIntent
    action: Action | None = None


class ConfirmationObservation(StrEnum):
    """How the model read the caller's answer to the active challenge."""

    NONE = "NONE"
    AFFIRMATIVE = "AFFIRMATIVE"
    NEGATIVE = "NEGATIVE"
    AMBIGUOUS = "AMBIGUOUS"
    CANCEL = "CANCEL"


class HandoffCause(StrEnum):
    """Handoff causes the SPEC permits without inventing new ones.

    Unsupported or out-of-scope requests are answered or redirected, never
    used as a handoff cause: ESCALATE is not a classification or scope
    fallback (owner decision), so no such cause exists in the closed contract.
    """

    CALLER_REQUEST = "CALLER_REQUEST"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"


class ClaimKind(StrEnum):
    """Business claims the runtime can verify against its own evidence."""

    IDENTITY_VALID = "IDENTITY_VALID"
    ACTION_AUTHORIZED = "ACTION_AUTHORIZED"
    OPERATION_SUCCEEDED = "OPERATION_SUCCEEDED"
    OPERATION_FAILED = "OPERATION_FAILED"
    RESET_CONFIRMED = "RESET_CONFIRMED"
    DELIVERY_CONFIRMED = "DELIVERY_CONFIRMED"


class Claim(BaseModel):
    """Structured claim proposal; the runtime, not the model, decides if it holds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ClaimKind


class ModelTurnDecision(BaseModel):
    """Semantic proposal for one turn. Transient; never durable, never authoritative."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str = Field(min_length=1)
    route: Route
    goal: GoalProposal | None = None
    confirmation_request: bool = False
    confirmation_observation: ConfirmationObservation = ConfirmationObservation.NONE
    procedure_observation: ProcedureObservation = Field(
        default=ProcedureObservation.NONE,
        description=(
            "Propuesta de progreso del procedimiento guiado: ADVANCE sólo si "
            "el llamante completó el paso actual; REGRESS si dice que no lo "
            "terminó, sin cambiar el objetivo; NONE en otro caso."
        ),
    )
    handoff_cause: HandoffCause | None = None
    claims: tuple[Claim, ...] = Field(default=(), max_length=4)


class IdentityOutcome(StrEnum):
    """Domain result of one identity validation attempt (wire contract: ID-001)."""

    VALIDATED = "VALIDATED"
    CALLER_FAILURE = "CALLER_FAILURE"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"


class ConfirmationEvent(StrEnum):
    """Voice-domain confirmation events; events, never caller phrases (XC-001)."""

    ASR_TIMEOUT = "ASR_TIMEOUT"


class ExternalEventKind(StrEnum):
    """Simulated boundary event kinds; no wire status is invented here."""

    DISPATCH_UNKNOWN = "DISPATCH_UNKNOWN"
    RESULT = "RESULT"
    LATE_RESULT = "LATE_RESULT"
    DELIVERY = "DELIVERY"


class ExternalEvent(BaseModel):
    """External boundary event; only this seam changes external-operation truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ExternalEventKind
    operation_id: str = Field(min_length=1)
    status: OperationStatus | None = None
    delivery: DeliveryStatus | None = None


class TurnInput(BaseModel):
    """Per-turn transient input. Never persisted and never durable state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transcript: str | None = None
    identity_outcome: IdentityOutcome | None = None
    confirmation_event: ConfirmationEvent | None = None
    external_event: ExternalEvent | None = None


class ExternalActionCommand(BaseModel):
    """Authorized external action the boundary orders XCALLY to execute.

    The command is CU013-owned correlation: only the opaque ``operation_id``,
    the closed ``action`` enum and the goal revision bound to the same guard.
    It never carries document, date, phone, email, password, temporary
    password, RD API key, RD URL, RD payload, CALLERID(Name), ``codigo`` or
    ``callId``. The runtime creates it only after the dispatch guard is
    durable; the model never proposes or executes it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1)
    action: Action
    goal_revision: int = Field(ge=0)


class TurnOutcomeState(BaseModel):
    """Runtime-validated outcome the boundary may emit; safe by construction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str = Field(min_length=1)
    route: BoundaryRoute
    command: ExternalActionCommand | None = None
    violations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _command_only_with_execute_action(self) -> Self:
        if self.command is not None and self.route is not BoundaryRoute.EXECUTE_ACTION:
            raise ValueError("command is only valid with EXECUTE_ACTION")
        if self.route is BoundaryRoute.EXECUTE_ACTION and self.command is None:
            raise ValueError("EXECUTE_ACTION requires a command")
        return self


class TurnModel(Protocol):
    """Minimal model capability the turn consumes; one call per normal turn.

    The model receives only the current transcript and the semantic projection
    of the durable record. Raw DTMF cannot reach this seam, the model never
    validates identity, never authorizes dispatch and never creates business
    results.
    """

    async def decide(
        self,
        *,
        transcript: str,
        goal: ConversationGoal | None,
        identity_validated: bool,
        confirmation: ConfirmationChallenge | None,
        external_operation: ExternalOperation | None,
        memory_context: str | None = None,
    ) -> ModelTurnDecision: ...


class GraphState(TypedDict):
    """Ephemeral state: durable projection, per-turn input and validated outcome."""

    conversation_id: str
    goal: ConversationGoal | None
    identity: IdentityState
    confirmation: ConfirmationChallenge | None
    dispatch: AuthorizedDispatch | None
    external_operation: ExternalOperation | None
    experimental_config: ExperimentalMemoryConfig | None
    experimental_procedure: ExperimentalProcedureState | None
    experimental_suspended: ExperimentalSuspendedProcedure | None
    experimental_window: tuple[ExperimentalTurnPair, ...]
    memory_render_ms: float | None
    memory_decode_ms: float
    memory_encode_ms: float | None
    now: datetime
    transcript: str | None
    identity_outcome: IdentityOutcome | None
    confirmation_event: ConfirmationEvent | None
    external_event: ExternalEvent | None
    model_decision: ModelTurnDecision | None
    outcome: TurnOutcomeState | None


class TurnDelta(TypedDict):
    """The durable projection one turn changes plus the validated outcome."""

    goal: ConversationGoal | None
    identity: IdentityState
    confirmation: ConfirmationChallenge | None
    dispatch: AuthorizedDispatch | None
    external_operation: ExternalOperation | None
    experimental_procedure: ExperimentalProcedureState | None
    experimental_suspended: ExperimentalSuspendedProcedure | None
    experimental_window: tuple[ExperimentalTurnPair, ...]
    memory_encode_ms: float | None
    outcome: TurnOutcomeState | None


def initial_graph_state(
    record: SessionRecord,
    turn: TurnInput,
    *,
    now: datetime,
    experimental: ExperimentalMemoryConfig | None = None,
) -> GraphState:
    """Build the ephemeral state from durable state plus this turn's input."""
    procedure, suspended, window, decode_ms = decode_experimental(
        record.experimental_procedure,
        record.experimental_suspended,
        record.experimental_window,
    )
    return GraphState(
        conversation_id=record.conversation_id,
        goal=record.goal,
        identity=record.identity,
        confirmation=record.confirmation,
        dispatch=record.dispatch,
        external_operation=record.external_operation,
        experimental_config=experimental,
        experimental_procedure=procedure,
        experimental_suspended=suspended,
        experimental_window=window,
        memory_render_ms=None,
        memory_decode_ms=decode_ms,
        memory_encode_ms=None,
        now=now,
        transcript=turn.transcript,
        identity_outcome=turn.identity_outcome,
        confirmation_event=turn.confirmation_event,
        external_event=turn.external_event,
        model_decision=None,
        outcome=None,
    )


async def run_model(
    state: GraphState, *, model: TurnModel
) -> dict[str, ModelTurnDecision | float | str | None]:
    """Produce the typed semantic proposal from the transcript and projection.

    The model owns language; it never validates identity, never authorizes a
    dispatch, never creates business results and never executes side effects.
    Under the Exp 0009 opt-in the synthetic recent-pair/procedure block is
    rendered into the model input; the default no-recent-memory path renders
    nothing new.
    """
    transcript = state["transcript"]
    if transcript is None:
        return {"model_decision": None}
    memory_context: str | None = None
    render_ms: float | None = None
    if state["experimental_config"] is not None:
        memory_context, render_ms = render_memory_block(
            state["experimental_window"],
            state["experimental_procedure"],
            state["experimental_suspended"],
            window_n=state["experimental_config"].window_n,
            strategy=state["experimental_config"].strategy,
        )
    decision = await model.decide(
        transcript=transcript,
        goal=state["goal"],
        identity_validated=state["identity"].is_valid_at(state["now"]),
        confirmation=state["confirmation"],
        external_operation=state["external_operation"],
        memory_context=memory_context,
    )
    return {"model_decision": decision, "memory_render_ms": render_ms}


def _apply_identity_outcome(
    identity: IdentityState,
    outcome: IdentityOutcome | None,
    *,
    now: datetime,
) -> IdentityState:
    """Apply one boundary identity result; only caller mistakes count."""
    if outcome is IdentityOutcome.VALIDATED:
        return IdentityState(validated_at=now, caller_failures=identity.caller_failures)
    if outcome is IdentityOutcome.CALLER_FAILURE:
        return IdentityState(
            validated_at=identity.validated_at,
            caller_failures=identity.caller_failures + 1,
        )
    return identity


def _challenge_is_stale(
    challenge: ConfirmationChallenge,
    goal: ConversationGoal | None,
) -> bool:
    """A challenge dies when the goal it challenged is gone or revised."""
    if goal is None:
        return True
    return challenge.action is not goal.action or challenge.goal_revision != goal.revision


def _apply_goal_proposal(
    goal: ConversationGoal | None,
    challenge: ConfirmationChallenge | None,
    proposal: GoalProposal | None,
) -> tuple[ConversationGoal | None, ConfirmationChallenge | None, str | None]:
    """Apply the plan delta; any revision change invalidates the challenge."""
    if proposal is None or proposal.intent is GoalIntent.NONE:
        return goal, challenge, None
    if proposal.intent is GoalIntent.CANCEL:
        return None, None, None
    action = proposal.action
    if action is None:
        return goal, challenge, "goal proposal without an action"
    if goal is not None and goal.action is action:
        if proposal.intent is GoalIntent.CORRECT:
            goal = ConversationGoal(action=action, revision=goal.revision + 1)
    else:
        goal = ConversationGoal(
            action=action,
            revision=(goal.revision + 1) if goal is not None else 1,
        )
    if challenge is not None and _challenge_is_stale(challenge, goal):
        challenge = None
    return goal, challenge, None


def _apply_confirmation_observation(
    decision: ModelTurnDecision,
    *,
    goal: ConversationGoal | None,
    identity: IdentityState,
    challenge: ConfirmationChallenge | None,
    dispatch: AuthorizedDispatch | None,
    operation: ExternalOperation | None,
    now: datetime,
) -> tuple[
    ConfirmationChallenge | None,
    AuthorizedDispatch | None,
    ExternalOperation | None,
    str | None,
]:
    """Apply the model's reading of the caller's answer; authorize only if legal."""
    observation = decision.confirmation_observation
    if observation is ConfirmationObservation.NONE:
        return challenge, dispatch, operation, None
    if challenge is None:
        # Without an active challenge an observation authorizes nothing.
        return None, dispatch, operation, None
    if observation in {
        ConfirmationObservation.NEGATIVE,
        ConfirmationObservation.AMBIGUOUS,
        ConfirmationObservation.CANCEL,
    }:
        return None, dispatch, operation, None
    binding_error = _dispatch_binding_error(
        challenge, goal=goal, identity=identity, dispatch=dispatch, now=now
    )
    if binding_error is not None:
        return None, dispatch, operation, binding_error
    if operation is not None and operation.is_active():
        return None, dispatch, operation, "dispatch with an active external operation"
    operation_id = uuid4().hex
    authorized = AuthorizedDispatch(
        operation_id=operation_id,
        action=challenge.action,
        goal_revision=challenge.goal_revision,
        challenge_id=challenge.challenge_id,
        authorized_at=now,
    )
    opened = ExternalOperation(
        operation_id=operation_id,
        action=challenge.action,
        last_progress_feedback_at=now,
        progress_feedback_index=0,
    )
    return None, authorized, opened, None


def _dispatch_binding_error(
    challenge: ConfirmationChallenge,
    *,
    goal: ConversationGoal | None,
    identity: IdentityState,
    dispatch: AuthorizedDispatch | None,
    now: datetime,
) -> str | None:
    """Deterministic checks the dispatch guard requires before it may exist."""
    if not identity.is_valid_at(now):
        return "dispatch without a valid identity authorization"
    if identity.requires_handoff():
        return "dispatch after the identity attempts were exhausted"
    if goal is None:
        return "dispatch without a supported goal"
    if challenge.action is not goal.action or challenge.goal_revision != goal.revision:
        return "confirmation does not match the current goal and revision"
    if challenge.identity_validated_at != identity.validated_at:
        return "confirmation does not match the validated identity"
    if dispatch is not None and dispatch.challenge_id == challenge.challenge_id:
        return "duplicate dispatch for the same confirmation challenge"
    return None


def _maybe_open_challenge(
    decision: ModelTurnDecision,
    *,
    goal: ConversationGoal | None,
    identity: IdentityState,
    challenge: ConfirmationChallenge | None,
    operation: ExternalOperation | None,
    now: datetime,
) -> ConfirmationChallenge | None:
    """Open a challenge only when the caller is legally eligible to confirm."""
    validated_at = identity.validated_at
    if not decision.confirmation_request:
        return challenge
    if challenge is not None:
        return challenge
    if goal is None or validated_at is None or not identity.is_valid_at(now):
        return None
    if identity.requires_handoff():
        return None
    if operation is not None and operation.is_active():
        return None
    return ConfirmationChallenge(
        challenge_id=uuid4().hex,
        action=goal.action,
        goal_revision=goal.revision,
        identity_validated_at=validated_at,
        issued_at=now,
    )


def _apply_external_event(
    operation: ExternalOperation | None,
    event: ExternalEvent | None,
) -> ExternalOperation | None:
    """Reconcile one boundary event with the existing operation, never a new one."""
    if event is None or operation is None:
        return operation
    if event.operation_id != operation.operation_id:
        return operation
    if event.kind is ExternalEventKind.DISPATCH_UNKNOWN:
        if operation.status is OperationStatus.PENDING:
            return operation.model_copy(update={"status": OperationStatus.UNKNOWN})
        return operation
    if event.kind in {ExternalEventKind.RESULT, ExternalEventKind.LATE_RESULT}:
        if event.status in {OperationStatus.CONFIRMED, OperationStatus.FAILED}:
            return operation.model_copy(update={"status": event.status})
        return operation
    if event.kind is ExternalEventKind.DELIVERY:
        if operation.action is Action.RESET_PASSWORD and event.delivery is not None:
            return operation.model_copy(update={"delivery": event.delivery})
        return operation
    return operation


def _claim_is_backed(
    kind: ClaimKind,
    *,
    identity: IdentityState,
    dispatch: AuthorizedDispatch | None,
    operation: ExternalOperation | None,
    now: datetime,
) -> bool:
    """Verify one structured claim against runtime evidence only."""
    if kind is ClaimKind.IDENTITY_VALID:
        return identity.is_valid_at(now)
    if kind is ClaimKind.ACTION_AUTHORIZED:
        return dispatch is not None
    if kind is ClaimKind.OPERATION_SUCCEEDED:
        return operation is not None and operation.status is OperationStatus.CONFIRMED
    if kind is ClaimKind.OPERATION_FAILED:
        return operation is not None and operation.status is OperationStatus.FAILED
    if kind is ClaimKind.RESET_CONFIRMED:
        return (
            operation is not None
            and operation.action is Action.RESET_PASSWORD
            and operation.status is OperationStatus.CONFIRMED
        )
    return operation is not None and operation.delivery is DeliveryStatus.CONFIRMED


def _complete_is_backed(operation: ExternalOperation | None) -> bool:
    """COMPLETE never proves a side effect and never closes unfinished business."""
    if operation is None:
        return True
    if operation.is_active():
        return False
    return not (
        operation.action is Action.RESET_PASSWORD
        and operation.status is OperationStatus.CONFIRMED
        and operation.delivery is not DeliveryStatus.CONFIRMED
    )


def _handoff_cause_is_backed(
    decision: ModelTurnDecision,
    *,
    identity: IdentityState,
    operation: ExternalOperation | None,
) -> bool:
    """Only SPEC causes count; sensitivity alone is never one of them."""
    cause = decision.handoff_cause
    if cause is HandoffCause.CALLER_REQUEST:
        return True
    if cause is HandoffCause.TERMINAL_FAILURE:
        return identity.requires_handoff() or (
            operation is not None and operation.status is OperationStatus.FAILED
        )
    return False


def _guard_outcome(
    decision: ModelTurnDecision | None,
    *,
    goal: ConversationGoal | None,
    identity: IdentityState,
    dispatch: AuthorizedDispatch | None,
    operation: ExternalOperation | None,
    now: datetime,
    extra_violations: tuple[str, ...] = (),
) -> TurnOutcomeState | None:
    """Reject illegal routes and unbacked claims; never add a second model call."""
    violations = list(extra_violations)
    if decision is not None:
        for claim in decision.claims:
            if not _claim_is_backed(
                claim.kind, identity=identity, dispatch=dispatch, operation=operation, now=now
            ):
                violations.append(f"unbacked claim {claim.kind.value}")
        if decision.route is Route.COLLECT_IDENTITY and (goal is None or identity.is_valid_at(now)):
            violations.append("COLLECT_IDENTITY is not coherent with the current plan")
        if decision.route is Route.ESCALATE and not identity.requires_handoff():
            if not _handoff_cause_is_backed(decision, identity=identity, operation=operation):
                violations.append("ESCALATE without a permitted handoff cause")
        if decision.route is Route.COMPLETE and not _complete_is_backed(operation):
            violations.append("COMPLETE asserted an unbacked business result")
    if identity.requires_handoff():
        return TurnOutcomeState(
            message=ESCALATION_MESSAGE,
            route=BoundaryRoute.ESCALATE,
            violations=tuple(violations),
        )
    if decision is None:
        return None
    if violations:
        return TurnOutcomeState(
            message=SAFE_FALLBACK_MESSAGE,
            route=BoundaryRoute.CONTINUE,
            violations=tuple(violations),
        )
    return TurnOutcomeState(message=decision.message, route=BoundaryRoute(decision.route.value))


def advance_turn(state: GraphState) -> TurnDelta:
    """Apply one deterministic turn with the runtime keeping the last word.

    Boundary events (identity result, voice-domain confirmation event,
    external result) and the model's semantic proposal are applied in a fixed
    order. Identity is never downgraded by a failed attempt; the plan is
    separate from authorization; a dispatch guard exists only after every
    legality check passes; external truth changes only through boundary
    events; and an illegal proposal falls back to a safe deterministic output
    without a second model call.
    """
    now = state["now"]
    identity = _apply_identity_outcome(state["identity"], state["identity_outcome"], now=now)
    challenge = state["confirmation"]
    if challenge is not None and _challenge_is_stale(challenge, state["goal"]):
        # Repair durable state: a challenge bound to a superseded goal revision
        # is invalid by definition, whatever the current turn proposes.
        challenge = None
    if identity.validated_at != state["identity"].validated_at:
        challenge = None
    if state["confirmation_event"] is ConfirmationEvent.ASR_TIMEOUT:
        challenge = None

    decision = state["model_decision"]
    proposal_error: str | None = None
    goal = state["goal"]
    if decision is not None:
        goal, challenge, proposal_error = _apply_goal_proposal(goal, challenge, decision.goal)

    dispatch = state["dispatch"]
    operation = state["external_operation"]
    binding_error: str | None = None
    dispatched_this_turn = False
    if decision is not None:
        if (
            decision.confirmation_observation is ConfirmationObservation.CANCEL
            and challenge is not None
        ):
            # An explicit cancellation before dispatch cancels the challenged
            # action itself, not only the confirmation attempt.
            goal = None
        challenge, dispatch, operation, binding_error = _apply_confirmation_observation(
            decision,
            goal=goal,
            identity=identity,
            challenge=challenge,
            dispatch=dispatch,
            operation=operation,
            now=now,
        )
        dispatched_this_turn = dispatch is not None and dispatch is not state["dispatch"]
        if not dispatched_this_turn:
            challenge = _maybe_open_challenge(
                decision,
                goal=goal,
                identity=identity,
                challenge=challenge,
                operation=operation,
                now=now,
            )
    operation = _apply_external_event(operation, state["external_event"])

    experimental = state["experimental_config"]
    procedure = state["experimental_procedure"]
    suspended = state["experimental_suspended"]
    window = state["experimental_window"]
    encode_ms: float | None = None
    if experimental is not None:
        previous_action = state["goal"].action if state["goal"] is not None else None
        current_action = goal.action if goal is not None else None
        current_revision = goal.revision if goal is not None else 0
        procedure, suspended = apply_goal_lifecycle(
            procedure,
            suspended,
            previous_action=previous_action,
            current_action=current_action,
            current_revision=current_revision,
            now=now,
        )
        if decision is not None:
            procedure = apply_procedure_observation(procedure, decision.procedure_observation)

    extra_violations = tuple(
        error for error in (proposal_error, binding_error) if error is not None
    )
    outcome: TurnOutcomeState | None
    if dispatched_this_turn and dispatch is not None:
        # The durable guard exists: the boundary must deliver its command even
        # if the same model turn proposed something illegal. The runtime
        # message replaces the model message, so no unbacked claim is spoken;
        # any violation remains recorded as evidence.
        outcome = TurnOutcomeState(
            message=PROCESSING_MESSAGE,
            route=BoundaryRoute.EXECUTE_ACTION,
            command=ExternalActionCommand(
                operation_id=dispatch.operation_id,
                action=dispatch.action,
                goal_revision=dispatch.goal_revision,
            ),
            violations=extra_violations,
        )
    else:
        outcome = _guard_outcome(
            decision,
            goal=goal,
            identity=identity,
            dispatch=dispatch,
            operation=operation,
            now=now,
            extra_violations=extra_violations,
        )

    if (
        experimental is not None
        and experimental.with_window
        and state["transcript"] is not None
        and decision is not None
        and outcome is not None
    ):
        # Only completed/validated pairs: the runtime-final message intended
        # for the 200 response. Drafts, model JSON, technical polls,
        # timeouts, retries, tool payloads and external secrets never land
        # here; without a transcript or an outcome nothing is appended.
        next_sequence = max((pair.sequence for pair in window), default=0) + 1
        candidate = make_pair(
            state["transcript"],
            outcome.message,
            sequence=next_sequence,
            goal_revision=goal.revision if goal is not None else None,
        )
        window, encode_ms = append_pair(window, candidate, window_n=experimental.window_n)

    return TurnDelta(
        goal=goal,
        identity=identity,
        confirmation=challenge,
        dispatch=dispatch,
        external_operation=operation,
        experimental_procedure=procedure,
        experimental_suspended=suspended,
        experimental_window=window,
        memory_encode_ms=encode_ms,
        outcome=outcome,
    )


TurnGraph = CompiledStateGraph[GraphState, None, GraphState, GraphState]


def build_turn_graph(model: TurnModel | None = None) -> TurnGraph:
    """Compile the turn graph without a persistent checkpointer.

    With a model the graph runs START -> run_model -> advance_turn -> END:
    exactly one model call per turn and the runtime node keeps the last
    word on legality and durable state. Without a model only the runtime
    node runs, which keeps the deterministic session core self-contained.
    """
    builder = StateGraph(GraphState)
    builder.add_node("advance_turn", advance_turn)
    if model is not None:
        builder.add_node("run_model", partial(run_model, model=model))
        builder.add_edge(START, "run_model")
        builder.add_edge("run_model", "advance_turn")
    else:
        builder.add_edge(START, "advance_turn")
    builder.add_edge("advance_turn", END)
    return builder.compile()
