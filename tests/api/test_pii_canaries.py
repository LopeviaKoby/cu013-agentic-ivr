"""PII canary matrix across the two active HTTP lanes.

Canaries are generated inside the test (never fixtures, never committed)
for the personal data the backend must never hold: document, birth or entry
date, email, identity value, password and secret. Each canary is injected
through a rejected field or an unaccredited reference and must stay absent
from the model input, Firestore, logs, durable state, the HTTP response and
any shared repository artifact.
"""

import logging
import secrets
from pathlib import Path

import pytest

from app.session.record import session_record_to_document
from tests.api.doubles import integration_events_url, turns_url
from tests.session.doubles import (
    NOW,
    make_dispatch,
    make_goal,
    make_identity,
    make_operation,
    make_record,
)

ROOT = Path(__file__).resolve().parents[2]

PII_FIELDS = [
    ("document", "document_id"),
    ("birth_date", "birth_date"),
    ("email", "email"),
    ("identity", "identity"),
    ("password", "password"),
    ("secret", "api_key"),
]


def _fresh_canary(category: str) -> str:
    return f"SYNTHETIC-{category.upper()}-{secrets.token_hex(4)}"


def _assert_absent_from_shared_artifacts(canary: str) -> None:
    for base in ("app", "tests", "evals", "docs"):
        for path in (ROOT / base).rglob("*"):
            if not path.is_file():
                continue
            if path.resolve() == Path(__file__).resolve():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            assert canary not in text, f"canary committed in {path}"


@pytest.fixture
def dispatched_store(store):
    store.documents["conversation-1"] = session_record_to_document(
        make_record(
            goal=make_goal("UNLOCK_ACCOUNT", revision=1),
            identity=make_identity(NOW),
            dispatch=make_dispatch("UNLOCK_ACCOUNT", revision=1, operation_id="operation-1"),
            external_operation=make_operation(
                "UNLOCK_ACCOUNT", operation_id="operation-1", last_progress_feedback_at=NOW
            ),
        )
    )
    return store


@pytest.mark.parametrize("category,field", PII_FIELDS)
async def test_pii_canary_in_an_integration_event_is_rejected_and_absent(
    client, dispatched_store, model, caplog, category, field
) -> None:
    canary = _fresh_canary(category)
    durable_before = repr(dispatched_store.documents)
    payload = {
        "event": "IDENTITY_VALIDATION_RESULT",
        "outcome": "VALID",
        field: canary,
    }
    with caplog.at_level(logging.DEBUG):
        response = await client.post(integration_events_url("conversation-1"), json=payload)
    assert response.status_code == 422
    assert canary not in response.text
    assert all(canary not in value for value in response.headers.values())
    assert canary not in caplog.text
    assert canary not in repr(dispatched_store.documents)
    assert repr(dispatched_store.documents) == durable_before
    assert model.calls == []
    _assert_absent_from_shared_artifacts(canary)


@pytest.mark.parametrize("category,field", PII_FIELDS)
async def test_pii_canary_in_a_turn_payload_is_rejected_and_absent(
    client, model, store, caplog, category, field
) -> None:
    canary = _fresh_canary(category)
    payload = {"transcript": "synthetic transcript", field: canary}
    with caplog.at_level(logging.DEBUG):
        response = await client.post(turns_url("conversation-1"), json=payload)
    assert response.status_code == 422
    assert canary not in response.text
    assert canary not in caplog.text
    assert canary not in repr(store.documents)
    assert model.calls == []
    _assert_absent_from_shared_artifacts(canary)


async def test_validation_reference_is_accepted_but_never_persisted(
    client, dispatched_store, model, caplog
) -> None:
    canary = _fresh_canary("identity")
    payload = {
        "event": "IDENTITY_VALIDATION_RESULT",
        "outcome": "VALID",
        "validation_reference": canary,
    }
    with caplog.at_level(logging.DEBUG):
        response = await client.post(integration_events_url("conversation-1"), json=payload)
    assert response.status_code == 200
    assert canary not in response.text
    assert canary not in caplog.text
    assert canary not in repr(dispatched_store.documents)
    assert model.calls == []
    _assert_absent_from_shared_artifacts(canary)
