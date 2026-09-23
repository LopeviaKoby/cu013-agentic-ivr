"""HTTP contract tests for POST /integration-events.

No model, network, Firestore or credentials are involved. The endpoint must
accept only PII-safe technical events, never call the model, return a flat
directive response and reject anything that cannot be correlated with the
durable session.
"""

import json
import logging
import secrets

import pytest

from app.session.integration import (
    IDENTITY_TECHNICAL_FAILURE_MESSAGE,
    UNLOCK_COMPLETED_MESSAGE,
    UNLOCK_CONFIRMATION_MESSAGE,
)
from app.session.record import session_record_to_document
from tests.api.doubles import integration_events_url, turns_url
from tests.session.doubles import (
    NOW,
    make_challenge,
    make_decision,
    make_dispatch,
    make_goal,
    make_identity,
    make_operation,
    make_record,
)

CONFLICT_ERROR = {
    "error": {
        "code": "conflict_or_duplicate",
        "message": "event cannot be correlated with the conversation",
    }
}

VALIDATION_ERROR = {
    "error": {"code": "validation", "message": "request validation failed"},
}


def _seed_dispatched(store, action: str = "UNLOCK_ACCOUNT") -> str:
    record = make_record(
        goal=make_goal(action, revision=1),
        identity=make_identity(NOW),
        confirmation=None,
        dispatch=make_dispatch(action, revision=1, operation_id="operation-1"),
        external_operation=make_operation(
            action, operation_id="operation-1", last_progress_feedback_at=NOW
        ),
    )
    store.documents["conversation-1"] = session_record_to_document(record)
    return "operation-1"


def _status_body(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "event": "ACCOUNT_ACTION_STATUS",
        "operation_id": "operation-1",
        "action": "UNLOCK_ACCOUNT",
        "goal_revision": 1,
        "status": "NONE",
    }
    values.update(overrides)
    return values


async def test_integration_events_require_the_api_key(anonymous_client, store) -> None:
    response = await anonymous_client.post(
        integration_events_url("conversation-1"),
        json={"event": "VOICE_INPUT_FAILURE", "reason": "NO_SPEECH"},
    )
    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "authorization", "message": "authentication failed"}
    }
    assert store.writes == 0


async def test_transcript_is_not_part_of_the_technical_contract(client, store) -> None:
    response = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "VOICE_INPUT_FAILURE", "reason": "NO_SPEECH", "transcript": "hola"},
    )
    assert response.status_code == 422
    assert response.json() == VALIDATION_ERROR
    assert store.writes == 0


@pytest.mark.parametrize(
    "extra",
    [
        {"document_id": "synthetic-document"},
        {"birth_date": "synthetic-date"},
        {"email": "synthetic@example.test"},
        {"password": "synthetic-password"},
        {"api_key": "synthetic-rd-key"},
    ],
)
async def test_pii_fields_are_rejected(client, store, extra) -> None:
    response = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "IDENTITY_VALIDATION_RESULT", "outcome": "VALID", **extra},
    )
    assert response.status_code == 422
    assert store.writes == 0


async def test_unknown_event_kind_is_rejected(client) -> None:
    response = await client.post(
        integration_events_url("conversation-1"), json={"event": "SOMETHING_ELSE"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"event": "IDENTITY_VALIDATION_RESULT", "outcome": 1},
        {"event": "IDENTITY_VALIDATION_RESULT"},
        {"event": "VOICE_INPUT_FAILURE", "reason": 5},
        {"event": "VOICE_INPUT_FAILURE", "reason": "WHISPERING"},
        {"event": "ACCOUNT_ACTION_STATUS", "operation_id": "op", "action": "REBOOT"},
        {
            "event": "ACCOUNT_ACTION_STATUS",
            "operation_id": "op",
            "action": "UNLOCK_ACCOUNT",
            "goal_revision": "one",
            "status": "NONE",
        },
        {
            "event": "ACCOUNT_ACTION_ERROR",
            "operation_id": "op",
            "action": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "phase": 1,
            "error_kind": "TIMEOUT",
        },
        {
            "event": "ACCOUNT_ACTION_ERROR",
            "operation_id": "op",
            "action": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "phase": "BOTH",
            "error_kind": "TIMEOUT",
        },
    ],
)
async def test_wrong_types_and_unknown_values_are_rejected(client, store, payload) -> None:
    response = await client.post(integration_events_url("conversation-1"), json=payload)
    assert response.status_code == 422
    assert response.json() == VALIDATION_ERROR
    assert store.writes == 0


