"""Turn flow tests: model seam, session identity, turn ids and safe errors."""

import logging

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.conversation.errors import (
    InvalidModelOutputError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.session.record import Action
from app.session.turns import Route
from tests.api.doubles import (
    SYNTHETIC_DTMF,
    SYNTHETIC_MESSAGE,
    SYNTHETIC_TRANSCRIPT,
    turns_url,
)
from tests.session.doubles import make_decision

REQUEST_ID_HEADERS = {"X-Request-ID": "conversation-1"}

PRIOR_REQUEST_TRANSCRIPT = "quiero desbloquear mi cuenta pero antes explícame qué puedes hacer"

ENGINE_UNAVAILABLE_ERROR = {
    "error": {
        "code": "dependency_unavailable",
        "message": "conversation engine is not available",
    },
}

DEPENDENCY_TIMEOUT_ERROR = {
    "error": {"code": "dependency_timeout", "message": "dependency timed out"},
}

DEPENDENCY_UNAVAILABLE_ERROR = {
    "error": {"code": "dependency_unavailable", "message": "dependency is not available"},
}

INTERNAL_ERROR = {"error": {"code": "internal", "message": "internal error"}}

COLLECT_IDENTITY_WITH_GOAL = make_decision(
    route=Route.COLLECT_IDENTITY,
    goal={"intent": "REQUEST", "action": "UNLOCK_ACCOUNT"},
)


async def test_structured_model_output_reaches_the_http_contract(client, model, store) -> None:
    model.decision = make_decision(message=SYNTHETIC_MESSAGE, route=Route.COMPLETE)
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["message"] == SYNTHETIC_MESSAGE
    assert body["route"] == "COMPLETE"
    assert body["turn_id"]
    assert len(model.calls) == 1
    assert (store.reads, store.writes) == (1, 1)


async def test_transcript_reaches_the_model_once_and_not_durable_state(
    client, model, store, caplog
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            turns_url("conversation-1"),
            json={"transcript": SYNTHETIC_TRANSCRIPT, "asr_confidence": 0.0, "channel": "voice"},
        )
    assert response.status_code == 200
    assert len(model.calls) == 1
    assert model.calls[0]["transcript"] == SYNTHETIC_TRANSCRIPT
    document = store.documents["conversation-1"]
    assert "transcript" not in document
    assert "message" not in document
    assert SYNTHETIC_TRANSCRIPT not in repr(document)
    assert SYNTHETIC_MESSAGE not in repr(document)
    assert SYNTHETIC_TRANSCRIPT not in caplog.text
    assert SYNTHETIC_MESSAGE not in caplog.text


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


async def test_request_id_is_not_an_idempotency_key(client, model, store) -> None:
    payload = {"transcript": SYNTHETIC_TRANSCRIPT}
    first = await client.post(turns_url("conversation-1"), json=payload, headers=REQUEST_ID_HEADERS)
    second = await client.post(
        turns_url("conversation-1"), json=payload, headers=REQUEST_ID_HEADERS
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(model.calls) == 2
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


async def test_model_timeout_is_a_safe_dependency_timeout(client, model, store) -> None:
    model.error = ModelTimeoutError("synthetic model timeout")
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 504
    assert response.json() == DEPENDENCY_TIMEOUT_ERROR
    assert "synthetic model timeout" not in response.text
    assert store.writes == 0


async def test_model_unavailable_is_a_safe_dependency_error(client, model, store) -> None:
    model.error = ModelUnavailableError("synthetic model outage")
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 503
    assert response.json() == DEPENDENCY_UNAVAILABLE_ERROR
    assert "synthetic model outage" not in response.text
    assert store.writes == 0


async def test_invalid_model_output_is_a_safe_internal_error(client, model, store) -> None:
    model.error = InvalidModelOutputError("synthetic invalid decision")
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR
    assert "synthetic invalid decision" not in response.text
    assert store.writes == 0


async def test_internal_engine_failure_is_a_safe_internal_error(
    client, model, store, caplog
) -> None:
    model.error = RuntimeError(f"synthetic failure {SYNTHETIC_DTMF}")
    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
        )
    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR
    assert SYNTHETIC_DTMF not in response.text
    assert SYNTHETIC_DTMF not in caplog.text
    assert store.writes == 0


async def test_prior_request_turn_keeps_the_route_and_the_goal_is_durable(
    client, model, store
) -> None:
    """The runtime never rewrites a CONTINUE route, and the pre-auth goal is
    representable and retakeable (the CNV-001 property)."""
    model.decision = make_decision(
        message="Puedo restablecer contraseñas y desbloquear cuentas. ¿Seguimos?",
        route=Route.CONTINUE,
        goal={"intent": "REQUEST", "action": "UNLOCK_ACCOUNT"},
    )
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": PRIOR_REQUEST_TRANSCRIPT}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "CONTINUE"
    assert body["message"] == model.decision.message
    document = store.documents["conversation-1"]
    assert document["goal"] == {"action": "UNLOCK_ACCOUNT", "revision": 1}
    assert document["identity"] == {"validated_at": None, "caller_failures": 0}
    assert document["dispatch"] is None
    assert document["external_operation"] is None


async def test_model_claimed_success_is_not_business_success(client, model, store) -> None:
    model.decision = make_decision(
        message="synthetic claim of business success",
        route=Route.COMPLETE,
        goal={"intent": "REQUEST", "action": "UNLOCK_ACCOUNT"},
        claims=[{"kind": "OPERATION_SUCCEEDED"}],
    )
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 200
    assert response.json()["route"] == "CONTINUE"
    assert response.json()["message"] != model.decision.message
    document = store.documents["conversation-1"]
    assert document["identity"]["validated_at"] is None  # type: ignore[index]
    assert document["dispatch"] is None
    assert document["external_operation"] is None


async def test_every_legal_route_reaches_the_response(client, model) -> None:
    model.decision = COLLECT_IDENTITY_WITH_GOAL
    first = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert first.json()["route"] == "COLLECT_IDENTITY"

    for decision in (
        make_decision(route=Route.CONTINUE),
        make_decision(route=Route.ESCALATE, handoff_cause="CALLER_REQUEST"),
        make_decision(route=Route.COMPLETE),
    ):
        model.decision = decision
        response = await client.post(
            turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
        )
        assert response.status_code == 200
        assert response.json()["route"] == decision.route.value


async def test_illegal_route_is_replaced_by_the_safe_fallback(client, model, store) -> None:
    model.decision = make_decision(
        route=Route.ESCALATE,
        message="synthetic escalation message",
        handoff_cause="TERMINAL_FAILURE",
    )
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 200
    assert response.json()["route"] == "CONTINUE"
    assert response.json()["message"] != model.decision.message
    assert store.documents["conversation-1"]["dispatch"] is None


def test_action_enum_is_closed_to_the_supported_slice() -> None:
    assert {action.value for action in Action} == {"RESET_PASSWORD", "UNLOCK_ACCOUNT"}
