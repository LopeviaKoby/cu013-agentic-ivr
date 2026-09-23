"""Turn cycle tests: continuity, durability, migration, crash and PII closure."""

import asyncio
import copy

import pytest
from pydantic import ValidationError

from app.conversation.errors import ModelTimeoutError
from app.session.metrics import RecordingTurnMetrics
from app.session.record import Action, OperationStatus, SessionRecord
from app.session.repository import SessionPersistenceError
from app.session.service import TurnService
from app.session.turns import (
    IdentityOutcome,
    Route,
    TurnInput,
    build_turn_graph,
    initial_graph_state,
)
from tests.session.doubles import NOW, make_decision

DOCUMENT_WHITELIST = {
    "schema_version",
    "conversation_id",
    "turn_count",
    "revision",
    "goal",
    "identity",
    "confirmation",
    "dispatch",
    "external_operation",
    "polling",
    "password_presentation",
    "created_at",
    "updated_at",
}

TRANSIENT_STATE_KEYS = {
    "now",
    "transcript",
    "identity_outcome",
    "confirmation_event",
    "external_event",
    "model_decision",
    "outcome",
}

GRAPH_OR_RUNTIME_KEYS = {
    "messages",
    "tools",
    "tool_schemas",
    "checkpointer",
    "checkpoint",
    "graph_state",
}

PII_SENTINELS = ("SYNTHETIC-DOC-0000", "1900-01-01-SYNTHETIC", "SYNTHETIC-PASSWORD-0000")

V1_DOCUMENT = {
    "schema_version": 1,
    "conversation_id": "conversation-legacy",
    "turn_count": 4,
    "revision": 4,
    "identity_validated": True,
    "requested_action": "UNLOCK_ACCOUNT",
    "pending_operation": {
        "operation_id": "operation-legacy",
        "action": "UNLOCK_ACCOUNT",
        "status": "pending",
    },
    "created_at": NOW,
    "updated_at": NOW,
}


async def test_first_turn_creates_a_valid_semantic_session(service, store) -> None:
    result = await service.handle_turn("conversation-new", TurnInput())
    record = result.record
    assert record.conversation_id == "conversation-new"
    assert record.schema_version == 3
    assert record.turn_count == 1
    assert record.revision == 1
    assert record.identity.validated_at is None
    assert record.created_at <= record.updated_at
    assert set(store.documents["conversation-new"]) == DOCUMENT_WHITELIST
    assert result.decision is None
    assert result.outcome is None


async def test_normal_turn_is_exactly_one_read_and_one_write(service, store) -> None:
    await service.handle_turn("conversation-1", TurnInput())
    assert (store.reads, store.writes) == (1, 1)
    await service.handle_turn("conversation-1", TurnInput())
    assert (store.reads, store.writes) == (2, 2)
    assert len(store.documents) == 1


async def test_multi_turn_continuity(service, store) -> None:
    first = await service.handle_turn(
        "conversation-1", TurnInput(identity_outcome=IdentityOutcome.VALIDATED)
    )
    second = await service.handle_turn("conversation-1", TurnInput())
    assert first.record.turn_count == 1
    assert second.record.turn_count == 2
    assert second.record.revision == 2
    assert second.record.identity.validated_at == NOW
    stored = store.documents["conversation-1"]
    assert stored["turn_count"] == 2
    assert stored["revision"] == 2
    assert stored["identity"]["validated_at"] == NOW  # type: ignore[index]


async def test_goal_and_authorization_are_durable_in_separate_planes(
    service_with_model, model, store
) -> None:
    model.decision = make_decision(
        route=Route.COLLECT_IDENTITY,
        goal={"intent": "REQUEST", "action": "UNLOCK_ACCOUNT"},
    )
    planned = await service_with_model.handle_turn(
        "conversation-1", TurnInput(transcript="synthetic transcript 0000")
    )
    assert planned.record.goal is not None
    assert planned.record.goal.action is Action.UNLOCK_ACCOUNT
    assert planned.record.identity.validated_at is None
    assert planned.record.dispatch is None
    assert planned.record.external_operation is None
    assert store.documents["conversation-1"]["goal"] == {
        "action": "UNLOCK_ACCOUNT",
        "revision": 1,
    }
    assert store.documents["conversation-1"]["dispatch"] is None


