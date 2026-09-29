"""Narrow numeric compatibility for the next-step-v1 boundary.

XCALLY may render a numeric placeholder as a quoted canonical decimal. Only
the closed next-step-v1 field whitelist accepts those strings, only at the
HTTP boundary, and only before the strict domain schema validates; the legacy
payload reaches its adapter untouched. No model, network, Firestore or
credentials are involved.
"""

import logging

import pytest
from pydantic import ValidationError

import app.api.app as app_module
from app.api.app import _NEXT_STEP_EVENT_ADAPTER, _normalize_next_step_numbers
from app.api.contracts_next_step import NEXT_STEP_CONTRACT, RESPONSE_CONTRACT_HEADER
from app.session.integration import (
    AccountActionErrorV1Event,
    AccountActionStatusV1Event,
    PasswordPresentationResultEvent,
)
from app.session.record import OperationStatus, session_record_to_document
from tests.api.doubles import integration_events_url
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

VALIDATION_ERROR = {
    "error": {"code": "validation", "message": "request validation failed"},
}


def _status_payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "event": "ACCOUNT_ACTION_STATUS",
        "operation_id": "operation-1",
        "action": "UNLOCK_ACCOUNT",
        "goal_revision": 1,
        "status": "NONE",
        "poll_sequence": 1,
    }
    values.update(overrides)
    return values


def _error_payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "event": "ACCOUNT_ACTION_ERROR",
        "operation_id": "operation-1",
        "action": "UNLOCK_ACCOUNT",
        "goal_revision": 1,
        "phase": "POLL",
        "error_kind": "UNAVAILABLE",
        "http_status": None,
        "poll_sequence": 1,
    }
    values.update(overrides)
    return values


def _presentation_payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "event": "PASSWORD_PRESENTATION_RESULT",
        "operation_id": "operation-1",
        "action": "RESET_PASSWORD",
        "goal_revision": 1,
        "voice": "PLAYBACK_RETURNED",
    }
    values.update(overrides)
    return values


def _validate(payload: dict[str, object]):  # type: ignore[no-untyped-def]
    return _NEXT_STEP_EVENT_ADAPTER.validate_python(_normalize_next_step_numbers(payload))


def _seed_dispatched(store, *, action: str = "UNLOCK_ACCOUNT", status: str = "pending") -> None:  # type: ignore[no-untyped-def]
    store.documents["conversation-1"] = session_record_to_document(
        make_record(
            goal=make_goal(action, revision=1),
            identity=make_identity(NOW),
            dispatch=make_dispatch(action, revision=1, operation_id="operation-1"),
            external_operation=make_operation(
                action, OperationStatus(status), operation_id="operation-1"
            ),
        )
    )


# --- helper unit contract ---------------------------------------------------


def test_native_ints_pass_through_unchanged() -> None:
    status = _validate(_status_payload(goal_revision=0, poll_sequence=2))
    assert status.goal_revision == 0
    assert status.poll_sequence == 2
    error = _validate(_error_payload(goal_revision=1, poll_sequence=2))
    assert error.goal_revision == 1
    assert error.poll_sequence == 2
    presentation = _validate(_presentation_payload(goal_revision=1))
    assert presentation.goal_revision == 1


def test_canonical_decimal_strings_are_normalized_to_native_ints() -> None:
    status = _validate(_status_payload(goal_revision="10", poll_sequence="2"))
    assert type(status.goal_revision) is int
    assert type(status.poll_sequence) is int
    assert status.goal_revision == 10
    assert status.poll_sequence == 2
    error = _validate(_error_payload(goal_revision="0", poll_sequence="1"))
    assert type(error.goal_revision) is int
    assert type(error.poll_sequence) is int
    presentation = _validate(_presentation_payload(goal_revision="1"))
    assert type(presentation.goal_revision) is int
    assert presentation.goal_revision == 1


@pytest.mark.parametrize(
    "value",
    [
        "",
        "01",
        "001",
        " 1",
        "1 ",
        "+1",
        "-1",
        "1.0",
        "1e2",
        True,
        1.0,
        "{GOAL_REVISION}",
        "{RD_POLL_COUNT}",
        "{MAIL_REQUESTED}",
    ],
)
def test_non_canonical_goal_revision_is_left_to_fail_closed(value: object) -> None:
    with pytest.raises(ValidationError):
        _validate(_status_payload(goal_revision=value))


