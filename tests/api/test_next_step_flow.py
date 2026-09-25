"""End-to-end next-step-v1 flows over the HTTP boundary.

No model, network, Firestore or credentials are involved: the conversational
model and the feedback composer are deterministic doubles, and every value is
synthetic and PII-safe.
"""

import logging
import secrets

from app.api.contracts_next_step import NEXT_STEP_CONTRACT, RESPONSE_CONTRACT_HEADER
from app.session.integration import (
    POLL_EXHAUSTED_MESSAGE,
    POLLING_FEEDBACK_INTERVAL,
    UNLOCK_CONFIRMATION_MESSAGE,
)
from app.session.record import session_record_to_document
from tests.api.doubles import (
    SYNTHETIC_TRANSCRIPT,
    integration_events_url,
    turns_url,
)
from tests.session.doubles import (
    NOW,
    make_dispatch,
    make_goal,
    make_identity,
    make_operation,
    make_record,
)

NEXT_STEP_HEADERS = {RESPONSE_CONTRACT_HEADER: NEXT_STEP_CONTRACT}

CONFLICT_ERROR = {
    "error": {
        "code": "conflict_or_duplicate",
        "message": "event cannot be correlated with the conversation",
    }
}


def _seed_dispatched(
    store, *, action: str = "UNLOCK_ACCOUNT", operation_id: str = "operation-1"
) -> None:
    store.documents["conversation-1"] = session_record_to_document(
        make_record(
            goal=make_goal(action, revision=1),
            identity=make_identity(NOW),
            dispatch=make_dispatch(action, revision=1, operation_id=operation_id),
            external_operation=make_operation(action, operation_id=operation_id),
        )
    )


def _status_body(sequence: int, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "event": "ACCOUNT_ACTION_STATUS",
        "operation_id": "operation-1",
        "action": "UNLOCK_ACCOUNT",
        "goal_revision": 1,
        "status": "NONE",
        "poll_sequence": sequence,
    }
    values.update(overrides)
    return values


def _presentation_body(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "event": "PASSWORD_PRESENTATION_RESULT",
        "operation_id": "operation-1",
        "action": "RESET_PASSWORD",
        "goal_revision": 1,
        "voice": "PLAYBACK_RETURNED",
        "email_requested": 1,
        "email_acceptance": "UNKNOWN",
        "email_delivery": "UNKNOWN",
    }
    values.update(overrides)
    return values


async def test_ambiguous_decision_returns_listen_without_a_goal(client, model, store) -> None:
    """An unresolved ambiguity stays conversational: no goal, no capture.

    The model decides the semantics (it asks the clarification); the boundary
    must project LISTEN and the durable state must stay free of plan,
    challenge, dispatch and operation.
    """
    from tests.session.doubles import make_decision

    model.decision = make_decision(
        message="¿Quieres restablecerla o desbloquearla?", route="CONTINUE"
    )
    response = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT},
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["next_step"] == "LISTEN"
    assert body["command"] is None
    document = store.documents["conversation-1"]
    assert document["goal"] is None
    assert document["confirmation"] is None
    assert document["dispatch"] is None
    assert document["external_operation"] is None


async def test_identity_valid_then_affirmative_dispatches_under_v1(client, model, store) -> None:
    from tests.session.doubles import make_decision

    model.decision = make_decision(
        route="COLLECT_IDENTITY",
        goal={"intent": "REQUEST", "action": "UNLOCK_ACCOUNT"},
    )
    turn = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT},
        headers=NEXT_STEP_HEADERS,
    )
    assert turn.status_code == 200
    assert turn.json()["next_step"] == "COLLECT_IDENTITY"

    validated = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "IDENTITY_VALIDATION_RESULT", "outcome": "VALID"},
        headers=NEXT_STEP_HEADERS,
    )
    assert validated.status_code == 200
    assert validated.json()["message"] == UNLOCK_CONFIRMATION_MESSAGE
    assert validated.json()["next_step"] == "LISTEN"
    document = store.documents["conversation-1"]
    assert document["confirmation"]["goal_revision"] == 1
    assert document["dispatch"] is None

    model.decision = make_decision(route="CONTINUE", confirmation_observation="AFFIRMATIVE")
    dispatched = await client.post(
        turns_url("conversation-1"),
        json={"transcript": "sí, adelante"},
        headers=NEXT_STEP_HEADERS,
    )
    assert dispatched.status_code == 200
    body = dispatched.json()
    assert body["next_step"] == "EXECUTE_ACTION"
    assert body["command"]["action"] == "UNLOCK_ACCOUNT"
    assert body["command"]["goal_revision"] == 1
    assert set(body) == {"message", "next_step", "operation_state", "command"}


