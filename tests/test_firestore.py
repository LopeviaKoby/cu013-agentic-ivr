import pytest

from app.firestore import SessionData, get_session, save_session
from tests.conftest import InMemoryFirestoreMock


def test_session_data_serialization_roundtrip() -> None:
    """SessionData to_dict and from_dict preserve all properties."""
    original = SessionData(
        conversation_id="conv-12345",
        turn_count=3,
        turns=[
            {
                "turn_id": "turn-1",
                "user_text": "Hola",
                "bot_text": "Buenas",
                "route": "CONTINUE",
            }
        ],
        created_at="2026-08-28T12:00:00+00:00",
        updated_at="2026-08-28T12:01:00+00:00",
    )

    serialized = original.to_dict()
    assert isinstance(serialized, dict)
    assert serialized["conversation_id"] == "conv-12345"
    assert serialized["turn_count"] == 3
    assert len(serialized["turns"]) == 1

    restored = SessionData.from_dict(serialized)
    assert restored.conversation_id == original.conversation_id
    assert restored.turn_count == original.turn_count
    assert restored.turns == original.turns
    assert restored.created_at == original.created_at
    assert restored.updated_at == original.updated_at


@pytest.mark.asyncio
async def test_firestore_save_and_get_session(
    mock_firestore: InMemoryFirestoreMock,
) -> None:
    """Saving a session to Firestore and retrieving it yields equivalent state."""
    session = SessionData(
        conversation_id="conv-persistent-test",
        turn_count=1,
        turns=[{"turn_id": "t-1", "user_text": "VPN no conecta"}],
    )

    # Save to mock Firestore
    await save_session(session, client=mock_firestore)  # type: ignore[arg-type]

    # Retrieve from mock Firestore
    loaded = await get_session("conv-persistent-test", client=mock_firestore)  # type: ignore[arg-type]

    assert loaded is not None
    assert loaded.conversation_id == "conv-persistent-test"
    assert loaded.turn_count == 1
    assert len(loaded.turns) == 1
    assert loaded.turns[0]["user_text"] == "VPN no conecta"


@pytest.mark.asyncio
async def test_firestore_get_nonexistent_session_returns_none(
    mock_firestore: InMemoryFirestoreMock,
) -> None:
    """Querying a non-existent conversation_id returns None."""
    loaded = await get_session("nonexistent-conv-id", client=mock_firestore)  # type: ignore[arg-type]
    assert loaded is None