@pytest.mark.parametrize(
    "value",
    [
        "",
        "01",
        "001",
        " 1",
        "1 ",
        "+1",
        "-1",
        "1.0",
        "1e2",
        True,
        1.0,
        "{GOAL_REVISION}",
        "{RD_POLL_COUNT}",
        "{MAIL_REQUESTED}",
    ],
)
def test_non_canonical_poll_sequence_is_left_to_fail_closed(value: object) -> None:
    with pytest.raises(ValidationError):
        _validate(_status_payload(poll_sequence=value))


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (_status_payload(poll_sequence="0"), "poll_sequence"),
        (_status_payload(goal_revision=-1), "goal_revision"),
    ],
)
def test_canonical_values_outside_the_field_limits_are_rejected(
    payload: dict[str, object], field: str
) -> None:
    with pytest.raises(ValidationError):
        _validate(payload)


def test_only_the_whitelisted_events_and_fields_are_normalized() -> None:
    untouched = _normalize_next_step_numbers(_error_payload(http_status="500"))
    assert untouched["http_status"] == "500"
    assert untouched["goal_revision"] == 1
    other_event = _normalize_next_step_numbers(
        {"event": "VOICE_INPUT_FAILURE", "reason": "NO_SPEECH", "goal_revision": "1"}
    )
    assert other_event["goal_revision"] == "1"
    non_object = _normalize_next_step_numbers(["not", "an", "object"])
    assert non_object == ["not", "an", "object"]


def test_normalization_never_adds_removes_or_renames_keys() -> None:
    payload = _status_payload(poll_sequence="2")
    normalized = _normalize_next_step_numbers(payload)
    assert set(normalized) == set(payload)
    without_optional = _normalize_next_step_numbers(
        _error_payload(phase="DISPATCH", poll_sequence=None)
    )
    assert "poll_sequence" in without_optional


def test_dispatch_error_without_a_sequence_stays_valid_and_with_one_is_rejected() -> None:
    payload = _error_payload(phase="DISPATCH", poll_sequence=None)
    del payload["poll_sequence"]
    validated = _validate(payload)
    assert isinstance(validated, AccountActionErrorV1Event)
    with pytest.raises(ValidationError):
        _validate(_error_payload(phase="DISPATCH", poll_sequence="1"))


# --- strictness of the domain models ---------------------------------------


def test_domain_models_reject_numeric_strings_without_the_boundary() -> None:
    for model, payload in (
        (AccountActionStatusV1Event, _status_payload(goal_revision="1")),
        (AccountActionErrorV1Event, _error_payload(goal_revision="1")),
        (PasswordPresentationResultEvent, _presentation_payload(goal_revision="1")),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)
    with pytest.raises(ValidationError):
        AccountActionStatusV1Event.model_validate(_status_payload(poll_sequence="1"))


def test_boolean_is_never_accepted_as_a_number() -> None:
    for payload in (
        _status_payload(goal_revision=True),
        _status_payload(poll_sequence=True),
    ):
        with pytest.raises(ValidationError):
            _validate(payload)


# --- HTTP functional contract ----------------------------------------------


