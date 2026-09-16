"""API-key authentication: valid, invalid, missing and unconfigured."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.api.security import API_KEY_ENV_VAR
from tests.api.doubles import SYNTHETIC_API_KEY, SYNTHETIC_TRANSCRIPT, turns_url

WRONG_API_KEY = "synthetic-wrong-key-0000"

AUTHORIZATION_ERROR = {
    "error": {"code": "authorization", "message": "authentication failed"},
}

INTERNAL_ERROR = {"error": {"code": "internal", "message": "internal error"}}


async def test_valid_api_key_is_accepted(client) -> None:
    response = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT},
        headers={"X-API-Key": SYNTHETIC_API_KEY},
    )
    assert response.status_code == 200


async def test_invalid_api_key_is_rejected_without_echo(client) -> None:
    response = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT},
        headers={"X-API-Key": WRONG_API_KEY},
    )
    assert response.status_code == 401
    assert response.json() == AUTHORIZATION_ERROR
    assert WRONG_API_KEY not in response.text


async def test_missing_api_key_is_rejected(anonymous_client) -> None:
    response = await anonymous_client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 401
    assert response.json() == AUTHORIZATION_ERROR


async def test_unconfigured_api_key_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    engine,
) -> None:
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    app: FastAPI = create_app(engine=engine)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            turns_url("conversation-1"),
            json={"transcript": SYNTHETIC_TRANSCRIPT},
            headers={"X-API-Key": SYNTHETIC_API_KEY},
        )
    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR


async def test_authentication_precedes_body_field_validation(anonymous_client) -> None:
    response = await anonymous_client.post(turns_url("conversation-1"), json={"unknown": True})
    assert response.status_code == 401
    assert response.json() == AUTHORIZATION_ERROR