async def test_operation_truth_is_durable_across_turns(service_with_model, model, store) -> None:
    model.decision = make_decision(
        route=Route.COLLECT_IDENTITY,
        goal={"intent": "REQUEST", "action": "UNLOCK_ACCOUNT"},
    )
    await service_with_model.handle_turn(
        "conversation-1", TurnInput(transcript="synthetic transcript 0000")
    )
    await service_with_model.handle_turn(
        "conversation-1", TurnInput(identity_outcome=IdentityOutcome.VALIDATED)
    )
    model.decision = make_decision(confirmation_request=True, route=Route.CONTINUE)
    challenged = await service_with_model.handle_turn(
        "conversation-1", TurnInput(transcript="synthetic transcript 0001")
    )
    assert challenged.record.confirmation is not None
    assert challenged.record.dispatch is None

    model.decision = make_decision(confirmation_observation="AFFIRMATIVE", route=Route.CONTINUE)
    authorized = await service_with_model.handle_turn(
        "conversation-1", TurnInput(transcript="synthetic transcript 0002")
    )
    assert authorized.record.dispatch is not None
    assert authorized.record.external_operation is not None
    operation_id = authorized.record.external_operation.operation_id
    assert authorized.record.confirmation is None
    assert store.documents["conversation-1"]["external_operation"] == {
        "operation_id": operation_id,
        "action": "UNLOCK_ACCOUNT",
        "status": "pending",
        "delivery": None,
        "last_progress_feedback_at": NOW,
        "progress_feedback_index": 0,
    }


async def test_crash_before_save_keeps_the_last_durable_state(service, store) -> None:
    await service.handle_turn("conversation-1", TurnInput(identity_outcome="VALIDATED"))
    durable_before = copy.deepcopy(store.documents["conversation-1"])

    store.fail_writes = True
    with pytest.raises(SessionPersistenceError):
        await service.handle_turn("conversation-1", TurnInput())
    assert store.documents["conversation-1"] == durable_before

    store.fail_writes = False
    resumed = await service.handle_turn("conversation-1", TurnInput())
    assert resumed.record.turn_count == 2
    assert resumed.record.external_operation is None
    assert store.documents["conversation-1"]["turn_count"] == 2


async def test_save_completes_before_control_returns(service, store) -> None:
    store.write_gate = asyncio.Event()
    task = asyncio.create_task(service.handle_turn("conversation-1", TurnInput()))
    await store.write_started.wait()
    assert not task.done()
    assert "conversation-1" not in store.documents

    store.write_gate.set()
    result = await task
    assert result.record.revision == 1
    assert "conversation-1" in store.documents


async def test_graph_state_is_never_persisted(service, store) -> None:
    await service.handle_turn(
        "conversation-1", TurnInput(identity_outcome=IdentityOutcome.VALIDATED)
    )
    document = store.documents["conversation-1"]
    assert set(document) == DOCUMENT_WHITELIST
    assert TRANSIENT_STATE_KEYS.isdisjoint(document)
    assert GRAPH_OR_RUNTIME_KEYS.isdisjoint(document)


async def test_ephemeral_state_only_exists_in_ram() -> None:
    record = SessionRecord.new("conversation-1", now=NOW)
    state = initial_graph_state(record, TurnInput(identity_outcome="VALIDATED"), now=NOW)
    assert state["identity"].validated_at is None
    final = await build_turn_graph().ainvoke(state)
    assert final["identity"].validated_at == NOW
    assert final["dispatch"] is None


def test_transient_turn_input_rejects_unwhitelisted_pii_fields() -> None:
    with pytest.raises(ValidationError):
        TurnInput(identity_outcome="VALIDATED", document_number="SYNTHETIC-DOC-0000")


