"""Turn cycle tests: continuity, durability, crash, ordering and PII closure."""

import asyncio
import copy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.conversation.errors import ModelTimeoutError
from app.session.metrics import RecordingTurnMetrics
from app.session.record import Action, OperationStatus, SessionRecord
from app.session.repository import SessionPersistenceError
from app.session.service import TurnService
from app.session.turns import (
    ModelTurnDecision,
    Route,
    TurnInput,
    build_turn_graph,
    initial_graph_state,
)

DOCUMENT_WHITELIST = {
    "schema_version",
    "conversation_id",
    "turn_count",
    "revision",
    "identity_validated",
    "requested_action",
    "pending_operation",
    "created_at",
    "updated_at",
}

TRANSIENT_STATE_KEYS = {
    "identity_ok",
    "action_requested",
    "operation_result",
    "transcript",
    "model_decision",
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


async def test_first_turn_creates_a_valid_semantic_session(service, store) -> None:
    result = await service.handle_turn("conversation-new", TurnInput())
    record = result.record
    assert record.conversation_id == "conversation-new"
    assert record.schema_version == 1
    assert record.turn_count == 1
    assert record.revision == 1
    assert record.identity_validated is False
    assert record.created_at <= record.updated_at
    assert set(store.documents["conversation-new"]) == DOCUMENT_WHITELIST
    assert result.decision is None


async def test_normal_turn_is_exactly_one_read_and_one_write(service, store) -> None:
    await service.handle_turn("conversation-1", TurnInput())
    assert (store.reads, store.writes) == (1, 1)
    await service.handle_turn("conversation-1", TurnInput())
    assert (store.reads, store.writes) == (2, 2)
    assert len(store.documents) == 1


async def test_multi_turn_continuity(service, store) -> None:
    first = await service.handle_turn("conversation-1", TurnInput(identity_ok=True))
    second = await service.handle_turn(
        "conversation-1", TurnInput(action_requested=Action.RESET_PASSWORD)
    )
    assert first.record.turn_count == 1
    assert second.record.turn_count == 2
    assert second.record.revision == 2
    assert second.record.identity_validated is True
    assert second.record.requested_action is Action.RESET_PASSWORD
    stored = store.documents["conversation-1"]
    assert stored["turn_count"] == 2
    assert stored["revision"] == 2
    assert stored["identity_validated"] is True


async def test_pending_operation_is_durable_across_turns(service, store) -> None:
    created = await service.handle_turn(
        "conversation-1", TurnInput(identity_ok=True, action_requested=Action.UNLOCK_ACCOUNT)
    )
    record = created.record
    assert record.pending_operation is not None
    operation_id = record.pending_operation.operation_id
    assert store.documents["conversation-1"]["pending_operation"] == {
        "operation_id": operation_id,
        "action": "UNLOCK_ACCOUNT",
        "status": "pending",
    }

    repeated = await service.handle_turn(
        "conversation-1", TurnInput(action_requested=Action.UNLOCK_ACCOUNT)
    )
    assert repeated.record.pending_operation is not None
    assert repeated.record.pending_operation.operation_id == operation_id
    assert repeated.record.pending_operation.status is OperationStatus.PENDING

    resolved = await service.handle_turn(
        "conversation-1", TurnInput(operation_result=OperationStatus.CONFIRMED)
    )
    assert resolved.record.pending_operation is not None
    assert resolved.record.pending_operation.operation_id == operation_id
    assert resolved.record.pending_operation.status is OperationStatus.CONFIRMED
    assert store.documents["conversation-1"]["pending_operation"] == {
        "operation_id": operation_id,
        "action": "UNLOCK_ACCOUNT",
        "status": "confirmed",
    }


async def test_crash_before_save_keeps_the_last_durable_state(service, store) -> None:
    await service.handle_turn("conversation-1", TurnInput(identity_ok=True))
    durable_before = copy.deepcopy(store.documents["conversation-1"])

    store.fail_writes = True
    with pytest.raises(SessionPersistenceError):
        await service.handle_turn(
            "conversation-1", TurnInput(action_requested=Action.RESET_PASSWORD)
        )
    assert store.documents["conversation-1"] == durable_before

    store.fail_writes = False
    resumed = await service.handle_turn("conversation-1", TurnInput())
    assert resumed.record.turn_count == 2
    assert resumed.record.pending_operation is None
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
        "conversation-1", TurnInput(identity_ok=True, action_requested=Action.RESET_PASSWORD)
    )
    document = store.documents["conversation-1"]
    assert set(document) == DOCUMENT_WHITELIST
    assert TRANSIENT_STATE_KEYS.isdisjoint(document)
    assert GRAPH_OR_RUNTIME_KEYS.isdisjoint(document)


async def test_ephemeral_state_only_exists_in_ram() -> None:
    record = SessionRecord.new("conversation-1", now=datetime(2026, 9, 15, 12, 0, tzinfo=UTC))
    state = initial_graph_state(
        record, TurnInput(identity_ok=True, action_requested=Action.UNLOCK_ACCOUNT)
    )
    assert state["identity_ok"] is True
    final = await build_turn_graph().ainvoke(state)
    assert final["identity_ok"] is True
    assert final["action_requested"] is Action.UNLOCK_ACCOUNT
    assert final["pending_operation"] is not None


def test_transient_turn_input_rejects_unwhitelisted_pii_fields() -> None:
    with pytest.raises(ValidationError):
        TurnInput(identity_ok=True, document_number="SYNTHETIC-DOC-0000")


async def test_full_turn_persists_no_pii_sentinels(service, store) -> None:
    await service.handle_turn(
        "conversation-1", TurnInput(identity_ok=True, action_requested=Action.RESET_PASSWORD)
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


async def test_model_inferred_action_without_identity_is_never_durable(
    service_with_model, model, store
) -> None:
    model.decision = ModelTurnDecision(
        message="synthetic message",
        route=Route.COLLECT_IDENTITY,
        action_requested=Action.UNLOCK_ACCOUNT,
    )
    result = await service_with_model.handle_turn(
        "conversation-1", TurnInput(transcript="synthetic transcript 0000")
    )
    assert result.decision is not None
    assert result.decision.action_requested is Action.UNLOCK_ACCOUNT
    assert result.record.requested_action is None
    assert result.record.pending_operation is None
    assert store.documents["conversation-1"]["requested_action"] is None


async def test_segments_are_recorded_through_the_metrics_seam(repository) -> None:
    metrics = RecordingTurnMetrics()
    service = TurnService(repository, build_turn_graph(), metrics=metrics)
    await service.handle_turn("conversation-1", TurnInput())
    names = [name for name, _ in metrics.segments]
    assert names == ["session_load", "graph", "session_save"]
    assert all(duration >= 0 for _, duration in metrics.segments)
