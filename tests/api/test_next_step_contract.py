"""HTTP tests for the next-step-v1 selector and common envelope.

No model, network, Firestore or credentials are involved. The selector is
explicit: no header keeps the legacy contract, the exact version selects the
new envelope and any empty, repeated or unknown version fails closed with 400
after authentication.
"""

import pytest
from pydantic import ValidationError

from app.api.contracts import TurnResponse
from app.api.contracts_next_step import (
    NEXT_STEP_CONTRACT,
    RESPONSE_CONTRACT_HEADER,
    NextStepResponse,
    ResponseContract,
    select_response_contract,
)
from app.api.errors import UnsupportedResponseContractError
from app.session.outcome import NextStep
from app.session.turns import ExternalActionCommand
from tests.api.doubles import (
    SYNTHETIC_TRANSCRIPT,
    integration_events_url,
    turns_url,
)
from tests.session.doubles import make_decision

NEXT_STEP_HEADERS = {RESPONSE_CONTRACT_HEADER: NEXT_STEP_CONTRACT}

UNSUPPORTED_CONTRACT_ERROR = {
    "error": {
        "code": "unsupported_response_contract",
        "message": "unsupported response contract",
    }
}

VALIDATION_ERROR = {
    "error": {"code": "validation", "message": "request validation failed"},
}


# --- selector unit contract -------------------------------------------------


def test_absent_header_selects_the_legacy_contract() -> None:
    assert select_response_contract([]) is ResponseContract.LEGACY


def test_the_exact_version_selects_next_step_v1() -> None:
    assert select_response_contract(["next-step-v1"]) is ResponseContract.NEXT_STEP_V1


@pytest.mark.parametrize("values", [[""], ["v2"], ["next-step-v1 "], ["Next-Step-V1"]])
def test_empty_or_unknown_versions_fail_closed(values: list[str]) -> None:
    with pytest.raises(UnsupportedResponseContractError):
        select_response_contract(values)


def test_repeated_header_never_resolves_by_position() -> None:
    with pytest.raises(UnsupportedResponseContractError):
        select_response_contract(["next-step-v1", "next-step-v1"])


def test_envelope_rejects_a_command_outside_execute_action() -> None:
    command = ExternalActionCommand(
        operation_id="operation-1", action="UNLOCK_ACCOUNT", goal_revision=1
    )
    with pytest.raises(ValidationError):
        NextStepResponse(next_step=NextStep.LISTEN, command=command)
    with pytest.raises(ValidationError):
        NextStepResponse(next_step=NextStep.EXECUTE_ACTION)
    allowed = NextStepResponse(next_step=NextStep.EXECUTE_ACTION, command=command)
    assert allowed.command == command


def test_legacy_turn_response_still_requires_its_route() -> None:
    with pytest.raises(ValidationError):
        TurnResponse(message="synthetic message", route="LISTEN", turn_id="turn-1")


# --- selector over HTTP -----------------------------------------------------


async def test_turns_without_the_header_keep_the_legacy_envelope(client) -> None:
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message", "route", "turn_id", "command"}
    assert body["route"] == "CONTINUE"


async def test_turns_with_the_header_return_the_common_envelope(client, model) -> None:
    model.decision = make_decision(message="synthetic message", route="CONTINUE")
    response = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT},
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 200
    assert response.json() == {
        "message": "synthetic message",
        "next_step": "LISTEN",
        "operation_state": None,
        "command": None,
    }


async def test_integration_events_with_the_header_return_the_common_envelope(client, store) -> None:
    from app.session.record import session_record_to_document
    from tests.session.doubles import make_goal, make_identity, make_record

    store.documents["conversation-1"] = session_record_to_document(
        make_record(goal=make_goal("UNLOCK_ACCOUNT", revision=1), identity=make_identity())
    )
    response = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "IDENTITY_VALIDATION_RESULT", "outcome": "VALID"},
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message", "next_step", "operation_state", "command"}
    assert body["next_step"] == "LISTEN"
    assert body["operation_state"] is None
    assert body["command"] is None


@pytest.mark.parametrize("value", ["", "v2", "next-step-v1 "])
async def test_unknown_contract_version_is_a_safe_400(client, value) -> None:
    for url, payload in (
        (turns_url("conversation-1"), {"transcript": SYNTHETIC_TRANSCRIPT}),
        (
            integration_events_url("conversation-1"),
            {"event": "VOICE_INPUT_FAILURE", "reason": "NO_SPEECH"},
        ),
    ):
        response = await client.post(url, json=payload, headers={RESPONSE_CONTRACT_HEADER: value})
        assert response.status_code == 400
        assert response.json() == UNSUPPORTED_CONTRACT_ERROR


