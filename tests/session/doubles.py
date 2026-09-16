"""Deterministic in-memory double for the narrow session document seam."""

import asyncio
from collections.abc import Mapping


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
