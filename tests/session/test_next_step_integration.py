"""Next-step-v1 integration semantics: sequence, budget, presentation, feedback.

No model, network, Firestore or credentials are involved. The composer is a
deterministic double and every value is synthetic and PII-safe.
"""

from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from app.session.actions import Action
from app.session.feedback import PollingFeedbackRequest
from app.session.integration import (
    POLL_EXHAUSTED_MESSAGE,
    POLLING_FEEDBACK_INTERVAL,
    RESET_CONFIRMED_MESSAGE,
    UNLOCK_COMPLETED_MESSAGE,
    AccountActionErrorV1Event,
    AccountActionStatusV1Event,
    IdentityInputFailureEvent,
    IntegrationEventRejected,
    IntegrationEventService,
    IntegrationOperationState,
    PasswordPresentationResultEvent,
)
from app.session.outcome import NextStep
from app.session.record import (
    OperationStatus,
    session_record_from_document,
    session_record_to_document,
)
from app.session.repository import SessionRepository
from tests.session.doubles import (
    NOW,
    FrozenClock,
    InMemorySessionDocumentStore,
    make_dispatch,
    make_goal,
    make_identity,
    make_operation,
    make_record,
)


class RecordingComposer:
    """Deterministic composer double: records calls, returns a canned message."""

    def __init__(
        self,
        *,
        message: str | None = "Sigo con tu solicitud.",
        error: Exception | None = None,
    ) -> None:
        self.calls: list[PollingFeedbackRequest] = []
        self.message = message
        self.error = error

    async def compose(self, request: PollingFeedbackRequest) -> str | None:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.message


def _service(
    store: InMemorySessionDocumentStore,
    *,
    clock: FrozenClock | None = None,
    composer: RecordingComposer | None = None,
) -> IntegrationEventService:
    return IntegrationEventService(
        SessionRepository(store),
        clock=clock or FrozenClock(),
        composer=composer,
    )


def _seed_dispatched(
    store: InMemorySessionDocumentStore,
    *,
    action: Action = Action.UNLOCK_ACCOUNT,
    status: OperationStatus = OperationStatus.PENDING,
) -> None:
    record = make_record(
        goal=make_goal(action, revision=1),
        identity=make_identity(NOW),
        dispatch=make_dispatch(action, revision=1, operation_id="operation-1"),
        external_operation=make_operation(action, status, operation_id="operation-1"),
    )
    store.documents["conversation-1"] = session_record_to_document(record)


def _stored(store: InMemorySessionDocumentStore):  # type: ignore[no-untyped-def]
    return session_record_from_document(store.documents["conversation-1"])


def _status(sequence: int, **overrides: object) -> AccountActionStatusV1Event:
    values: dict[str, object] = {
        "event": "ACCOUNT_ACTION_STATUS",
        "operation_id": "operation-1",
        "action": "UNLOCK_ACCOUNT",
        "goal_revision": 1,
        "status": "NONE",
        "poll_sequence": sequence,
    }
    values.update(overrides)
    return AccountActionStatusV1Event.model_validate(values)


def _poll_error(sequence: int, **overrides: object) -> AccountActionErrorV1Event:
    values: dict[str, object] = {
        "event": "ACCOUNT_ACTION_ERROR",
        "operation_id": "operation-1",
        "action": "UNLOCK_ACCOUNT",
        "goal_revision": 1,
        "phase": "POLL",
        "error_kind": "TIMEOUT",
        "http_status": None,
        "poll_sequence": sequence,
    }
    values.update(overrides)
    return AccountActionErrorV1Event.model_validate(values)


def _presentation(**overrides: object) -> PasswordPresentationResultEvent:
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
    return PasswordPresentationResultEvent.model_validate(values)


# --- capture exhaustion -----------------------------------------------------


async def test_capture_exhaustion_keeps_goal_and_operation_and_transfers() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    writes_before = store.writes
    event = IdentityInputFailureEvent.model_validate(
        {"event": "IDENTITY_INPUT_FAILURE", "reason": "CAPTURE_EXHAUSTED"}
    )
    outcome = await _service(store).handle_event("conversation-1", event)
    assert outcome.next_step is NextStep.TRANSFER
    assert outcome.operation_state is IntegrationOperationState.PENDING
    assert outcome.message
    assert store.writes == writes_before
    stored = _stored(store)
    assert stored.goal is not None and stored.goal.revision == 1
    assert stored.identity.caller_failures == 0
    assert stored.external_operation is not None
    assert stored.external_operation.status is OperationStatus.PENDING


