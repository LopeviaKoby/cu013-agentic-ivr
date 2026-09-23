"""Async repository for the durable SessionRecord.

One load and one save per normal turn. Reads and writes go through a narrow
document seam so tests can substitute a deterministic double; the Firestore
adapter is the only production implementation.

``load_existing`` answers real existence for the technical lane, and
``create_if_absent`` is the only primitive allowed to create a session from a
technical event: it relies on the backend create-only precondition instead of
a read-then-write race.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore import AsyncClient

from app.session.record import (
    SessionRecord,
    session_record_from_document,
    session_record_to_document,
)


class SessionPersistenceError(RuntimeError):
    """A durable session read, write or validation failed."""


class SessionDocumentStore(Protocol):
    """Narrow async document seam implemented by Firestore and by test doubles."""

    async def read(self, conversation_id: str) -> Mapping[str, object] | None: ...

    async def write(self, conversation_id: str, document: Mapping[str, object]) -> None: ...

    async def create(self, conversation_id: str, document: Mapping[str, object]) -> bool: ...


class FirestoreSessionDocumentStore:
    """Firestore adapter for exactly one session collection."""

    def __init__(self, client: AsyncClient, collection: str) -> None:
        self._collection = client.collection(collection)

    async def read(self, conversation_id: str) -> Mapping[str, object] | None:
        snapshot = await self._collection.document(conversation_id).get()
        if not snapshot.exists:
            return None
        return snapshot.to_dict()

    async def write(self, conversation_id: str, document: Mapping[str, object]) -> None:
        await self._collection.document(conversation_id).set(dict(document))

    async def create(self, conversation_id: str, document: Mapping[str, object]) -> bool:
        """Create only when the document does not exist; never overwrite."""
        try:
            await self._collection.document(conversation_id).create(dict(document))
        except AlreadyExists:
            return False
        return True


class SessionRepository:
    """Loads and saves the durable SessionRecord for one conversation."""

    def __init__(self, store: SessionDocumentStore) -> None:
        self._store = store

    async def load(self, conversation_id: str, *, now: datetime | None = None) -> SessionRecord:
        """Return the durable record, or a fresh semantic one when none exists.

        The caller may pass its injected turn clock so a brand-new record is
        stamped with the same ``now`` the rest of the turn uses; without one
        the wall clock is used.
        """
        try:
            document = await self._store.read(conversation_id)
            if document is None:
                return SessionRecord.new(conversation_id, now=now or datetime.now(UTC))
            return session_record_from_document(document)
        except Exception as exc:
            raise SessionPersistenceError("session load failed") from exc

    async def load_existing(self, conversation_id: str) -> SessionRecord | None:
        """Return the stored record, or None when no document exists.

        Unlike ``load`` this never fabricates a record: the technical lane must
        distinguish a missing session from a durable pre-turn one.
        """
        try:
            document = await self._store.read(conversation_id)
            if document is None:
                return None
            return session_record_from_document(document)
        except Exception as exc:
            raise SessionPersistenceError("session load failed") from exc

    async def create_if_absent(self, record: SessionRecord) -> bool:
        """Create the record only when absent; False when it already exists."""
        try:
            document = session_record_to_document(record)
            return await self._store.create(record.conversation_id, document)
        except Exception as exc:
            raise SessionPersistenceError("session create failed") from exc

    async def save(self, record: SessionRecord) -> None:
        """Persist the consolidated record; the caller awaits completion."""
        try:
            document = session_record_to_document(record)
            await self._store.write(record.conversation_id, document)
        except Exception as exc:
            raise SessionPersistenceError("session save failed") from exc
