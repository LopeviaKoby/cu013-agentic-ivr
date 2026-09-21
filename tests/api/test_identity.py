"""Raw identity shapes are out of the active turn contract.

Cally Square captures and validates identity; CU013 only receives the
PII-safe ``IDENTITY_VALIDATION_RESULT`` outcome through the technical
endpoint. These tests pin that the old ``IDENTITY_DATA`` request shape no
longer exists, is rejected as an invalid payload and can never create
durable state, reach the model or leak into telemetry.
"""

import logging

import pytest

from tests.api.doubles import SYNTHETIC_DTMF, SYNTHETIC_TRANSCRIPT, turns_url

VALIDATION_ERROR = {
    "error": {"code": "validation", "message": "request validation failed"},
}

RAW_IDENTITY_PAYLOADS = [
    {"event": "IDENTITY_DATA", "slots": {"document_id": SYNTHETIC_DTMF}, "channel": "voice"},
    {"event": "IDENTITY_DATA", "slots": {"document_id": SYNTHETIC_DTMF}},
    {"slots": {"document_id": SYNTHETIC_DTMF}},
    {"document_id": SYNTHETIC_DTMF},
    {"birth_date": SYNTHETIC_DTMF},
]


@pytest.mark.parametrize("payload", RAW_IDENTITY_PAYLOADS)
async def test_raw_identity_payload_is_rejected_without_side_effects(
    client, store, model, caplog, payload
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await client.post(turns_url("conversation-1"), json=payload)
    assert response.status_code == 422
    assert response.json() == VALIDATION_ERROR
    assert SYNTHETIC_DTMF not in response.text
    assert all(SYNTHETIC_DTMF not in value for value in response.headers.values())
    assert SYNTHETIC_DTMF not in caplog.text
    assert store.documents == {}
    assert (store.reads, store.writes) == (0, 0)
    assert model.calls == []


async def test_rejected_raw_identity_never_marks_a_validated_identity(client, store) -> None:
    await client.post(
        turns_url("conversation-1"),
        json={"event": "IDENTITY_DATA", "slots": {"document_id": SYNTHETIC_DTMF}},
    )
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 200
    assert store.documents["conversation-1"]["identity"] == {
        "validated_at": None,
        "caller_failures": 0,
    }
    assert store.documents["conversation-1"]["dispatch"] is None