def test_capture_exhaustion_rejects_any_other_reason() -> None:
    with pytest.raises(ValidationError):
        IdentityInputFailureEvent.model_validate(
            {"event": "IDENTITY_INPUT_FAILURE", "reason": "NO_MORE_TRIES"}
        )


# --- sequence, dedupe and budget -------------------------------------------


async def test_first_observation_must_be_sequence_one() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    with pytest.raises(IntegrationEventRejected):
        await _service(store).handle_event("conversation-1", _status(2))


async def test_sequence_jump_is_rejected() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    service = _service(store)
    await service.handle_event("conversation-1", _status(1))
    with pytest.raises(IntegrationEventRejected):
        await service.handle_event("conversation-1", _status(3))


async def test_same_sequence_with_the_same_observation_is_an_idempotent_ack() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    service = _service(store)
    first = await service.handle_event("conversation-1", _status(1))
    writes_after_first = store.writes
    replay = await service.handle_event("conversation-1", _status(1))
    assert first.next_step is NextStep.POLL_RD
    assert replay.next_step is NextStep.POLL_RD
    assert replay.message is None
    assert store.writes == writes_after_first
    assert _stored(store).polling is not None
    assert _stored(store).polling.observations_used == 1  # type: ignore[union-attr]


async def test_same_sequence_with_a_different_observation_conflicts() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    service = _service(store)
    await service.handle_event("conversation-1", _status(1))
    with pytest.raises(IntegrationEventRejected):
        await service.handle_event("conversation-1", _status(1, status="SUCESSO"))


async def test_unknown_status_consumes_one_observation_without_mutating() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    outcome = await _service(store).handle_event(
        "conversation-1", _status(1, status="STATUS_NUEVO_RD")
    )
    assert outcome.next_step is NextStep.POLL_RD
    assert outcome.operation_state is IntegrationOperationState.PENDING
    stored = _stored(store)
    assert stored.external_operation is not None
    assert stored.external_operation.status is OperationStatus.PENDING
    assert stored.polling is not None
    assert stored.polling.observations_used == 1
    assert "STATUS_NUEVO_RD" not in repr(store.documents["conversation-1"])


async def test_poll_error_consumes_one_observation() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    outcome = await _service(store).handle_event("conversation-1", _poll_error(1))
    assert outcome.next_step is NextStep.POLL_RD
    assert outcome.operation_state is IntegrationOperationState.PENDING
    assert _stored(store).polling is not None
    assert _stored(store).polling.observations_used == 1  # type: ignore[union-attr]


async def test_dispatch_error_never_consumes_get_budget() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    service = _service(store)
    dispatch_error = AccountActionErrorV1Event.model_validate(
        {
            "event": "ACCOUNT_ACTION_ERROR",
            "operation_id": "operation-1",
            "action": "UNLOCK_ACCOUNT",
            "goal_revision": 1,
            "phase": "DISPATCH",
            "error_kind": "TIMEOUT",
            "http_status": None,
        }
    )
    outcome = await service.handle_event("conversation-1", dispatch_error)
    assert outcome.next_step is NextStep.POLL_RD
    assert outcome.operation_state is IntegrationOperationState.UNKNOWN
    stored = _stored(store)
    assert stored.polling is None
    assert stored.external_operation is not None
    assert stored.external_operation.status is OperationStatus.UNKNOWN


async def test_ninth_non_terminal_observation_transfers_without_failing() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    service = _service(store)
    for sequence in range(1, 9):
        outcome = await service.handle_event("conversation-1", _status(sequence))
        assert outcome.next_step is NextStep.POLL_RD
    ninth = await service.handle_event("conversation-1", _status(9))
    assert ninth.next_step is NextStep.TRANSFER
    assert ninth.message == POLL_EXHAUSTED_MESSAGE
    assert ninth.operation_state is IntegrationOperationState.PENDING
    stored = _stored(store)
    assert stored.external_operation is not None
    assert stored.external_operation.status is OperationStatus.PENDING
    assert stored.polling is not None
    assert stored.polling.observations_used == 9


async def test_non_terminal_observation_after_the_budget_is_rejected() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    service = _service(store)
    for sequence in range(1, 10):
        await service.handle_event("conversation-1", _status(sequence))
    with pytest.raises(IntegrationEventRejected):
        await service.handle_event("conversation-1", _status(10))