async def test_canonical_status_strings_reach_the_domain_as_ints(client, model, store) -> None:
    _seed_dispatched(store)
    response = await client.post(
        integration_events_url("conversation-1"),
        json=_status_payload(goal_revision="1", poll_sequence="1"),
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["next_step"] == "POLL_RD"
    assert body["operation_state"] == "PENDING"
    assert model.calls == []
    polling = store.documents["conversation-1"]["polling"]
    receipt = polling["receipts"][0]  # type: ignore[index]
    assert receipt["sequence"] == 1
    assert type(receipt["sequence"]) is int
    assert len(polling["receipts"]) == 1  # type: ignore[index]


async def test_canonical_poll_error_strings_reach_the_domain_as_ints(client, store) -> None:
    _seed_dispatched(store)
    response = await client.post(
        integration_events_url("conversation-1"),
        json=_error_payload(goal_revision="1", poll_sequence="1"),
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["next_step"] == "POLL_RD"
    assert body["operation_state"] == "PENDING"
    polling = store.documents["conversation-1"]["polling"]
    assert polling["receipts"][0]["sequence"] == 1  # type: ignore[index]


async def test_canonical_dispatch_error_without_a_sequence_is_accepted(client, store) -> None:
    _seed_dispatched(store)
    payload = _error_payload(goal_revision="1", phase="DISPATCH", poll_sequence=None)
    del payload["poll_sequence"]
    response = await client.post(
        integration_events_url("conversation-1"),
        json=payload,
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["operation_state"] == "UNKNOWN"


async def test_canonical_presentation_string_persists_native_goal_revision(client, store) -> None:
    _seed_dispatched(store, action="RESET_PASSWORD", status="confirmed")
    response = await client.post(
        integration_events_url("conversation-1"),
        json=_presentation_payload(goal_revision="1"),
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["next_step"] == "LISTEN"
    presentation = store.documents["conversation-1"]["password_presentation"]
    assert presentation["goal_revision"] == 1
    assert type(presentation["goal_revision"]) is int
    # The legacy email facts are never produced by the active event.
    assert presentation["email_requested"] is None
    assert presentation["caller_finished"] is False


async def test_presentation_event_rejects_legacy_email_fields(client, store) -> None:
    _seed_dispatched(store, action="RESET_PASSWORD", status="confirmed")
    payload = _presentation_payload()
    payload["email_requested"] = 1
    response = await client.post(
        integration_events_url("conversation-1"),
        json=payload,
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 422


async def test_canonical_strings_on_an_unknown_session_reach_the_domain_guards(
    client, store
) -> None:
    """A 409 proves normalization and schema acceptance; a 422 would not."""
    response = await client.post(
        integration_events_url("conversation-missing"),
        json=_status_payload(goal_revision="1", poll_sequence="1"),
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 409
    assert response.json() == CONFLICT_ERROR
    assert store.writes == 0


async def test_non_canonical_string_still_fails_validation(client, store) -> None:
    _seed_dispatched(store)
    writes_before = store.writes
    response = await client.post(
        integration_events_url("conversation-1"),
        json=_status_payload(poll_sequence="01"),
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 422
    assert response.json() == VALIDATION_ERROR
    assert store.writes == writes_before


async def test_placeholders_are_never_resolved(client, store) -> None:
    _seed_dispatched(store)
    response = await client.post(
        integration_events_url("conversation-1"),
        json=_status_payload(poll_sequence="{RD_POLL_COUNT}", goal_revision="{GOAL_REVISION}"),
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 422
    assert response.json() == VALIDATION_ERROR


# --- legacy is untouched ----------------------------------------------------


async def test_legacy_payloads_never_run_the_normalizer(client, monkeypatch, store) -> None:
    calls: list[object] = []
    original = app_module._normalize_next_step_numbers

    def spy(payload: object) -> object:
        calls.append(payload)
        return original(payload)

    monkeypatch.setattr(app_module, "_normalize_next_step_numbers", spy)
    legacy = await client.post(
        integration_events_url("conversation-1"),
        json={"event": "VOICE_INPUT_FAILURE", "reason": "NO_SPEECH"},
    )
    assert legacy.status_code == 409
    assert calls == []
    _seed_dispatched(store)
    v1 = await client.post(
        integration_events_url("conversation-1"),
        json=_status_payload(poll_sequence="1"),
        headers=NEXT_STEP_HEADERS,
    )
    assert v1.status_code == 200
    assert len(calls) == 1


async def test_legacy_regression_is_unchanged(client, store) -> None:
    _seed_dispatched(store)
    response = await client.post(
        integration_events_url("conversation-1"),
        json={
            "event": "ACCOUNT_ACTION_STATUS",
            "operation_id": "operation-1",
            "action": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "status": "NONE",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"acknowledged", "operation_state", "directive", "message"}
    assert body["directive"] == "POLL_RD"
    assert body["operation_state"] == "PENDING"
    assert store.documents["conversation-1"]["polling"] is None


async def test_rejected_numeric_values_never_reach_the_logs(client, caplog) -> None:
    canary = "{RD_POLL_COUNT}"
    logger = logging.getLogger("cu013")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="cu013")
    try:
        response = await client.post(
            integration_events_url("conversation-1"),
            json=_status_payload(poll_sequence=canary),
            headers=NEXT_STEP_HEADERS,
        )
    finally:
        logger.removeHandler(caplog.handler)
    assert response.status_code == 422
    assert canary not in caplog.text
    assert canary not in response.text
    assert "request_validation_failed" in caplog.text
    assert "poll_sequence" in caplog.text