async def test_full_turn_persists_no_pii_sentinels(service, store) -> None:
    await service.handle_turn(
        "conversation-1", TurnInput(identity_outcome=IdentityOutcome.VALIDATED)
    )
    rendered = repr(store.documents["conversation-1"])
    for sentinel in PII_SENTINELS:
        assert sentinel not in rendered


async def test_transcript_turn_runs_one_model_call_and_one_load_one_save(
    service_with_model, model, store
) -> None:
    result = await service_with_model.handle_turn(
        "conversation-1", TurnInput(transcript="synthetic transcript 0000")
    )
    assert result.record.conversation_id == "conversation-1"
    assert result.decision is model.decision
    assert result.outcome is not None
    assert result.outcome.message == model.decision.message
    assert len(model.calls) == 1
    assert (store.reads, store.writes) == (1, 1)
    document = store.documents["conversation-1"]
    assert set(document) == DOCUMENT_WHITELIST
    assert "transcript" not in document
    assert "message" not in document
    assert "synthetic message" not in repr(document)


async def test_transcript_and_model_output_never_reach_the_second_turn(
    service_with_model, model
) -> None:
    await service_with_model.handle_turn(
        "conversation-1", TurnInput(transcript="synthetic transcript 0000")
    )
    await service_with_model.handle_turn(
        "conversation-1", TurnInput(transcript="synthetic transcript 0001")
    )
    assert len(model.calls) == 2
    assert model.calls[1]["transcript"] == "synthetic transcript 0001"
    assert model.calls[1]["identity_validated"] is False


async def test_model_failure_aborts_before_the_save(service_with_model, model, store) -> None:
    await service_with_model.handle_turn(
        "conversation-1", TurnInput(transcript="synthetic transcript 0000")
    )
    durable_before = copy.deepcopy(store.documents["conversation-1"])

    model.error = ModelTimeoutError("synthetic model timeout")
    with pytest.raises(ModelTimeoutError):
        await service_with_model.handle_turn(
            "conversation-1", TurnInput(transcript="synthetic transcript 0001")
        )
    assert store.documents["conversation-1"] == durable_before
    assert store.writes == 1


async def test_model_goal_without_identity_is_never_dispatchable(
    service_with_model, model, store
) -> None:
    model.decision = make_decision(
        route=Route.COLLECT_IDENTITY,
        goal={"intent": "REQUEST", "action": "UNLOCK_ACCOUNT"},
    )
    result = await service_with_model.handle_turn(
        "conversation-1", TurnInput(transcript="synthetic transcript 0000")
    )
    assert result.record.goal is not None
    assert result.record.identity.validated_at is None
    assert result.record.dispatch is None
    assert result.record.external_operation is None
    assert store.documents["conversation-1"]["dispatch"] is None


async def test_migrated_legacy_identity_never_authorizes_through_the_service(
    service_with_model, model, store
) -> None:
    store.documents["conversation-legacy"] = dict(V1_DOCUMENT)
    model.decision = make_decision(confirmation_request=True, route=Route.CONTINUE)
    result = await service_with_model.handle_turn(
        "conversation-legacy", TurnInput(transcript="synthetic transcript 0000")
    )
    assert result.record.identity.validated_at is None
    assert result.record.confirmation is None
    assert result.record.dispatch is None
    assert store.documents["conversation-legacy"]["schema_version"] == 3


async def test_pending_operation_legacy_status_is_preserved_on_migration(service, store) -> None:
    store.documents["conversation-legacy"] = dict(V1_DOCUMENT)
    result = await service.handle_turn("conversation-legacy", TurnInput())
    assert result.record.external_operation is not None
    assert result.record.external_operation.operation_id == "operation-legacy"
    assert result.record.external_operation.status is OperationStatus.PENDING
    assert result.record.dispatch is None


async def test_segments_are_recorded_through_the_metrics_seam(repository, clock) -> None:
    metrics = RecordingTurnMetrics()
    service = TurnService(repository, build_turn_graph(), metrics=metrics, clock=clock)
    await service.handle_turn("conversation-1", TurnInput())
    names = [name for name, _ in metrics.segments]
    assert names == ["session_load", "graph", "session_save"]
    assert all(duration >= 0 for _, duration in metrics.segments)