async def test_external_lookup_states_are_not_identity_outcomes(client, store) -> None:
    """FOUND/NOT_FOUND belong to the external lookup, never to CU013's outcome.

    XCALLY maps NOT_FOUND, a date mismatch and technical lookup errors to the
    local VALID/INVALID/TECHNICAL_FAILURE vocabulary; FOUND alone never
    authorizes anything at this boundary.
    """
    for outcome in ("FOUND", "NOT_FOUND"):
        response = await client.post(
            integration_events_url("conversation-1"),
            json={"event": "IDENTITY_VALIDATION_RESULT", "outcome": outcome},
        )
        assert response.status_code == 422
        assert response.json() == VALIDATION_ERROR
    assert store.writes == 0


async def test_unwired_integration_service_fails_safely(api_key) -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.app import create_app

    app: FastAPI = create_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport, base_url="http://testserver", headers={"X-API-Key": api_key}
    ) as http_client:
        response = await http_client.post(
            integration_events_url("conversation-1"),
            json={"event": "VOICE_INPUT_FAILURE", "reason": "NO_SPEECH"},
        )
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "dependency_unavailable",
            "message": "integration events are not available",
        }
    }


async def test_persistence_failure_is_a_safe_dependency_error(client, store) -> None:
    store.documents["conversation-1"] = session_record_to_document(
        make_record(goal=make_goal("UNLOCK_ACCOUNT", revision=1), identity=make_identity())
    )
    store.fail_writes = True
    response = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "IDENTITY_VALIDATION_RESULT", "outcome": "VALID"},
    )
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "dependency_unavailable",
            "message": "dependency is not available",
        }
    }


async def test_identity_valid_returns_a_safe_directive_without_a_model_call(
    client, model, store
) -> None:
    store.documents["conversation-1"] = session_record_to_document(
        make_record(goal=make_goal("UNLOCK_ACCOUNT", revision=1), identity=make_identity())
    )
    response = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "IDENTITY_VALIDATION_RESULT", "outcome": "VALID"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"acknowledged", "operation_state", "directive", "message"}
    assert body["acknowledged"] is True
    assert body["directive"] == "RESUME_CONVERSATION"
    assert body["message"] == UNLOCK_CONFIRMATION_MESSAGE
    assert body["operation_state"] is None
    assert model.calls == []


async def test_identity_invalid_escalates_at_the_accepted_maximum(client, store) -> None:
    store.documents["conversation-1"] = session_record_to_document(
        make_record(goal=make_goal("UNLOCK_ACCOUNT", revision=1), identity=make_identity())
    )
    for expected_directive in ("COLLECT_IDENTITY", "COLLECT_IDENTITY", "ESCALATE"):
        response = await client.post(
            integration_events_url("conversation-1"),
            json={"event": "IDENTITY_VALIDATION_RESULT", "outcome": "INVALID"},
        )
        assert response.status_code == 200
        assert response.json()["directive"] == expected_directive
    document = store.documents["conversation-1"]
    assert document["identity"]["caller_failures"] == 3


async def test_identity_technical_failure_keeps_the_attempt_and_calls_no_model(
    client, model, store
) -> None:
    store.documents["conversation-1"] = session_record_to_document(
        make_record(
            goal=make_goal("UNLOCK_ACCOUNT", revision=1),
            identity=make_identity(failures=1),
        )
    )
    writes_before = store.writes
    response = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "IDENTITY_VALIDATION_RESULT", "outcome": "TECHNICAL_FAILURE"},
    )
    assert response.status_code == 200
    assert response.json()["message"] == IDENTITY_TECHNICAL_FAILURE_MESSAGE
    assert store.documents["conversation-1"]["identity"]["caller_failures"] == 1
    assert store.writes == writes_before
    assert model.calls == []


