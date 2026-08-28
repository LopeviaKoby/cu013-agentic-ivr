from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.contracts import ModelTurnOutput, Route
from app.firestore import get_session
from tests.conftest import InMemoryFirestoreMock


@pytest.mark.asyncio
async def test_turn_endpoint_valid_request(async_client: AsyncClient) -> None:
    """POST /turn with valid payload returns HTTP 200 and conforming response schema."""
    payload = {
        "conversation_id": "Ivr02-test-12345",
        "text": "Estoy en Perú y uso FortiClient",
    }
    response = await async_client.post("/turn", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "turn_id" in data
    assert data["turn_id"].startswith("turn-")
    assert data["route"] in [r.value for r in Route]
    assert isinstance(data["text"], str)
    assert len(data["text"]) > 0


@pytest.mark.asyncio
async def test_turn_endpoint_rejects_missing_conversation_id(
    async_client: AsyncClient,
) -> None:
    """POST /turn without conversation_id returns HTTP 422 validation error."""
    payload = {"text": "Hola mundo"}
    response = await async_client.post("/turn", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_turn_endpoint_rejects_blank_conversation_id(
    async_client: AsyncClient,
) -> None:
    """POST /turn with blank/whitespace conversation_id returns HTTP 422 validation error."""
    payload = {"conversation_id": "   ", "text": "Hola mundo"}
    response = await async_client.post("/turn", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_turn_endpoint_rejects_missing_text(async_client: AsyncClient) -> None:
    """POST /turn without text returns HTTP 422 validation error."""
    payload = {"conversation_id": "Ivr02-test-12345"}
    response = await async_client.post("/turn", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_turn_endpoint_rejects_blank_text(async_client: AsyncClient) -> None:
    """POST /turn with blank/whitespace text returns HTTP 422 validation error."""
    payload = {"conversation_id": "Ivr02-test-12345", "text": "   "}
    response = await async_client.post("/turn", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_turn_endpoint_multi_turn_continuity_and_session_persistence(
    async_client: AsyncClient,
    mock_firestore: InMemoryFirestoreMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Demonstrate continuity across turns with the same conversation_id."""
    mock_model = AsyncMock(
        side_effect=[
            (ModelTurnOutput(response_text="Entendido, estás en Perú con FortiClient."), 40.0),
            (ModelTurnOutput(response_text="Me dijiste que usas FortiClient."), 38.0),
        ]
    )
    monkeypatch.setattr("app.graph.generate_turn_response_async", mock_model)

    conv_id = "Ivr02-continuity-test-99"

    # Turn 1
    resp1 = await async_client.post(
        "/turn",
        json={"conversation_id": conv_id, "text": "Estoy en Perú y uso FortiClient"},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["text"] == "Entendido, estás en Perú con FortiClient."

    # Verify session persisted in Firestore after Turn 1
    session1 = await get_session(conv_id, client=mock_firestore)  # type: ignore[arg-type]
    assert session1 is not None
    assert session1.turn_count == 1
    assert len(session1.turns) == 1
    assert session1.turns[0]["user_text"] == "Estoy en Perú y uso FortiClient"

    # Turn 2
    resp2 = await async_client.post(
        "/turn",
        json={"conversation_id": conv_id, "text": "¿Qué cliente te dije que uso?"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["text"] == "Me dijiste que usas FortiClient."

    # Verify session updated in Firestore after Turn 2
    session2 = await get_session(conv_id, client=mock_firestore)  # type: ignore[arg-type]
    assert session2 is not None
    assert session2.turn_count == 2
    assert len(session2.turns) == 2
    assert session2.turns[1]["user_text"] == "¿Qué cliente te dije que uso?"

    # Verify model boundary was called once per turn (total 2 calls)
    assert mock_model.await_count == 2


@pytest.mark.asyncio
async def test_turn_endpoint_isolation_between_conversations(
    async_client: AsyncClient,
    mock_firestore: InMemoryFirestoreMock,
) -> None:
    """Distinct conversation_ids maintain completely isolated session histories."""
    conv_a = "Ivr02-isolated-A"
    conv_b = "Ivr02-isolated-B"

    # Turn on Conv A
    resp_a = await async_client.post(
        "/turn",
        json={"conversation_id": conv_a, "text": "Problema con VPN en Conv A"},
    )
    assert resp_a.status_code == 200

    # Turn on Conv B
    resp_b = await async_client.post(
        "/turn",
        json={"conversation_id": conv_b, "text": "Problema con Contraseña en Conv B"},
    )
    assert resp_b.status_code == 200

    # Check isolation in Firestore store
    session_a = await get_session(conv_a, client=mock_firestore)  # type: ignore[arg-type]
    session_b = await get_session(conv_b, client=mock_firestore)  # type: ignore[arg-type]

    assert session_a is not None and session_b is not None
    assert session_a.conversation_id == conv_a
    assert session_b.conversation_id == conv_b
    assert session_a.turns[0]["user_text"] == "Problema con VPN en Conv A"
    assert session_b.turns[0]["user_text"] == "Problema con Contraseña en Conv B"


@pytest.mark.asyncio
async def test_turn_endpoint_model_failure_returns_500_without_retries(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When model boundary fails, endpoint returns HTTP 500 and does not loop."""
    mock_model = AsyncMock(side_effect=RuntimeError("Vertex AI connection failed"))
    monkeypatch.setattr("app.graph.generate_turn_response_async", mock_model)

    response = await async_client.post(
        "/turn",
        json={"conversation_id": "Ivr02-fail-test", "text": "Hola"},
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "Internal error processing conversational turn"
    mock_model.assert_awaited_once()
