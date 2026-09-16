"""Repository tests: async surface, missing session, round-trip and errors."""

import inspect
from datetime import UTC, datetime

import pytest

from app.session.record import Action, OperationStatus, PendingOperation, SessionRecord
from app.session.repository import (
    FirestoreSessionDocumentStore,
    SessionPersistenceError,
    SessionRepository,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


class FakeSnapshot:
    def __init__(self, data: dict[str, object] | None) -> None:
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict[str, object] | None:
        return self._data


class FakeDocumentReference:
    def __init__(self, documents: dict[str, dict[str, object]], conversation_id: str) -> None:
        self._documents = documents
        self._conversation_id = conversation_id

    async def get(self) -> FakeSnapshot:
        return FakeSnapshot(self._documents.get(self._conversation_id))

    async def set(self, document: dict[str, object]) -> None:
        self._documents[self._conversation_id] = document


class FakeCollectionReference:
    def __init__(self, documents: dict[str, dict[str, object]]) -> None:
        self._documents = documents

    def document(self, conversation_id: str) -> FakeDocumentReference:
        return FakeDocumentReference(self._documents, conversation_id)


class FakeAsyncClient:
    """Minimal async-client double; only the surface the adapter uses."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, object]] = {}
        self.collection_name: str | None = None

    def collection(self, name: str) -> FakeCollectionReference:
        self.collection_name = name
        return FakeCollectionReference(self.documents)


async def test_missing_session_loads_as_a_fresh_semantic_record(store) -> None:
    repository = SessionRepository(store)
    record = await repository.load("conversation-1")
    assert record.schema_version == 1
    assert record.conversation_id == "conversation-1"
    assert record.turn_count == 0
    assert record.revision == 0
    assert record.identity_validated is False
    assert record.requested_action is None
    assert record.pending_operation is None
    assert record.created_at.tzinfo is not None
    assert store.reads == 1
    assert store.writes == 0


async def test_save_and_load_round_trip(store) -> None:
    repository = SessionRepository(store)
    record = SessionRecord(
        schema_version=1,
        conversation_id="conversation-1",
        turn_count=3,
        revision=3,
        identity_validated=True,
        requested_action=Action.UNLOCK_ACCOUNT,
        pending_operation=PendingOperation(
            operation_id="operation-1",
            action=Action.UNLOCK_ACCOUNT,
            status=OperationStatus.CONFIRMED,
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    await repository.save(record)
    assert await repository.load("conversation-1") == record


async def test_load_rejects_a_document_with_unwhitelisted_fields(store) -> None:
    store.documents["conversation-1"] = {
        "schema_version": 1,
        "conversation_id": "conversation-1",
        "document_number": "SYNTHETIC-DOC-0000",
    }
    repository = SessionRepository(store)
    with pytest.raises(SessionPersistenceError):
        await repository.load("conversation-1")


async def test_write_failure_surfaces_as_a_persistence_error(store) -> None:
    store.fail_writes = True
    repository = SessionRepository(store)
    with pytest.raises(SessionPersistenceError):
        await repository.save(SessionRecord.new("conversation-1", now=NOW))
    assert store.writes == 1
    assert store.documents == {}


async def test_firestore_adapter_reads_and_writes_one_collection() -> None:
    client = FakeAsyncClient()
    document_store = FirestoreSessionDocumentStore(
        client,  # type: ignore[arg-type]
        "cu013_test_sessions",
    )
    assert client.collection_name == "cu013_test_sessions"
    assert await document_store.read("conversation-1") is None
    await document_store.write("conversation-1", {"conversation_id": "conversation-1"})
    assert await document_store.read("conversation-1") == {"conversation_id": "conversation-1"}


def test_repository_and_adapter_surfaces_are_async() -> None:
    assert inspect.iscoroutinefunction(SessionRepository.load)
    assert inspect.iscoroutinefunction(SessionRepository.save)
    assert inspect.iscoroutinefunction(FirestoreSessionDocumentStore.read)
    assert inspect.iscoroutinefunction(FirestoreSessionDocumentStore.write)