async def test_voice_failure_invalidates_the_challenge_without_authorizing(
    client, model, store
) -> None:
    store.documents["conversation-1"] = session_record_to_document(
        make_record(
            goal=make_goal("UNLOCK_ACCOUNT", revision=1),
            identity=make_identity(NOW),
            confirmation=make_challenge("UNLOCK_ACCOUNT", revision=1),
        )
    )
    response = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "VOICE_INPUT_FAILURE", "reason": "TIMEOUT"},
    )
    assert response.status_code == 200
    assert response.json()["directive"] == "RETRY_SPEECH"
    assert response.json()["message"]
    document = store.documents["conversation-1"]
    assert document["confirmation"] is None
    assert document["dispatch"] is None
    assert document["identity"]["validated_at"] == NOW
    assert document["identity"]["caller_failures"] == 0
    assert model.calls == []


async def test_status_none_polls_and_then_completes_on_success(client, model, store) -> None:
    _seed_dispatched(store)
    pending = await client.post(
        integration_events_url("conversation-1"), json=_status_body(status="NONE")
    )
    assert pending.status_code == 200
    assert pending.json()["directive"] == "POLL_RD"
    assert pending.json()["operation_state"] == "PENDING"
    assert pending.json()["message"] is None

    success = await client.post(
        integration_events_url("conversation-1"), json=_status_body(status="SUCESSO")
    )
    assert success.status_code == 200
    assert success.json()["directive"] == "COMPLETE"
    assert success.json()["operation_state"] == "SUCCEEDED"
    assert success.json()["message"] == UNLOCK_COMPLETED_MESSAGE
    assert store.documents["conversation-1"]["external_operation"]["status"] == "confirmed"
    assert model.calls == []


