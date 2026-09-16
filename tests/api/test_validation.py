"""Invalid payloads never echo PII or transcript and use the safe taxonomy."""

import logging

import pytest

from tests.api.doubles import SYNTHETIC_DTMF, SYNTHETIC_TRANSCRIPT, turns_url

VALIDATION_ERROR = {
    "error": {"code": "validation", "message": "request validation failed"},
}

INVALID_PAYLOADS = [
    {},
    {"unknown": SYNTHETIC_TRANSCRIPT},
    {"transcript": SYNTHETIC_TRANSCRIPT, "unknown": SYNTHETIC_DTMF},
    {"transcript": {"nested": SYNTHETIC_DTMF}},
    {"event": "IDENTITY_DATA"},
    {"event": "OTHER", "slots": {"document_id": SYNTHETIC_DTMF}},
    {
        "transcript": SYNTHETIC_TRANSCRIPT,
        "event": "IDENTITY_DATA",
        "slots": {"document_id": SYNTHETIC_DTMF},
    },
    {"transcript": SYNTHETIC_TRANSCRIPT, "asr_confidence": "not-a-number"},
]


@pytest.mark.parametrize("payload", INVALID_PAYLOADS)
async def test_invalid_payload_is_sanitized(client, caplog, payload) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await client.post(turns_url("conversation-1"), json=payload)
    assert response.status_code == 422
    assert response.json() == VALIDATION_ERROR
    assert "detail" not in response.text
    assert SYNTHETIC_DTMF not in response.text
    assert SYNTHETIC_TRANSCRIPT not in response.text
    assert SYNTHETIC_DTMF not in caplog.text
    assert SYNTHETIC_TRANSCRIPT not in caplog.text


async def test_malformed_json_is_sanitized(client, caplog) -> None:
    raw_body = '{"transcript": "' + SYNTHETIC_DTMF + '"} trailing'
    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            turns_url("conversation-1"),
            content=raw_body,
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 422
    assert response.json() == VALIDATION_ERROR
    assert SYNTHETIC_DTMF not in response.text
    assert SYNTHETIC_DTMF not in caplog.text
