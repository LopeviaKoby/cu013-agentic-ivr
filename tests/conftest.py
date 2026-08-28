from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.firestore import SessionData, reset_firestore_client
from app.gemini import reset_genai_client
from app.main import app


class InMemoryFirestoreMock:
    """Hermetic in-memory test double for Firestore AsyncClient."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}

    def collection(self, name: str) -> "InMemoryCollectionMock":
        return InMemoryCollectionMock(self.store, name)


class InMemoryCollectionMock:
    def __init__(self, store: dict[str, dict[str, Any]], name: str) -> None:
        self.store = store
        self.name = name

    def document(self, doc_id: str) -> "InMemoryDocumentMock":
        return InMemoryDocumentMock(self.store, self.name, doc_id)


class InMemoryDocumentMock:
    def __init__(self, store: dict[str, dict[str, Any]], col_name: str, doc_id: str) -> None:
        self.store = store
        self.col_name = col_name
        self.doc_id = doc_id
        self._key = f"{col_name}/{doc_id}"

    async def get(self) -> "InMemorySnapshotMock":
        data = self.store.get(self._key)
        return InMemorySnapshotMock(data)

    async def set(self, data: dict[str, Any]) -> None:
        self.store[self._key] = dict(data)


class InMemorySnapshotMock:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return self._data


@pytest.fixture(autouse=True)
def cleanup_clients() -> None:
    """Reset singletons before each test."""
    reset_genai_client()
    reset_firestore_client()


@pytest.fixture
def mock_firestore() -> InMemoryFirestoreMock:
    """Provide a fresh in-memory Firestore mock."""
    return InMemoryFirestoreMock()


@pytest.fixture
async def async_client(
    mock_firestore: InMemoryFirestoreMock, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient, None]:
    """Provide an AsyncClient for FastAPI endpoint testing with Firestore mocked."""

    async def mock_get_session(conv_id: str, client: Any = None) -> SessionData | None:
        from app.firestore import get_session

        return await get_session(conv_id, client=mock_firestore)  # type: ignore[arg-type]

    async def mock_save_session(session: SessionData, client: Any = None) -> None:
        from app.firestore import save_session

        await save_session(session, client=mock_firestore)  # type: ignore[arg-type]

    async def mock_gemini_turn(
        contents: Any, system_instruction: Any = None, client: Any = None
    ) -> tuple[Any, float]:
        from app.contracts import ModelTurnOutput

        return ModelTurnOutput(response_text="Entendido, te puedo ayudar con tu solicitud."), 45.0

    monkeypatch.setattr("app.main.get_session", mock_get_session)
    monkeypatch.setattr("app.main.save_session", mock_save_session)
    monkeypatch.setattr("app.graph.generate_turn_response_async", mock_gemini_turn)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