async def test_v1_polling_uses_the_composer_only_when_due(client, store, clock, composer) -> None:
    _seed_dispatched(store)
    composer.message = "Sigo con tu solicitud."
    first = await client.post(
        integration_events_url("conversation-1"),
        json=_status_body(1),
        headers=NEXT_STEP_HEADERS,
    )
    assert first.status_code == 200
    assert first.json()["next_step"] == "POLL_RD"
    assert first.json()["message"] is None
    assert composer.calls == []

    clock.now = NOW + POLLING_FEEDBACK_INTERVAL
    due = await client.post(
        integration_events_url("conversation-1"),
        json=_status_body(2),
        headers=NEXT_STEP_HEADERS,
    )
    assert due.status_code == 200
    assert due.json()["message"] == "Sigo con tu solicitud."
    assert due.json()["next_step"] == "POLL_RD"
    assert len(composer.calls) == 1

    terminal = await client.post(
        integration_events_url("conversation-1"),
        json=_status_body(3, status="SUCESSO"),
        headers=NEXT_STEP_HEADERS,
    )
    assert terminal.status_code == 200
    assert terminal.json()["next_step"] == "LISTEN"
    assert terminal.json()["operation_state"] == "SUCCEEDED"
    assert len(composer.calls) == 1


async def test_v1_poll_sequence_conflicts_are_safe_409(client, store) -> None:
    _seed_dispatched(store)
    first = await client.post(
        integration_events_url("conversation-1"),
        json=_status_body(1),
        headers=NEXT_STEP_HEADERS,
    )
    assert first.status_code == 200
    jump = await client.post(
        integration_events_url("conversation-1"),
        json=_status_body(3),
        headers=NEXT_STEP_HEADERS,
    )
    assert jump.status_code == 409
    assert jump.json() == CONFLICT_ERROR
    changed = await client.post(
        integration_events_url("conversation-1"),
        json=_status_body(1, status="SUCESSO"),
        headers=NEXT_STEP_HEADERS,
    )
    assert changed.status_code == 409
    replay = await client.post(
        integration_events_url("conversation-1"),
        json=_status_body(1),
        headers=NEXT_STEP_HEADERS,
    )
    assert replay.status_code == 200
    assert replay.json()["next_step"] == "POLL_RD"


async def test_v1_poll_exhaustion_transfers_without_failing(client, store) -> None:
    _seed_dispatched(store)
    for sequence in range(1, 9):
        response = await client.post(
            integration_events_url("conversation-1"),
            json=_status_body(sequence),
            headers=NEXT_STEP_HEADERS,
        )
        assert response.json()["next_step"] == "POLL_RD"
    ninth = await client.post(
        integration_events_url("conversation-1"),
        json=_status_body(9),
        headers=NEXT_STEP_HEADERS,
    )
    assert ninth.status_code == 200
    assert ninth.json()["next_step"] == "TRANSFER"
    assert ninth.json()["message"] == POLL_EXHAUSTED_MESSAGE
    assert ninth.json()["operation_state"] == "PENDING"
    assert store.documents["conversation-1"]["external_operation"]["status"] == "pending"


async def test_v1_reset_presents_the_password_once(client, store) -> None:
    _seed_dispatched(store, action="RESET_PASSWORD")
    terminal = await client.post(
        integration_events_url("conversation-1"),
        json=_status_body(1, action="RESET_PASSWORD", status="SUCESSO"),
        headers=NEXT_STEP_HEADERS,
    )
    assert terminal.status_code == 200
    assert terminal.json()["next_step"] == "DELIVER_PASSWORD"
    assert terminal.json()["operation_state"] == "SUCCEEDED"

    presented = await client.post(
        integration_events_url("conversation-1"),
        json=_presentation_body(),
        headers=NEXT_STEP_HEADERS,
    )
    assert presented.status_code == 200
    assert presented.json()["next_step"] == "LISTEN"
    assert presented.json()["message"] is None
    document = store.documents["conversation-1"]
    assert document["password_presentation"]["email_delivery"] == "UNKNOWN"
    assert "password" not in repr(document["password_presentation"]).replace(
        "'password_presentation'", ""
    )

    duplicate = await client.post(
        integration_events_url("conversation-1"),
        json=_presentation_body(),
        headers=NEXT_STEP_HEADERS,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["next_step"] == "LISTEN"


async def test_v1_voice_failure_bootstraps_before_any_turn(client, store) -> None:
    response = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "VOICE_INPUT_FAILURE", "reason": "NO_SPEECH"},
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["next_step"] == "LISTEN"
    assert body["message"]
    assert body["operation_state"] is None
    document = store.documents["conversation-1"]
    assert document["turn_count"] == 0
    assert document["voice_retry_count"] == 1
    assert document["goal"] is None
    assert document["identity"] == {"validated_at": None, "caller_failures": 0}