async def test_terminal_after_budget_exhaustion_still_reconciles() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    service = _service(store)
    for sequence in range(1, 10):
        await service.handle_event("conversation-1", _status(sequence))
    terminal = await service.handle_event("conversation-1", _status(10, status="SUCESSO"))
    assert terminal.next_step is NextStep.LISTEN
    assert terminal.message == UNLOCK_COMPLETED_MESSAGE
    assert terminal.operation_state is IntegrationOperationState.SUCCEEDED
    assert _stored(store).external_operation is not None
    assert _stored(store).external_operation.status is OperationStatus.CONFIRMED  # type: ignore[union-attr]


async def test_every_poll_event_never_re_posts() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    service = _service(store)
    await service.handle_event("conversation-1", _status(1))
    await service.handle_event("conversation-1", _poll_error(2))
    await service.handle_event("conversation-1", _status(3, status="FALHA_AD"))
    stored = _stored(store)
    assert stored.dispatch is not None
    assert stored.dispatch.operation_id == "operation-1"
    assert stored.external_operation is not None
    assert stored.external_operation.operation_id == "operation-1"
    assert stored.external_operation.status is OperationStatus.FAILED


# --- password presentation --------------------------------------------------


async def test_reset_success_requests_password_presentation() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store, action=Action.RESET_PASSWORD)
    outcome = await _service(store).handle_event(
        "conversation-1", _status(1, action="RESET_PASSWORD", status="SUCESSO")
    )
    assert outcome.next_step is NextStep.DELIVER_PASSWORD
    assert outcome.message == RESET_CONFIRMED_MESSAGE
    assert outcome.operation_state is IntegrationOperationState.SUCCEEDED


async def test_unlock_success_keeps_the_conversation_open_and_resolves_the_goal() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    outcome = await _service(store).handle_event("conversation-1", _status(1, status="SUCESSO"))
    assert outcome.next_step is NextStep.LISTEN
    assert outcome.message == UNLOCK_COMPLETED_MESSAGE
    assert outcome.operation_state is IntegrationOperationState.SUCCEEDED
    stored = _stored(store)
    # The operation is complete, the conversation is not: the goal is resolved
    # so nothing can be re-dispatched, while the history stays for grounding.
    assert stored.goal is None
    assert stored.confirmation is None
    assert stored.external_operation is not None
    assert stored.external_operation.status is OperationStatus.CONFIRMED
    assert stored.external_operation.is_active() is False


async def test_presentation_persists_facts_and_a_duplicate_acks() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store, action=Action.RESET_PASSWORD)
    service = _service(store)
    terminal = await service.handle_event(
        "conversation-1", _status(1, action="RESET_PASSWORD", status="SUCESSO")
    )
    assert terminal.next_step is NextStep.DELIVER_PASSWORD

    presented = await service.handle_event("conversation-1", _presentation())
    assert presented.next_step is NextStep.LISTEN
    assert presented.message is None
    stored = _stored(store)
    assert stored.password_presentation is not None
    assert stored.password_presentation.voice.value == "PLAYBACK_RETURNED"
    assert stored.password_presentation.email_requested == 1
    assert stored.password_presentation.email_acceptance.value == "UNKNOWN"
    assert stored.password_presentation.email_delivery.value == "UNKNOWN"

    writes_before = store.writes
    duplicate = await service.handle_event("conversation-1", _presentation())
    assert duplicate.next_step is NextStep.LISTEN
    assert store.writes == writes_before
    assert _stored(store).password_presentation == stored.password_presentation


async def test_presentation_failure_keeps_the_reset_confirmed_and_listens() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store, action=Action.RESET_PASSWORD)
    service = _service(store)
    terminal = await service.handle_event(
        "conversation-1", _status(1, action="RESET_PASSWORD", status="SUCESSO")
    )
    assert terminal.next_step is NextStep.DELIVER_PASSWORD

    failed = await service.handle_event(
        "conversation-1",
        _presentation(voice="PRESENTATION_FAILED_BEFORE_PLAYBACK", email_requested=0),
    )
    # A presentation that never reached playback is its own fact: the reset
    # stays confirmed, nothing is re-dispatched and the conversation continues.
    assert failed.next_step is NextStep.LISTEN
    assert failed.operation_state is IntegrationOperationState.SUCCEEDED
    stored = _stored(store)
    assert stored.external_operation is not None
    assert stored.external_operation.status is OperationStatus.CONFIRMED
    assert stored.password_presentation is not None
    assert stored.password_presentation.voice.value == "PRESENTATION_FAILED_BEFORE_PLAYBACK"
    assert stored.password_presentation.email_delivery.value == "UNKNOWN"


