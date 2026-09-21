"""DTMF/raw-identity canaries never reach the model, state, logs or response.

The canary is generated inside the test (never a fixture, never committed)
and injected through payloads the active contract rejects: the legacy
IDENTITY_DATA shape on ``/turns`` and an unknown identity field on
``/integration-events``. Any presence is a critical failure.
"""

import logging
import secrets

from tests.api.doubles import integration_events_url, turns_url


async def test_generated_dtmf_canary_stays_out_of_everything(client, store, model, caplog) -> None:
    canary = f"SYNTHETIC-DTMF-{secrets.token_hex(4)}"
    payload = {
        "event": "IDENTITY_DATA",
        "slots": {"document_id": canary},
        "channel": "voice",
    }
    with caplog.at_level(logging.DEBUG):
        response = await client.post(turns_url("conversation-1"), json=payload)
    assert response.status_code == 422
    assert canary not in response.text
    assert all(canary not in value for value in response.headers.values())
    assert canary not in caplog.text
    assert store.documents == {}
    assert (store.reads, store.writes) == (0, 0)
    assert model.calls == []


async def test_generated_dtmf_canary_is_rejected_by_the_technical_boundary(
    client, store, model, caplog
) -> None:
    canary = f"SYNTHETIC-DTMF-{secrets.token_hex(4)}"
    payload = {
        "event": "IDENTITY_VALIDATION_RESULT",
        "outcome": "VALID",
        "document_id": canary,
    }
    with caplog.at_level(logging.DEBUG):
        response = await client.post(integration_events_url("conversation-1"), json=payload)
    assert response.status_code == 422
    assert canary not in response.text
    assert all(canary not in value for value in response.headers.values())
    assert canary not in caplog.text
    assert store.documents == {}
    assert (store.reads, store.writes) == (0, 0)
    assert model.calls == []
