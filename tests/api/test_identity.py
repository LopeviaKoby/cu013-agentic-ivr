"""IDENTITY_DATA boundary: raw DTMF is accepted and contained."""

import logging

from tests.api.doubles import SYNTHETIC_DTMF, SYNTHETIC_TRANSCRIPT, turns_url

IDENTITY_DATA = {
    "event": "IDENTITY_DATA",
    "slots": {"document_id": SYNTHETIC_DTMF},
    "channel": "voice",
}

DEPENDENCY_ERROR = {
    "error": {
        "code": "dependency_unavailable",
        "message": "identity validation is not available",
    },
}


async def test_identity_data_terminates_safely_without_touching_durable_state(
    client, store, model, caplog
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await client.post(turns_url("conversation-1"), json=IDENTITY_DATA)
    assert response.status_code == 503
    assert response.json() == DEPENDENCY_ERROR
    assert SYNTHETIC_DTMF not in response.text
    assert all(SYNTHETIC_DTMF not in value for value in response.headers.values())
    assert SYNTHETIC_DTMF not in caplog.text
    assert store.documents == {}
    assert (store.reads, store.writes) == (0, 0)
    assert model.calls == []


async def test_identity_data_never_reaches_the_model_adapter(client, model) -> None:
    await client.post(turns_url("conversation-1"), json=IDENTITY_DATA)
    assert model.calls == []


async def test_receiving_dtmf_never_marks_a_validated_identity(client, store) -> None:
    await client.post(turns_url("conversation-1"), json=IDENTITY_DATA)
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 200
    assert store.documents["conversation-1"]["identity_validated"] is False


async def test_identity_data_requires_document_id(client) -> None:
    response = await client.post(
        turns_url("conversation-1"),
        json={"event": "IDENTITY_DATA", "slots": {}, "channel": "voice"},
    )
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation", "message": "request validation failed"}
    }