async def test_reset_presentation_success_resolves_the_goal_and_listens() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store, action=Action.RESET_PASSWORD)
    service = _service(store)
    await service.handle_event(
        "conversation-1", _status(1, action="RESET_PASSWORD", status="SUCESSO")
    )
    presented = await service.handle_event("conversation-1", _presentation())
    assert presented.next_step is NextStep.LISTEN
    assert presented.operation_state is IntegrationOperationState.SUCCEEDED
    stored = _stored(store)
    assert stored.goal is None
    assert stored.external_operation is not None
    assert stored.external_operation.status is OperationStatus.CONFIRMED


async def test_incompatible_presentation_is_rejected() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store, action=Action.RESET_PASSWORD)
    service = _service(store)
    await service.handle_event(
        "conversation-1", _status(1, action="RESET_PASSWORD", status="SUCESSO")
    )
    await service.handle_event("conversation-1", _presentation())
    with pytest.raises(IntegrationEventRejected):
        await service.handle_event("conversation-1", _presentation(email_requested=0))


async def test_presentation_before_a_confirmed_reset_is_rejected() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store, action=Action.RESET_PASSWORD)
    with pytest.raises(IntegrationEventRejected):
        await _service(store).handle_event("conversation-1", _presentation())


async def test_presentation_never_applies_to_unlock() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    with pytest.raises(IntegrationEventRejected):
        await _service(store).handle_event("conversation-1", _presentation())


async def test_terminal_reset_is_not_re_presented_after_presentation() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store, action=Action.RESET_PASSWORD)
    service = _service(store)
    await service.handle_event(
        "conversation-1", _status(1, action="RESET_PASSWORD", status="SUCESSO")
    )
    await service.handle_event("conversation-1", _presentation())
    replay = await service.handle_event(
        "conversation-1", _status(2, action="RESET_PASSWORD", status="SUCESSO")
    )
    assert replay.next_step is NextStep.LISTEN
    assert replay.message is None


def test_presentation_email_requested_is_a_strict_zero_or_one() -> None:
    for invalid in (2, -1, "1", True):
        with pytest.raises(ValidationError):
            _presentation(email_requested=invalid)


# --- waiting feedback -------------------------------------------------------


async def test_first_observation_only_starts_the_cadence() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    composer = RecordingComposer()
    clock = FrozenClock()
    service = _service(store, clock=clock, composer=composer)
    outcome = await service.handle_event("conversation-1", _status(1))
    assert outcome.message is None
    assert composer.calls == []
    stored = _stored(store)
    assert stored.polling is not None
    assert stored.polling.last_feedback_attempt_at == NOW


async def test_feedback_is_composed_once_when_due() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    composer = RecordingComposer(message="Sigo con tu solicitud.")
    clock = FrozenClock()
    service = _service(store, clock=clock, composer=composer)
    await service.handle_event("conversation-1", _status(1))
    clock.now = NOW + POLLING_FEEDBACK_INTERVAL
    due = await service.handle_event("conversation-1", _status(2))
    assert due.next_step is NextStep.POLL_RD
    assert due.message == "Sigo con tu solicitud."
    assert len(composer.calls) == 1
    request = composer.calls[0]
    assert set(request.model_dump()) == {
        "action",
        "goal_revision",
        "confirmation_obtained",
        "operation_state",
        "observation_kind",
        "poll_sequence",
        "observations_used",
        "observation_limit",
        "previous_messages",
    }
    assert request.observation_kind.value == "PENDING"
    assert request.operation_state.value == "PENDING"
    assert request.observations_used == 2
    assert request.observation_limit == 9
    assert request.previous_messages == ()
    assert _stored(store).polling is not None
    assert _stored(store).polling.feedback_messages == ("Sigo con tu solicitud.",)  # type: ignore[union-attr]


async def test_feedback_is_not_composed_within_the_interval() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    composer = RecordingComposer()
    clock = FrozenClock()
    service = _service(store, clock=clock, composer=composer)
    await service.handle_event("conversation-1", _status(1))
    clock.now = NOW + timedelta(seconds=9)
    within = await service.handle_event("conversation-1", _status(2))
    assert within.message is None
    assert composer.calls == []


