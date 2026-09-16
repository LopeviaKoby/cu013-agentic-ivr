"""Turn flow tests: seam input, session identity, turn ids and safe errors."""

import logging

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from tests.api.doubles import SYNTHETIC_DTMF, SYNTHETIC_TRANSCRIPT, turns_url

REQUEST_ID_HEADERS = {"X-Request-ID": "conversation-1"}

ENGINE_UNAVAILABLE_ERROR = {
    "error": {
        "code": "dependency_unavailable",
        "message": "conversation engine is not available",
    },
}

INTERNAL_ERROR = {"error": {"code": "internal", "message": "internal error"}}


async def test_transcript_reaches_the_engine_seam_but_not_durable_state(
    client, engine, store, caplog
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            turns_url("conversation-1"),
            json={"transcript": SYNTHETIC_TRANSCRIPT, "asr_confidence": 0.0, "channel": "voice"},
        )
    assert response.status_code == 200
    assert len(engine.turns) == 1
    assert engine.turns[0].conversation_id == "conversation-1"
    assert engine.turns[0].transcript == SYNTHETIC_TRANSCRIPT
    assert engine.turns[0].asr_confidence == 0.0
    document = store.documents["conversation-1"]
    assert "transcript" not in document
    assert SYNTHETIC_TRANSCRIPT not in repr(document)
    assert SYNTHETIC_TRANSCRIPT not in caplog.text


async def test_conversation_id_from_the_path_is_the_session_identity(client, store) -> None:
    response = await client.post(
        turns_url("conversation-abc"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 200
    assert list(store.documents) == ["conversation-abc"]
    document = store.documents["conversation-abc"]
    assert document["conversation_id"] == "conversation-abc"
    assert document["turn_count"] == 1


async def test_turn_ids_are_unique_and_ignore_request_id(client) -> None:
    first = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT},
        headers=REQUEST_ID_HEADERS,
    )
    second = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT},
        headers=REQUEST_ID_HEADERS,
    )
    first_turn_id = first.json()["turn_id"]
    second_turn_id = second.json()["turn_id"]
    assert first_turn_id != second_turn_id
    assert first_turn_id != REQUEST_ID_HEADERS["X-Request-ID"]
    assert second_turn_id != REQUEST_ID_HEADERS["X-Request-ID"]


async def test_request_id_is_not_an_idempotency_key(client, engine, store) -> None:
    payload = {"transcript": SYNTHETIC_TRANSCRIPT}
    first = await client.post(turns_url("conversation-1"), json=payload, headers=REQUEST_ID_HEADERS)
    second = await client.post(
        turns_url("conversation-1"), json=payload, headers=REQUEST_ID_HEADERS
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(engine.turns) == 2
    assert store.documents["conversation-1"]["turn_count"] == 2


async def test_engine_unavailable_is_a_safe_dependency_error(api_key) -> None:
    app: FastAPI = create_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-API-Key": api_key},
    ) as client:
        response = await client.post(
            turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
        )
    assert response.status_code == 503
    assert response.json() == ENGINE_UNAVAILABLE_ERROR


async def test_internal_engine_failure_is_a_safe_internal_error(
    client, engine, store, caplog
) -> None:
    engine.error = RuntimeError(f"synthetic failure {SYNTHETIC_DTMF}")
    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
        )
    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR
    assert SYNTHETIC_DTMF not in response.text
    assert SYNTHETIC_DTMF not in caplog.text
    assert store.writes == 0
