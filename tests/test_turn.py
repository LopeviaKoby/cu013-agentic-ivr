import pytest
from httpx import AsyncClient

from app.contracts import Route


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