async def test_legacy_voice_failure_still_conflicts_without_a_session(client, store) -> None:
    response = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "VOICE_INPUT_FAILURE", "reason": "NO_SPEECH"},
    )
    assert response.status_code == 409
    assert response.json() == CONFLICT_ERROR
    assert store.writes == 0
    assert store.documents == {}


async def test_identity_event_before_any_turn_never_creates_a_session(client, store) -> None:
    response = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "IDENTITY_VALIDATION_RESULT", "outcome": "VALID"},
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 409
    assert store.documents == {}


async def test_bootstrap_then_turn_continues_the_same_session(client, model, store) -> None:
    from tests.session.doubles import make_decision

    boot = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "VOICE_INPUT_FAILURE", "reason": "TIMEOUT"},
        headers=NEXT_STEP_HEADERS,
    )
    assert boot.status_code == 200
    model.decision = make_decision(
        route="COLLECT_IDENTITY",
        goal={"intent": "REQUEST", "action": "UNLOCK_ACCOUNT"},
    )
    turn = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT},
        headers=NEXT_STEP_HEADERS,
    )
    assert turn.status_code == 200
    assert turn.json()["next_step"] == "COLLECT_IDENTITY"
    document = store.documents["conversation-1"]
    assert document["turn_count"] == 1
    assert document["voice_retry_count"] == 0
    assert document["goal"] == {"action": "UNLOCK_ACCOUNT", "revision": 1}


async def test_v1_voice_policy_over_http_and_reset_after_a_turn(client, model, store) -> None:
    from tests.session.doubles import make_decision

    for expected in ("LISTEN", "LISTEN", "LISTEN", "TRANSFER"):
        response = await client.post(
            integration_events_url("conversation-1"),
            json={"event": "VOICE_INPUT_FAILURE", "reason": "NO_SPEECH"},
            headers=NEXT_STEP_HEADERS,
        )
        assert response.status_code == 200
        assert response.json()["next_step"] == expected
    # A voice failure never reaches the model and never creates business state.
    assert model.calls == []
    document = store.documents["conversation-1"]
    assert document["voice_retry_count"] == 4
    assert document["turn_count"] == 0
    assert document["goal"] is None
    assert document["identity"] == {"validated_at": None, "caller_failures": 0}

    model.decision = make_decision(
        route="COLLECT_IDENTITY",
        goal={"intent": "REQUEST", "action": "UNLOCK_ACCOUNT"},
    )
    turn = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT},
        headers=NEXT_STEP_HEADERS,
    )
    assert turn.status_code == 200
    assert turn.json()["next_step"] == "COLLECT_IDENTITY"
    document = store.documents["conversation-1"]
    assert document["voice_retry_count"] == 0
    assert document["turn_count"] == 1


async def test_v1_capture_exhaustion_transfers(client, store) -> None:
    _seed_dispatched(store)
    response = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "IDENTITY_INPUT_FAILURE", "reason": "CAPTURE_EXHAUSTED"},
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["next_step"] == "TRANSFER"
    assert response.json()["operation_state"] == "PENDING"
    assert store.documents["conversation-1"]["identity"]["caller_failures"] == 0


async def test_v1_never_leaks_pii_or_raw_status(client, store, caplog) -> None:
    operation_canary = f"synthetic-op-{secrets.token_hex(4)}"
    status_canary = f"STATUS_{secrets.token_hex(4)}"
    _seed_dispatched(store, operation_id=operation_canary)
    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            integration_events_url("conversation-1"),
            json=_status_body(1, operation_id=operation_canary, status=status_canary),
            headers=NEXT_STEP_HEADERS,
        )
    assert response.status_code == 200
    assert status_canary not in response.text
    assert status_canary not in caplog.text
    assert status_canary not in repr(store.documents["conversation-1"])
    assert "SYNTHETIC-PASSWORD-0000" not in repr(store.documents["conversation-1"])