async def test_known_failure_status_returns_a_grounded_resume(client, store) -> None:
    _seed_dispatched(store)
    response = await client.post(
        integration_events_url("conversation-1"), json=_status_body(status="FALHA_AD")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["directive"] == "RESUME_CONVERSATION"
    assert body["operation_state"] == "FAILED"
    assert body["message"]
    assert "AD" not in body["message"] and "RD" not in body["message"]


async def test_unknown_status_is_acknowledged_without_inventing_semantics(client, store) -> None:
    _seed_dispatched(store)
    writes_before = store.writes
    response = await client.post(
        integration_events_url("conversation-1"), json=_status_body(status="NOVO_STATUS")
    )
    assert response.status_code == 200
    assert response.json()["directive"] == "POLL_RD"
    assert response.json()["operation_state"] == "PENDING"
    assert store.writes == writes_before


async def test_wrong_operation_is_rejected_as_conflict(client, store) -> None:
    _seed_dispatched(store)
    writes_before = store.writes
    response = await client.post(
        integration_events_url("conversation-1"),
        json=_status_body(operation_id="operation-other", status="SUCESSO"),
    )
    assert response.status_code == 409
    assert response.json() == CONFLICT_ERROR
    assert store.writes == writes_before


async def test_unknown_conversation_is_rejected_as_conflict(client, store) -> None:
    response = await client.post(
        integration_events_url("conversation-unknown"),
        json={"event": "VOICE_INPUT_FAILURE", "reason": "NO_SPEECH"},
    )
    assert response.status_code == 409
    assert response.json() == CONFLICT_ERROR
    assert store.writes == 0


async def test_dispatch_error_moves_to_unknown_and_polls(client, store) -> None:
    _seed_dispatched(store)
    response = await client.post(
        integration_events_url("conversation-1"),
        json={
            "event": "ACCOUNT_ACTION_ERROR",
            "operation_id": "operation-1",
            "action": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "phase": "DISPATCH",
            "error_kind": "TIMEOUT",
            "http_status": None,
        },
    )
    assert response.status_code == 200
    assert response.json()["directive"] == "POLL_RD"
    assert response.json()["operation_state"] == "UNKNOWN"
    assert store.documents["conversation-1"]["external_operation"]["status"] == "unknown"


async def test_the_request_id_header_is_transport_correlation_not_idempotency(
    client, store
) -> None:
    _seed_dispatched(store)
    headers = {"X-Request-ID": "synthetic-request-id"}
    first = await client.post(
        integration_events_url("conversation-1"), json=_status_body(status="NONE"), headers=headers
    )
    second = await client.post(
        integration_events_url("conversation-1"), json=_status_body(status="NONE"), headers=headers
    )
    assert first.status_code == second.status_code == 200
    assert store.writes == 0


@pytest.mark.parametrize(
    "reference",
    [
        'quote " inside',
        "apostrophe ' inside",
        "line\nbreak and tab\t",
        "back\\slash",
        "acentos: áéíóúñ¿¡",
    ],
)
async def test_validation_reference_accepts_json_strings_without_leaking(
    client, store, caplog, reference
) -> None:
    store.documents["conversation-1"] = session_record_to_document(
        make_record(goal=make_goal("UNLOCK_ACCOUNT", revision=1), identity=make_identity())
    )
    payload = {
        "event": "IDENTITY_VALIDATION_RESULT",
        "outcome": "VALID",
        "validation_reference": reference,
    }
    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            integration_events_url("conversation-1"),
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 200
    assert reference not in response.text
    assert reference not in caplog.text
    assert reference not in repr(store.documents["conversation-1"])


async def test_operation_id_is_preserved_as_an_opaque_string(client, store) -> None:
    canary = f"synthetic-op-{secrets.token_hex(4)}"
    store.documents["conversation-1"] = session_record_to_document(
        make_record(
            goal=make_goal("UNLOCK_ACCOUNT", revision=1),
            identity=make_identity(NOW),
            dispatch=make_dispatch("UNLOCK_ACCOUNT", revision=1, operation_id=canary),
            external_operation=make_operation(
                "UNLOCK_ACCOUNT", operation_id=canary, last_progress_feedback_at=NOW
            ),
        )
    )
    response = await client.post(
        integration_events_url("conversation-1"), json=_status_body(operation_id=canary)
    )
    assert response.status_code == 200
    assert store.documents["conversation-1"]["external_operation"]["operation_id"] == canary


async def test_numeric_operation_id_is_rejected(client, store) -> None:
    _seed_dispatched(store)
    response = await client.post(
        integration_events_url("conversation-1"),
        json=_status_body(operation_id=12345),
    )
    assert response.status_code == 422
    assert store.writes == 0


async def test_progress_feedback_cadence_over_http(client, store, clock) -> None:

    from app.session.integration import PROGRESS_FEEDBACK_INTERVAL, PROGRESS_MESSAGES

    _seed_dispatched(store)
    immediate = await client.post(
        integration_events_url("conversation-1"), json=_status_body(status="NONE")
    )
    assert immediate.json()["message"] is None

    clock.now = NOW + PROGRESS_FEEDBACK_INTERVAL
    progressed = await client.post(
        integration_events_url("conversation-1"), json=_status_body(status="NONE")
    )
    assert progressed.json()["message"] == PROGRESS_MESSAGES[0]

    clock.now = NOW + 2 * PROGRESS_FEEDBACK_INTERVAL
    second = await client.post(
        integration_events_url("conversation-1"), json=_status_body(status="NONE")
    )
    assert second.json()["message"] == PROGRESS_MESSAGES[1]

    clock.now = NOW + 3 * PROGRESS_FEEDBACK_INTERVAL
    terminal = await client.post(
        integration_events_url("conversation-1"), json=_status_body(status="SUCESSO")
    )
    assert terminal.json()["directive"] == "COMPLETE"
    assert terminal.json()["message"] == UNLOCK_COMPLETED_MESSAGE
    prohibited = (
        "Ya casi termina",
        "AD está respondiendo",
        "Tu cuenta ya fue encontrada",
        "Está al 80",
        "desbloqueo fue exitoso",
    )
    for body in (progressed.json(), second.json(), terminal.json()):
        for phrase in prohibited:
            assert phrase not in (body["message"] or "")


async def test_turns_and_integration_events_share_one_durable_session(client, model, store) -> None:
    model.decision = make_decision(
        route="COLLECT_IDENTITY",
        goal={"intent": "REQUEST", "action": "UNLOCK_ACCOUNT"},
    )
    turn = await client.post(
        turns_url("conversation-1"), json={"transcript": "quiero desbloquear mi cuenta"}
    )
    assert turn.status_code == 200
    event = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "IDENTITY_VALIDATION_RESULT", "outcome": "VALID"},
    )
    assert event.status_code == 200
    document = store.documents["conversation-1"]
    assert document["conversation_id"] == "conversation-1"
    assert document["turn_count"] == 1
    assert document["identity"]["validated_at"] == NOW
