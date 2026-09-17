"""Async repository for the durable SessionRecord.

One load and one save per normal turn. Reads and writes go through a narrow
document seam so tests can substitute a deterministic double; the Firestore
adapter is the only production implementation.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

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

    async def save(self, record: SessionRecord) -> None:
        """Persist the consolidated record; the caller awaits completion."""
        try:
            document = session_record_to_document(record)
            await self._store.write(record.conversation_id, document)
        except Exception as exc:
            raise SessionPersistenceError("session save failed") from exc
