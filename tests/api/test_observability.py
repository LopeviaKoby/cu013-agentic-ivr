"""Observability tests: one shared handler, closed events, safe 422 facts.

No model, network, Firestore or credentials are involved. The logs are
captured by attaching the pytest handler to the shared ``cu013`` namespace, so
the assertions hold regardless of propagation, and every assertion is about
closed field values: no payload, transcript, identifier or secret may ever
reach a log line.
"""

import logging

import pytest

from app.api.contracts_next_step import NEXT_STEP_CONTRACT, RESPONSE_CONTRACT_HEADER
from app.observability import LOGGER_NAME, configure_logging
from tests.api.doubles import (
    SYNTHETIC_API_KEY,
    SYNTHETIC_TRANSCRIPT,
    integration_events_url,
    turns_url,
)

NEXT_STEP_HEADERS = {RESPONSE_CONTRACT_HEADER: NEXT_STEP_CONTRACT}


@pytest.fixture
def app_logs(caplog):  # type: ignore[no-untyped-def]
    logger = logging.getLogger(LOGGER_NAME)
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


def test_configure_logging_is_idempotent_and_single(app_logs) -> None:  # type: ignore[no-untyped-def]
    configure_logging()
    configure_logging()
    logger = logging.getLogger(LOGGER_NAME)
    shared = [
        handler for handler in logger.handlers if getattr(handler, "_cu013_shared_handler", False)
    ]
    assert len(shared) == 1
    assert logger.propagate is False


def test_metric_lines_reach_the_shared_namespace_once(app_logs) -> None:  # type: ignore[no-untyped-def]
    from app.session.metrics import StructuredLogTurnMetrics

    metrics = StructuredLogTurnMetrics()
    metrics.record_segment("model", 1.5)
    metrics.record_counter("total_tokens", 7)
    assert app_logs.text.count("turn_metric segment=model duration_ms=1.500") == 1
    assert app_logs.text.count("turn_metric counter=total_tokens value=7") == 1


async def test_a_turn_emits_closed_events_exactly_once(client, app_logs) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 200
    text = app_logs.text
    assert text.count("response_contract_selected lane=turns response_contract=legacy") == 1
    assert text.count("turn_handled lane=turns response_contract=legacy next_step=LISTEN") == 1
    assert text.count("http_result lane=turns response_contract=legacy http_status=200") == 1
    assert "conversation-1" not in text
    assert SYNTHETIC_TRANSCRIPT not in text


async def test_rejection_logs_a_closed_reason_without_identifiers(client, app_logs) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "IDENTITY_VALIDATION_RESULT", "outcome": "VALID"},
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 409
    text = app_logs.text
    assert (
        "integration_event_rejected event_type=IDENTITY_VALIDATION_RESULT "
        "normalized_rejection_reason=unknown_session" in text
    )
    assert (
        "http_result lane=integration_events response_contract=next-step-v1 http_status=409" in text
    )
    assert "conversation-1" not in text


async def test_validation_facts_are_logged_without_the_payload(client, app_logs) -> None:  # type: ignore[no-untyped-def]
    canary = "synthetic-canary@example.test"
    response = await client.post(
        integration_events_url("conversation-1"),
        json={
            "event": "ACCOUNT_ACTION_STATUS",
            "operation_id": "operation-1",
            "action": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "status": "NONE",
            "poll_sequence": 1,
            "email": canary,
        },
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 422
    text = app_logs.text
    # A discriminated union reports the matched tag plus the offending field,
    # both closed values; the payload value itself never travels.
    assert (
        "request_validation_failed lane=integration_events "
        "facts=ACCOUNT_ACTION_STATUS.email:extra_forbidden" in text
    )
    assert canary not in text
    assert (
        "http_result lane=integration_events response_contract=next-step-v1 http_status=422" in text
    )


async def test_malformed_json_facts_are_closed(client, app_logs) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        integration_events_url("conversation-1"),
        content='{"event": ',
        headers={**NEXT_STEP_HEADERS, "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert (
        "request_validation_failed lane=integration_events facts=body:json_invalid" in app_logs.text
    )


async def test_turn_validation_facts_come_from_the_closed_contract(client, app_logs) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT, "document_id": "SYNTHETIC-DOC-0000"},
    )
    assert response.status_code == 422
    text = app_logs.text
    assert "request_validation_failed lane=turns facts=body.document_id:extra_forbidden" in text
    assert "SYNTHETIC-DOC-0000" not in text


async def test_api_key_and_request_id_never_reach_the_logs(client, app_logs) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT},
        headers={"X-Request-ID": "synthetic-request-id-0000"},
    )
    assert response.status_code == 200
    assert SYNTHETIC_API_KEY not in app_logs.text
    assert "synthetic-request-id-0000" not in app_logs.text
