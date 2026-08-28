import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok_contract(async_client: AsyncClient) -> None:
    """GET /health must return HTTP 200 with status='ok' and version='0.2.0'."""
    response = await async_client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.2.0"
