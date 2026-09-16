"""Turn cycle tests: continuity, durability, crash, ordering and PII closure."""

import asyncio
import copy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.session.record import Action, OperationStatus, SessionRecord
from app.session.repository import SessionPersistenceError
from app.session.turns import TurnInput, build_turn_graph, initial_graph_state

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

TRANSIENT_STATE_KEYS = {"identity_ok", "action_requested", "operation_result"}

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
    record = await service.handle_turn("conversation-new", TurnInput())
    assert record.conversation_id == "conversation-new"
    assert record.schema_version == 1
    assert record.turn_count == 1
    assert record.revision == 1
    assert record.identity_validated is False
    assert record.created_at <= record.updated_at
    assert set(store.documents["conversation-new"]) == DOCUMENT_WHITELIST


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
    assert first.turn_count == 1
    assert second.turn_count == 2
    assert second.revision == 2
    assert second.identity_validated is True
    assert second.requested_action is Action.RESET_PASSWORD
    stored = store.documents["conversation-1"]
    assert stored["turn_count"] == 2
    assert stored["revision"] == 2
    assert stored["identity_validated"] is True


async def test_pending_operation_is_durable_across_turns(service, store) -> None:
    created = await service.handle_turn(
        "conversation-1", TurnInput(identity_ok=True, action_requested=Action.UNLOCK_ACCOUNT)
    )
    assert created.pending_operation is not None
    operation_id = created.pending_operation.operation_id
    assert store.documents["conversation-1"]["pending_operation"] == {
        "operation_id": operation_id,
        "action": "UNLOCK_ACCOUNT",
        "status": "pending",
    }

    repeated = await service.handle_turn(
        "conversation-1", TurnInput(action_requested=Action.UNLOCK_ACCOUNT)
    )
    assert repeated.pending_operation is not None
    assert repeated.pending_operation.operation_id == operation_id
    assert repeated.pending_operation.status is OperationStatus.PENDING

    resolved = await service.handle_turn(
        "conversation-1", TurnInput(operation_result=OperationStatus.CONFIRMED)
    )
    assert resolved.pending_operation is not None
    assert resolved.pending_operation.operation_id == operation_id
    assert resolved.pending_operation.status is OperationStatus.CONFIRMED
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
    assert resumed.turn_count == 2
    assert resumed.pending_operation is None
    assert store.documents["conversation-1"]["turn_count"] == 2


async def test_save_completes_before_control_returns(service, store) -> None:
    store.write_gate = asyncio.Event()
    task = asyncio.create_task(service.handle_turn("conversation-1", TurnInput()))
    await store.write_started.wait()
    assert not task.done()
    assert "conversation-1" not in store.documents

    store.write_gate.set()
    record = await task
    assert record.revision == 1
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