async def test_a_repeated_contract_header_is_a_safe_400(client) -> None:
    response = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT},
        headers=[
            (RESPONSE_CONTRACT_HEADER, NEXT_STEP_CONTRACT),
            (RESPONSE_CONTRACT_HEADER, NEXT_STEP_CONTRACT),
        ],
    )
    assert response.status_code == 400
    assert response.json() == UNSUPPORTED_CONTRACT_ERROR


async def test_authentication_precedes_the_contract_selector(anonymous_client) -> None:
    response = await anonymous_client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT},
        headers={RESPONSE_CONTRACT_HEADER: "v2"},
    )
    assert response.status_code == 401


async def test_selector_precedes_payload_validation_on_events(client) -> None:
    """The event body is parsed against the selected schema, never before it."""
    response = await client.post(
        integration_events_url("conversation-1"),
        json={"unknown": True},
        headers={RESPONSE_CONTRACT_HEADER: "v2"},
    )
    assert response.status_code == 400
    assert response.json() == UNSUPPORTED_CONTRACT_ERROR


# --- closed vocabularies ----------------------------------------------------


async def test_legacy_events_reject_the_next_step_only_vocabulary(client, store) -> None:
    from app.session.record import session_record_to_document
    from tests.session.doubles import (
        make_dispatch,
        make_goal,
        make_identity,
        make_operation,
        make_record,
    )

    store.documents["conversation-1"] = session_record_to_document(
        make_record(
            goal=make_goal("UNLOCK_ACCOUNT", revision=1),
            identity=make_identity(),
            dispatch=make_dispatch("UNLOCK_ACCOUNT", revision=1, operation_id="operation-1"),
            external_operation=make_operation("UNLOCK_ACCOUNT", operation_id="operation-1"),
        )
    )
    payloads = [
        {
            "event": "ACCOUNT_ACTION_STATUS",
            "operation_id": "operation-1",
            "action": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "status": "NONE",
            "poll_sequence": 1,
        },
        {
            "event": "PASSWORD_PRESENTATION_RESULT",
            "operation_id": "operation-1",
            "action": "RESET_PASSWORD",
            "goal_revision": 1,
            "voice": "PLAYBACK_RETURNED",
            "email_requested": 1,
            "email_acceptance": "UNKNOWN",
            "email_delivery": "UNKNOWN",
        },
        {"event": "IDENTITY_INPUT_FAILURE", "reason": "CAPTURE_EXHAUSTED"},
    ]
    writes_before = store.writes
    for payload in payloads:
        response = await client.post(integration_events_url("conversation-1"), json=payload)
        assert response.status_code == 422
        assert response.json() == VALIDATION_ERROR
    assert store.writes == writes_before


async def test_next_step_events_require_the_strict_poll_sequence(client, store) -> None:
    from app.session.record import session_record_to_document
    from tests.session.doubles import (
        make_dispatch,
        make_goal,
        make_identity,
        make_operation,
        make_record,
    )

    store.documents["conversation-1"] = session_record_to_document(
        make_record(
            goal=make_goal("UNLOCK_ACCOUNT", revision=1),
            identity=make_identity(),
            dispatch=make_dispatch("UNLOCK_ACCOUNT", revision=1, operation_id="operation-1"),
            external_operation=make_operation("UNLOCK_ACCOUNT", operation_id="operation-1"),
        )
    )
    missing = await client.post(
        integration_events_url("conversation-1"),
        json={
            "event": "ACCOUNT_ACTION_STATUS",
            "operation_id": "operation-1",
            "action": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "status": "NONE",
        },
        headers=NEXT_STEP_HEADERS,
    )
    assert missing.status_code == 422
    non_integer = await client.post(
        integration_events_url("conversation-1"),
        json={
            "event": "ACCOUNT_ACTION_STATUS",
            "operation_id": "operation-1",
            "action": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "status": "NONE",
            "poll_sequence": "1",
        },
        headers=NEXT_STEP_HEADERS,
    )
    assert non_integer.status_code == 422


# --- message normalization --------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("line\nbreak and tab\t", "line break and tab"),
        ('quote " inside', 'quote " inside'),
        ("apostrophe ' inside", "apostrophe ' inside"),
        ("back\\slash", "back\\slash"),
        ("acentos: áéíóúñ¿¡", "acentos: áéíóúñ¿¡"),
    ],
)
async def test_v1_turn_messages_are_normalized_without_rewriting(
    client, model, raw, expected
) -> None:
    model.decision = make_decision(message=raw, route="CONTINUE")
    response = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT},
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["message"] == expected


async def test_legacy_turn_messages_keep_the_exact_model_text(client, model) -> None:
    raw = "line\nbreak"
    model.decision = make_decision(message=raw, route="CONTINUE")
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.json()["message"] == raw


def test_next_step_response_null_message_stays_null() -> None:
    from app.api.contracts_next_step import next_step_response

    envelope = next_step_response(message=None, next_step=NextStep.LISTEN)
    assert envelope.message is None
