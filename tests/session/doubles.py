"""Deterministic in-memory doubles and fixtures for the session seams.

Every value is synthetic and PII-safe; no model, network, Firestore or
credentials are involved.
"""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

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
from app.session.turns import (
    BoundaryRoute,
    GraphState,
    ModelTurnDecision,
    Route,
    TurnOutcomeState,
)

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


class FrozenClock:
    """Injectable clock: tests advance it explicitly instead of sleeping."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class InMemorySessionDocumentStore:
    """Implements SessionDocumentStore without Firestore, credentials or network."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, object]] = {}
        self.reads = 0
        self.writes = 0
        self.fail_writes = False
        self.write_started = asyncio.Event()
        self.write_gate: asyncio.Event | None = None

    async def read(self, conversation_id: str) -> Mapping[str, object] | None:
        self.reads += 1
        document = self.documents.get(conversation_id)
        if document is None:
            return None
        return dict(document)

    async def write(self, conversation_id: str, document: Mapping[str, object]) -> None:
        self.writes += 1
        self.write_started.set()
        if self.write_gate is not None:
            await self.write_gate.wait()
        if self.fail_writes:
            raise RuntimeError("injected session write failure")
        self.documents[conversation_id] = dict(document)


class FakeTurnModel:
    """Deterministic TurnModel double; records calls, returns a canned decision."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.decision = ModelTurnDecision(message="synthetic message", route=Route.CONTINUE)
        self.error: Exception | None = None

    async def decide(
        self,
        *,
        transcript: str,
        goal: ConversationGoal | None,
        identity_validated: bool,
        confirmation: ConfirmationChallenge | None,
        external_operation: ExternalOperation | None,
        memory_context: str | None = None,
    ) -> ModelTurnDecision:
        self.calls.append(
            {
                "transcript": transcript,
                "goal": goal,
                "identity_validated": identity_validated,
                "confirmation": confirmation,
                "external_operation": external_operation,
                "memory_context": memory_context,
            }
        )
        if self.error is not None:
            raise self.error
        return self.decision


def make_goal(action: Action, revision: int = 1) -> ConversationGoal:
    return ConversationGoal(action=action, revision=revision)


def make_identity(validated_at: datetime | None = None, *, failures: int = 0) -> IdentityState:
    return IdentityState(validated_at=validated_at, caller_failures=failures)


def make_challenge(
    action: Action,
    *,
    revision: int = 1,
    identity_validated_at: datetime = NOW,
    challenge_id: str = "challenge-1",
) -> ConfirmationChallenge:
    return ConfirmationChallenge(
        challenge_id=challenge_id,
        action=action,
        goal_revision=revision,
        identity_validated_at=identity_validated_at,
        issued_at=identity_validated_at,
    )


def make_dispatch(
    action: Action,
    *,
    revision: int = 1,
    challenge_id: str = "challenge-1",
    operation_id: str = "operation-1",
) -> AuthorizedDispatch:
    return AuthorizedDispatch(
        operation_id=operation_id,
        action=action,
        goal_revision=revision,
        challenge_id=challenge_id,
        authorized_at=NOW,
    )


def make_operation(
    action: Action,
    status: OperationStatus = OperationStatus.PENDING,
    *,
    delivery: DeliveryStatus | None = None,
    operation_id: str = "operation-1",
    last_progress_feedback_at: datetime | None = None,
    progress_feedback_index: int = 0,
) -> ExternalOperation:
    return ExternalOperation(
        operation_id=operation_id,
        action=action,
        status=status,
        delivery=delivery,
        last_progress_feedback_at=last_progress_feedback_at,
        progress_feedback_index=progress_feedback_index,
    )


def make_record(**overrides: object) -> SessionRecord:
    """Build a complete v2 record; overrides replace whole semantic planes."""
    values: dict[str, object] = {
        "conversation_id": "conversation-1",
        "turn_count": 2,
        "revision": 2,
        "goal": make_goal(Action.RESET_PASSWORD),
        "identity": make_identity(NOW),
        "confirmation": None,
        "dispatch": None,
        "external_operation": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return SessionRecord.model_validate(values)


def make_decision(**overrides: object) -> ModelTurnDecision:
    values: dict[str, object] = {"message": "synthetic message", "route": Route.CONTINUE}
    values.update(overrides)
    return ModelTurnDecision.model_validate(values)


def make_outcome(**overrides: object) -> TurnOutcomeState:
    values: dict[str, object] = {"message": "synthetic message", "route": BoundaryRoute.CONTINUE}
    values.update(overrides)
    return TurnOutcomeState.model_validate(values)


def make_state(**overrides: object) -> GraphState:
    """Minimal ephemeral state for deterministic reducer tests."""
    state: dict[str, object] = {
        "conversation_id": "conversation-1",
        "goal": None,
        "identity": make_identity(),
        "confirmation": None,
        "dispatch": None,
        "external_operation": None,
        "experimental_config": None,
        "experimental_procedure": None,
        "experimental_suspended": None,
        "experimental_window": (),
        "memory_render_ms": None,
        "memory_decode_ms": 0.0,
        "memory_encode_ms": None,
        "now": NOW,
        "transcript": None,
        "identity_outcome": None,
        "confirmation_event": None,
        "external_event": None,
        "model_decision": None,
        "outcome": None,
    }
    state.update(overrides)
    return GraphState(**state)  # type: ignore[typeddict-item]