async def test_composer_failure_keeps_business_state_and_poll_metadata() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    composer = RecordingComposer(error=RuntimeError("synthetic composer outage"))
    clock = FrozenClock()
    service = _service(store, clock=clock, composer=composer)
    await service.handle_event("conversation-1", _status(1))
    clock.now = NOW + POLLING_FEEDBACK_INTERVAL
    outcome = await service.handle_event("conversation-1", _status(2))
    assert outcome.message is None
    assert outcome.operation_state is IntegrationOperationState.PENDING
    stored = _stored(store)
    assert stored.external_operation is not None
    assert stored.external_operation.status is OperationStatus.PENDING
    assert stored.polling is not None
    assert stored.polling.observations_used == 2
    assert stored.polling.last_feedback_attempt_at == clock.now
    assert stored.polling.feedback_messages == ()


async def test_inadmissible_composer_text_is_silent_and_not_persisted() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    composer = RecordingComposer(message="El desbloqueo fue confirmado.")
    clock = FrozenClock()
    service = _service(store, clock=clock, composer=composer)
    await service.handle_event("conversation-1", _status(1))
    clock.now = NOW + POLLING_FEEDBACK_INTERVAL
    outcome = await service.handle_event("conversation-1", _status(2))
    assert outcome.message is None
    stored = _stored(store)
    assert stored.polling is not None
    assert stored.polling.feedback_messages == ()


async def test_at_most_two_feedback_messages_are_persisted() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    composer = RecordingComposer(message="Sigo con tu solicitud.")
    clock = FrozenClock()
    service = _service(store, clock=clock, composer=composer)
    await service.handle_event("conversation-1", _status(1))
    for sequence in (2, 3, 4):
        clock.now = NOW + sequence * POLLING_FEEDBACK_INTERVAL
        await service.handle_event("conversation-1", _status(sequence))
    assert len(composer.calls) == 2
    stored = _stored(store)
    assert stored.polling is not None
    assert len(stored.polling.feedback_messages) == 2


async def test_composer_never_receives_transcript_identity_or_raw_status() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    composer = RecordingComposer()
    clock = FrozenClock()
    service = _service(store, clock=clock, composer=composer)
    await service.handle_event("conversation-1", _status(1, status="STATUS_NUEVO_RD"))
    clock.now = NOW + POLLING_FEEDBACK_INTERVAL
    await service.handle_event("conversation-1", _status(2, status="STATUS_NUEVO_RD"))
    assert len(composer.calls) == 1
    rendered = repr(composer.calls[0].model_dump())
    for canary in (
        "STATUS_NUEVO_RD",
        "SYNTHETIC-DOC-0000",
        "SYNTHETIC-PASSWORD-0000",
        "SYNTHETIC-TRANSCRIPT-0000",
        "operation-1",
    ):
        assert canary not in rendered


async def test_feedback_never_changes_the_next_step_or_authorization() -> None:
    store = InMemorySessionDocumentStore()
    _seed_dispatched(store)
    composer = RecordingComposer(message="Sigo con tu solicitud.")
    clock = FrozenClock()
    service = _service(store, clock=clock, composer=composer)
    await service.handle_event("conversation-1", _status(1))
    clock.now = NOW + POLLING_FEEDBACK_INTERVAL
    outcome = await service.handle_event("conversation-1", _status(2))
    assert outcome.next_step is NextStep.POLL_RD
    assert outcome.operation_state is IntegrationOperationState.PENDING
    stored = _stored(store)
    assert stored.dispatch is not None
    assert stored.confirmation is None


def test_poll_sequence_must_be_a_strict_positive_integer() -> None:
    for invalid in (0, -1, "1", 1.5, True):
        with pytest.raises(ValidationError):
            AccountActionStatusV1Event.model_validate(
                {
                    "event": "ACCOUNT_ACTION_STATUS",
                    "operation_id": "operation-1",
                    "action": "UNLOCK_ACCOUNT",
                    "goal_revision": 1,
                    "status": "NONE",
                    "poll_sequence": invalid,
                }
            )


def test_poll_error_requires_a_sequence_and_dispatch_error_forbids_one() -> None:
    base: dict[str, Any] = {
        "event": "ACCOUNT_ACTION_ERROR",
        "operation_id": "operation-1",
        "action": "UNLOCK_ACCOUNT",
        "goal_revision": 1,
        "error_kind": "TIMEOUT",
    }
    with pytest.raises(ValidationError):
        AccountActionErrorV1Event.model_validate({**base, "phase": "POLL"})
    with pytest.raises(ValidationError):
        AccountActionErrorV1Event.model_validate({**base, "phase": "DISPATCH", "poll_sequence": 1})
