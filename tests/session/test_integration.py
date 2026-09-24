"""Deterministic tests for the technical integration-event state machine.

No model, network, Firestore or credentials are involved: every event is
synthetic and PII-safe, and the durable record is a seeded in-memory
document. The tests pin correlation, duplicates, late results, the
anti-silence cadence and the rule that no event ever creates an operation,
re-dispatches one or calls the model.
"""

from datetime import timedelta

import pytest

from app.session.actions import Action
from app.session.integration import (
    ACTION_FAILURE_STATUSES,
    IDENTITY_TECHNICAL_FAILURE_MESSAGE,
    IDENTITY_VALID_MESSAGE,
    MAX_VOICE_CAPTURE_FAILURES,
    OPERATION_FAILED_MESSAGE,
    PROGRESS_FEEDBACK_INTERVAL,
    PROGRESS_MESSAGES,
    RESET_CONFIRMATION_MESSAGE,
    RESET_CONFIRMED_MESSAGE,
    UNLOCK_COMPLETED_MESSAGE,
    UNLOCK_CONFIRMATION_MESSAGE,
    VOICE_RETRY_MESSAGES,
    VOICE_TRANSFER_MESSAGE,
    AccountActionErrorEvent,
    AccountActionStatusEvent,
    IdentityValidationOutcome,
    IdentityValidationResultEvent,
    IntegrationDirective,
    IntegrationEventRejected,
    IntegrationEventService,
    IntegrationOperationState,
    RejectionReason,
    VoiceInputFailureEvent,
)
from app.session.metrics import RecordingTurnMetrics
from app.session.outcome import NextStep
from app.session.record import (
    MAX_CALLER_IDENTITY_FAILURES,
    OperationStatus,
    SessionRecord,
    session_record_from_document,
    session_record_to_document,
)
from app.session.repository import SessionRepository
from tests.session.doubles import (
    NOW,
    FrozenClock,
    InMemorySessionDocumentStore,
    make_challenge,
    make_dispatch,
    make_goal,
    make_identity,
    make_operation,
    make_record,
)

CALLER_FAILURE_STATUSES = tuple(sorted(status.value for status in ACTION_FAILURE_STATUSES))


def _service(
    store: InMemorySessionDocumentStore,
    clock: FrozenClock | None = None,
    metrics: RecordingTurnMetrics | None = None,
) -> IntegrationEventService:
    return IntegrationEventService(
        SessionRepository(store), clock=clock or FrozenClock(), metrics=metrics
    )


def _seed(store: InMemorySessionDocumentStore, record: SessionRecord) -> None:
    store.documents[record.conversation_id] = session_record_to_document(record)


def _stored(store: InMemorySessionDocumentStore) -> SessionRecord:
    return session_record_from_document(store.documents["conversation-1"])


def _dispatched_record(**overrides: object) -> SessionRecord:
    values: dict[str, object] = {
        "goal": make_goal(Action.UNLOCK_ACCOUNT, revision=1),
        "identity": make_identity(NOW),
        "confirmation": None,
        "dispatch": make_dispatch(Action.UNLOCK_ACCOUNT, revision=1, operation_id="operation-1"),
        "external_operation": make_operation(
            Action.UNLOCK_ACCOUNT,
            operation_id="operation-1",
            last_progress_feedback_at=NOW,
        ),
    }
    values.update(overrides)
    return make_record(**values)


def _identity_event(outcome: str) -> IdentityValidationResultEvent:
    return IdentityValidationResultEvent.model_validate(
        {"event": "IDENTITY_VALIDATION_RESULT", "outcome": outcome}
    )


def _voice_event(reason: str) -> VoiceInputFailureEvent:
    return VoiceInputFailureEvent.model_validate({"event": "VOICE_INPUT_FAILURE", "reason": reason})


def _status_event(**overrides: object) -> AccountActionStatusEvent:
    values: dict[str, object] = {
        "event": "ACCOUNT_ACTION_STATUS",
        "operation_id": "operation-1",
        "action": "UNLOCK_ACCOUNT",
        "goal_revision": 1,
        "status": "NONE",
    }
    values.update(overrides)
    return AccountActionStatusEvent.model_validate(values)


def _error_event(**overrides: object) -> AccountActionErrorEvent:
    values: dict[str, object] = {
        "event": "ACCOUNT_ACTION_ERROR",
        "operation_id": "operation-1",
        "action": "UNLOCK_ACCOUNT",
        "goal_revision": 1,
        "phase": "DISPATCH",
        "error_kind": "TIMEOUT",
        "http_status": None,
    }
    values.update(overrides)
    return AccountActionErrorEvent.model_validate(values)


async def test_unknown_conversation_is_rejected_without_writing() -> None:
    store = InMemorySessionDocumentStore()
    service = _service(store)
    with pytest.raises(IntegrationEventRejected):
        await service.handle_event("conversation-1", _identity_event("VALID"))
    assert store.writes == 0


async def test_identity_valid_keeps_the_goal_and_opens_the_confirmation() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        make_record(goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1), identity=make_identity()),
    )
    outcome = await _service(store).handle_event("conversation-1", _identity_event("VALID"))
    assert outcome.directive is IntegrationDirective.RESUME_CONVERSATION
    assert outcome.next_step is NextStep.LISTEN
    assert outcome.message == UNLOCK_CONFIRMATION_MESSAGE
    assert outcome.operation_state is None
    stored = _stored(store)
    assert stored.identity.validated_at == NOW
    assert stored.identity.caller_failures == 0
    assert stored.turn_count == 2
    assert stored.revision == 2
    assert stored.goal is not None and stored.goal.revision == 1
    assert stored.confirmation is not None
    assert stored.confirmation.action is Action.UNLOCK_ACCOUNT
    assert stored.confirmation.goal_revision == 1
    assert stored.confirmation.identity_validated_at == NOW


async def test_identity_valid_confirms_the_reset_action_specifically() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        make_record(goal=make_goal(Action.RESET_PASSWORD, revision=1), identity=make_identity()),
    )
    outcome = await _service(store).handle_event("conversation-1", _identity_event("VALID"))
    assert outcome.message == RESET_CONFIRMATION_MESSAGE
    assert outcome.next_step is NextStep.LISTEN
    stored = _stored(store)
    assert stored.confirmation is not None
    assert stored.confirmation.action is Action.RESET_PASSWORD
    assert stored.confirmation.goal_revision == 1


async def test_identity_valid_replaces_a_previous_challenge_with_a_fresh_one() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        make_record(
            goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1),
            identity=make_identity(),
            confirmation=make_challenge(
                Action.UNLOCK_ACCOUNT, revision=1, challenge_id="challenge-old"
            ),
        ),
    )
    await _service(store).handle_event("conversation-1", _identity_event("VALID"))
    confirmation = _stored(store).confirmation
    assert confirmation is not None
    assert confirmation.challenge_id != "challenge-old"


async def test_identity_valid_without_a_goal_invents_none() -> None:
    store = InMemorySessionDocumentStore()
    _seed(store, make_record(goal=None, identity=make_identity()))
    outcome = await _service(store).handle_event("conversation-1", _identity_event("VALID"))
    assert outcome.message == IDENTITY_VALID_MESSAGE
    assert outcome.next_step is NextStep.LISTEN
    stored = _stored(store)
    assert stored.goal is None
    assert stored.confirmation is None
    assert stored.identity.validated_at == NOW


async def test_identity_invalid_counts_caller_failures_until_handoff() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        make_record(goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1), identity=make_identity()),
    )
    service = _service(store)

    first = await service.handle_event("conversation-1", _identity_event("INVALID"))
    assert first.directive is IntegrationDirective.COLLECT_IDENTITY
    assert _stored(store).identity.caller_failures == 1

    second = await service.handle_event("conversation-1", _identity_event("INVALID"))
    assert second.directive is IntegrationDirective.COLLECT_IDENTITY
    assert _stored(store).identity.caller_failures == 2

    third = await service.handle_event("conversation-1", _identity_event("INVALID"))
    assert third.directive is IntegrationDirective.ESCALATE
    assert _stored(store).identity.caller_failures == MAX_CALLER_IDENTITY_FAILURES
    assert _stored(store).identity.validated_at is None


async def test_identity_technical_failure_consumes_nothing_and_writes_nothing() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        make_record(
            goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1),
            identity=make_identity(failures=1),
        ),
    )
    writes_before = store.writes
    outcome = await _service(store).handle_event(
        "conversation-1", _identity_event("TECHNICAL_FAILURE")
    )
    assert outcome.directive is IntegrationDirective.COLLECT_IDENTITY
    assert outcome.message == IDENTITY_TECHNICAL_FAILURE_MESSAGE
    stored = _stored(store)
    assert stored.identity.caller_failures == 1
    assert stored.identity.validated_at is None
    assert store.writes == writes_before


async def test_voice_failure_invalidates_the_challenge_and_keeps_identity() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        make_record(
            goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT, revision=1),
        ),
    )
    outcome = await _service(store).handle_event("conversation-1", _voice_event("LOW_CONFIDENCE"))
    assert outcome.directive is IntegrationDirective.RETRY_SPEECH
    assert outcome.message == VOICE_RETRY_MESSAGES["LOW_CONFIDENCE"]
    stored = _stored(store)
    assert stored.confirmation is None
    assert stored.identity.validated_at == NOW
    assert stored.identity.caller_failures == 0
    assert stored.dispatch is None


async def test_voice_failure_without_a_challenge_retries_and_counts() -> None:
    store = InMemorySessionDocumentStore()
    _seed(store, make_record(goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1)))
    writes_before = store.writes
    outcome = await _service(store).handle_event("conversation-1", _voice_event("NO_SPEECH"))
    assert outcome.directive is IntegrationDirective.RETRY_SPEECH
    assert outcome.message == VOICE_RETRY_MESSAGES["NO_SPEECH"]
    assert store.writes == writes_before + 1
    assert _stored(store).voice_retry_count == 1


@pytest.mark.parametrize("reason", ["NO_SPEECH", "LOW_CONFIDENCE", "TIMEOUT"])
async def test_every_voice_failure_reason_retries_with_a_safe_phrase(reason: str) -> None:
    store = InMemorySessionDocumentStore()
    _seed(store, _dispatched_record())
    outcome = await _service(store).handle_event("conversation-1", _voice_event(reason))
    assert outcome.directive is IntegrationDirective.RETRY_SPEECH
    assert outcome.message == VOICE_RETRY_MESSAGES[reason]
    assert _stored(store).dispatch is not None
    assert _stored(store).external_operation is not None
    assert _stored(store).external_operation.status is OperationStatus.PENDING


async def test_none_none_success_keeps_pending_until_the_terminal() -> None:
    store = InMemorySessionDocumentStore()
    clock = FrozenClock()
    _seed(store, _dispatched_record())
    service = _service(store, clock)

    first = await service.handle_event("conversation-1", _status_event(status="NONE"))
    second = await service.handle_event("conversation-1", _status_event(status="NONE"))
    assert first.operation_state is IntegrationOperationState.PENDING
    assert second.operation_state is IntegrationOperationState.PENDING

    terminal = await service.handle_event("conversation-1", _status_event(status="SUCESSO"))
    assert terminal.directive is IntegrationDirective.COMPLETE
    assert terminal.operation_state is IntegrationOperationState.SUCCEEDED
    assert _stored(store).external_operation is not None
    assert _stored(store).external_operation.status is OperationStatus.CONFIRMED


@pytest.mark.parametrize("error_kind", ["TIMEOUT", "HTTP_ERROR", "INVALID_BODY", "UNAVAILABLE"])
async def test_every_dispatch_error_kind_moves_to_unknown(error_kind: str) -> None:
    store = InMemorySessionDocumentStore()
    _seed(store, _dispatched_record())
    outcome = await _service(store).handle_event(
        "conversation-1", _error_event(phase="DISPATCH", error_kind=error_kind)
    )
    assert outcome.directive is IntegrationDirective.POLL_RD
    assert outcome.operation_state is IntegrationOperationState.UNKNOWN


@pytest.mark.parametrize("error_kind", ["TIMEOUT", "HTTP_ERROR", "INVALID_BODY", "UNAVAILABLE"])
async def test_every_poll_error_kind_keeps_the_result_unconfirmed(error_kind: str) -> None:
    store = InMemorySessionDocumentStore()
    _seed(store, _dispatched_record())
    outcome = await _service(store).handle_event(
        "conversation-1", _error_event(phase="POLL", error_kind=error_kind)
    )
    assert outcome.directive is IntegrationDirective.POLL_RD
    assert outcome.operation_state is IntegrationOperationState.PENDING


async def test_none_keeps_pending_and_speaks_only_after_the_interval() -> None:
    store = InMemorySessionDocumentStore()
    clock = FrozenClock()
    _seed(store, _dispatched_record())
    service = _service(store, clock)

    immediate = await service.handle_event("conversation-1", _status_event(status="NONE"))
    assert immediate.directive is IntegrationDirective.POLL_RD
    assert immediate.operation_state is IntegrationOperationState.PENDING
    assert immediate.message is None
    assert store.writes == 0

    clock.now = NOW + PROGRESS_FEEDBACK_INTERVAL
    first = await service.handle_event("conversation-1", _status_event(status="NONE"))
    assert first.message == PROGRESS_MESSAGES[0]
    assert _stored(store).external_operation is not None
    assert _stored(store).external_operation.progress_feedback_index == 1

    clock.now = NOW + 2 * PROGRESS_FEEDBACK_INTERVAL
    second = await service.handle_event("conversation-1", _status_event(status="NONE"))
    assert second.message == PROGRESS_MESSAGES[1]

    clock.now = NOW + 3 * PROGRESS_FEEDBACK_INTERVAL
    third = await service.handle_event("conversation-1", _status_event(status="NONE"))
    assert third.message == PROGRESS_MESSAGES[2]

    clock.now = NOW + 4 * PROGRESS_FEEDBACK_INTERVAL
    wrapped = await service.handle_event("conversation-1", _status_event(status="NONE"))
    assert wrapped.message == PROGRESS_MESSAGES[0]
    assert _stored(store).external_operation.progress_feedback_index == 4


async def test_duplicate_none_within_the_interval_is_idempotent() -> None:
    store = InMemorySessionDocumentStore()
    _seed(store, _dispatched_record())
    service = _service(store)
    first = await service.handle_event("conversation-1", _status_event(status="NONE"))
    second = await service.handle_event("conversation-1", _status_event(status="NONE"))
    assert first.message is None and second.message is None
    assert store.writes == 0
    assert _stored(store).external_operation is not None
    assert _stored(store).external_operation.status is OperationStatus.PENDING


async def test_unlock_success_confirms_and_completes() -> None:
    store = InMemorySessionDocumentStore()
    _seed(store, _dispatched_record())
    outcome = await _service(store).handle_event("conversation-1", _status_event(status="SUCESSO"))
    assert outcome.directive is IntegrationDirective.COMPLETE
    assert outcome.message == UNLOCK_COMPLETED_MESSAGE
    assert outcome.operation_state is IntegrationOperationState.SUCCEEDED
    assert _stored(store).external_operation is not None
    assert _stored(store).external_operation.status is OperationStatus.CONFIRMED


async def test_reset_success_confirms_reset_but_not_delivery() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        _dispatched_record(
            goal=make_goal(Action.RESET_PASSWORD, revision=1),
            dispatch=make_dispatch(Action.RESET_PASSWORD, revision=1, operation_id="operation-1"),
            external_operation=make_operation(
                Action.RESET_PASSWORD,
                operation_id="operation-1",
                last_progress_feedback_at=NOW,
            ),
        ),
    )
    outcome = await _service(store).handle_event(
        "conversation-1",
        _status_event(action="RESET_PASSWORD", status="SUCESSO"),
    )
    assert outcome.directive is IntegrationDirective.RESUME_CONVERSATION
    assert outcome.message == RESET_CONFIRMED_MESSAGE
    assert outcome.operation_state is IntegrationOperationState.SUCCEEDED
    operation = _stored(store).external_operation
    assert operation is not None
    assert operation.status is OperationStatus.CONFIRMED
    assert operation.delivery is None


@pytest.mark.parametrize("status", CALLER_FAILURE_STATUSES)
async def test_known_failure_status_persists_failure(status: str) -> None:
    store = InMemorySessionDocumentStore()
    _seed(store, _dispatched_record())
    outcome = await _service(store).handle_event("conversation-1", _status_event(status=status))
    assert outcome.directive is IntegrationDirective.RESUME_CONVERSATION
    assert outcome.message == OPERATION_FAILED_MESSAGE
    assert outcome.operation_state is IntegrationOperationState.FAILED
    operation = _stored(store).external_operation
    assert operation is not None
    assert operation.status is OperationStatus.FAILED


async def test_unknown_status_changes_nothing_and_keeps_polling() -> None:
    store = InMemorySessionDocumentStore()
    metrics = RecordingTurnMetrics()
    _seed(store, _dispatched_record())
    writes_before = store.writes
    outcome = await _service(store, metrics=metrics).handle_event(
        "conversation-1", _status_event(status="STATUS_NUEVO_RD")
    )
    assert outcome.directive is IntegrationDirective.POLL_RD
    assert outcome.operation_state is IntegrationOperationState.PENDING
    assert outcome.message is None
    assert store.writes == writes_before
    operation = _stored(store).external_operation
    assert operation is not None and operation.status is OperationStatus.PENDING
    assert ("unrecognized_action_status", 1) in metrics.counters


async def test_dispatch_error_moves_pending_to_unknown_without_redispatch() -> None:
    store = InMemorySessionDocumentStore()
    _seed(store, _dispatched_record())
    outcome = await _service(store).handle_event(
        "conversation-1", _error_event(phase="DISPATCH", error_kind="TIMEOUT")
    )
    assert outcome.directive is IntegrationDirective.POLL_RD
    assert outcome.operation_state is IntegrationOperationState.UNKNOWN
    stored = _stored(store)
    assert stored.external_operation is not None
    assert stored.external_operation.status is OperationStatus.UNKNOWN
    assert stored.external_operation.operation_id == "operation-1"
    assert stored.dispatch is not None


async def test_duplicate_dispatch_error_is_idempotent() -> None:
    store = InMemorySessionDocumentStore()
    _seed(store, _dispatched_record())
    service = _service(store)
    await service.handle_event(
        "conversation-1", _error_event(phase="DISPATCH", error_kind="TIMEOUT")
    )
    writes_before = store.writes
    outcome = await service.handle_event(
        "conversation-1", _error_event(phase="DISPATCH", error_kind="UNAVAILABLE")
    )
    assert outcome.directive is IntegrationDirective.POLL_RD
    assert outcome.operation_state is IntegrationOperationState.UNKNOWN
    assert store.writes == writes_before


async def test_poll_error_keeps_the_result_unconfirmed() -> None:
    store = InMemorySessionDocumentStore()
    _seed(store, _dispatched_record())
    writes_before = store.writes
    outcome = await _service(store).handle_event(
        "conversation-1", _error_event(phase="POLL", error_kind="HTTP_ERROR", http_status=500)
    )
    assert outcome.directive is IntegrationDirective.POLL_RD
    assert outcome.operation_state is IntegrationOperationState.PENDING
    assert outcome.message is None
    assert store.writes == writes_before


async def test_unknown_plus_late_success_reconciles() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        _dispatched_record(
            external_operation=make_operation(
                Action.UNLOCK_ACCOUNT,
                OperationStatus.UNKNOWN,
                operation_id="operation-1",
                last_progress_feedback_at=NOW,
            )
        ),
    )
    outcome = await _service(store).handle_event("conversation-1", _status_event(status="SUCESSO"))
    assert outcome.directive is IntegrationDirective.COMPLETE
    assert outcome.operation_state is IntegrationOperationState.SUCCEEDED


async def test_duplicate_terminal_is_idempotent() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        _dispatched_record(
            external_operation=make_operation(
                Action.UNLOCK_ACCOUNT,
                OperationStatus.CONFIRMED,
                operation_id="operation-1",
            )
        ),
    )
    writes_before = store.writes
    outcome = await _service(store).handle_event("conversation-1", _status_event(status="SUCESSO"))
    assert outcome.directive is IntegrationDirective.COMPLETE
    assert outcome.operation_state is IntegrationOperationState.SUCCEEDED
    assert store.writes == writes_before


async def test_contradictory_terminal_never_overwrites() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        _dispatched_record(
            external_operation=make_operation(
                Action.UNLOCK_ACCOUNT,
                OperationStatus.CONFIRMED,
                operation_id="operation-1",
            )
        ),
    )
    writes_before = store.writes
    with pytest.raises(IntegrationEventRejected):
        await _service(store).handle_event("conversation-1", _status_event(status="FALHA_AD"))
    assert store.writes == writes_before
    stored = _stored(store)
    assert stored.external_operation is not None
    assert stored.external_operation.status is OperationStatus.CONFIRMED


async def test_late_none_after_terminal_does_not_reopen() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        _dispatched_record(
            external_operation=make_operation(
                Action.UNLOCK_ACCOUNT,
                OperationStatus.CONFIRMED,
                operation_id="operation-1",
            )
        ),
    )
    writes_before = store.writes
    outcome = await _service(store).handle_event("conversation-1", _status_event(status="NONE"))
    assert outcome.directive is IntegrationDirective.COMPLETE
    assert outcome.message is None
    assert outcome.operation_state is IntegrationOperationState.SUCCEEDED
    assert store.writes == writes_before


async def test_terminal_dispatch_error_is_rejected() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        _dispatched_record(
            external_operation=make_operation(
                Action.UNLOCK_ACCOUNT,
                OperationStatus.CONFIRMED,
                operation_id="operation-1",
            )
        ),
    )
    with pytest.raises(IntegrationEventRejected):
        await _service(store).handle_event("conversation-1", _error_event(phase="DISPATCH"))


async def test_poll_error_after_terminal_returns_the_terminal_directive() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        _dispatched_record(
            external_operation=make_operation(
                Action.UNLOCK_ACCOUNT,
                OperationStatus.FAILED,
                operation_id="operation-1",
            )
        ),
    )
    outcome = await _service(store).handle_event(
        "conversation-1", _error_event(phase="POLL", error_kind="TIMEOUT")
    )
    assert outcome.directive is IntegrationDirective.RESUME_CONVERSATION
    assert outcome.operation_state is IntegrationOperationState.FAILED
    assert outcome.message is None


async def test_missing_operation_is_rejected() -> None:
    store = InMemorySessionDocumentStore()
    _seed(store, make_record(goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1)))
    with pytest.raises(IntegrationEventRejected):
        await _service(store).handle_event("conversation-1", _status_event())


@pytest.mark.parametrize(
    "event",
    [
        _status_event(operation_id="operation-other"),
        _status_event(action="RESET_PASSWORD"),
        _status_event(goal_revision=2),
    ],
)
async def test_correlation_mismatch_is_rejected(event: AccountActionStatusEvent) -> None:
    store = InMemorySessionDocumentStore()
    _seed(store, _dispatched_record())
    writes_before = store.writes
    with pytest.raises(IntegrationEventRejected):
        await _service(store).handle_event("conversation-1", event)
    assert store.writes == writes_before


async def test_action_event_without_dispatch_guard_is_rejected() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        make_record(
            goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1),
            external_operation=make_operation(Action.UNLOCK_ACCOUNT, operation_id="operation-1"),
        ),
    )
    with pytest.raises(IntegrationEventRejected):
        await _service(store).handle_event("conversation-1", _status_event())


async def test_the_integration_service_never_calls_a_model_store_only() -> None:
    """The service performs one load and at most one save; nothing else."""
    store = InMemorySessionDocumentStore()
    _seed(store, _dispatched_record())
    await _service(store).handle_event("conversation-1", _status_event(status="NONE"))
    assert (store.reads, store.writes) == (1, 0)


def test_progress_interval_is_the_experimental_default() -> None:
    assert PROGRESS_FEEDBACK_INTERVAL == timedelta(seconds=10)
    assert len(PROGRESS_MESSAGES) == 3


def test_wire_preserves_only_the_observed_action_status_literals() -> None:
    from app.session.integration import AccountActionStatus, resolve_action_status

    assert {status.value for status in AccountActionStatus} == {
        "NONE",
        "SUCESSO",
        "CPF_NAO_ENCONTRADO",
        "ERRO_NA_VALIDACAO",
        "FALHA_AD",
        "USUARIO_DESABILITADO",
        "USUARIO_EXPIRADO",
    }
    assert resolve_action_status("SUCESSO") is AccountActionStatus.SUCESSO
    assert resolve_action_status("NOVO_STATUS") is None


def test_identity_outcome_domain_is_local_only() -> None:
    """Only the local outcome travels; external lookup states never do.

    XCALLY turns NOT_FOUND, a date mismatch and technical lookup errors into
    these three local outcomes before calling CU013.
    """
    assert {outcome.value for outcome in IdentityValidationOutcome} == {
        "VALID",
        "INVALID",
        "TECHNICAL_FAILURE",
    }


def test_record_status_enum_is_reused_not_duplicated() -> None:
    assert Action.UNLOCK_ACCOUNT.value == "UNLOCK_ACCOUNT"
    assert {status.value for status in OperationStatus} == {
        "pending",
        "unknown",
        "confirmed",
        "failed",
    }


# --- pre-turn bootstrap (next-step-v1) --------------------------------------


async def test_v1_voice_failure_bootstraps_a_minimal_pre_turn_record() -> None:
    store = InMemorySessionDocumentStore()
    outcome = await _service(store).handle_event(
        "conversation-1", _voice_event("NO_SPEECH"), bootstrap=True
    )
    assert outcome.directive is IntegrationDirective.RETRY_SPEECH
    assert outcome.next_step is NextStep.LISTEN
    assert outcome.message == VOICE_RETRY_MESSAGES["NO_SPEECH"]
    assert outcome.operation_state is None
    assert store.writes == 1
    stored = _stored(store)
    assert stored.schema_version == 4
    assert stored.turn_count == 0
    assert stored.goal is None
    assert stored.identity.validated_at is None
    assert stored.confirmation is None
    assert stored.dispatch is None
    assert stored.external_operation is None
    assert stored.polling is None
    assert stored.voice_retry_count == 1


async def test_legacy_voice_failure_never_bootstraps() -> None:
    store = InMemorySessionDocumentStore()
    with pytest.raises(IntegrationEventRejected) as excinfo:
        await _service(store).handle_event("conversation-1", _voice_event("NO_SPEECH"))
    assert excinfo.value.reason is RejectionReason.UNKNOWN_SESSION
    assert store.writes == 0
    assert store.documents == {}


async def test_pre_turn_record_increments_the_counter_on_v1_voice_failure() -> None:
    store = InMemorySessionDocumentStore()
    service = _service(store)
    await service.handle_event("conversation-1", _voice_event("NO_SPEECH"), bootstrap=True)
    await service.handle_event("conversation-1", _voice_event("TIMEOUT"), bootstrap=True)
    stored = _stored(store)
    assert stored.turn_count == 0
    assert stored.voice_retry_count == 2
    assert stored.goal is None
    assert stored.dispatch is None


@pytest.mark.parametrize("reason", ["NO_SPEECH", "LOW_CONFIDENCE", "TIMEOUT"])
async def test_every_v1_voice_failure_reason_bootstraps_safely(reason: str) -> None:
    store = InMemorySessionDocumentStore()
    outcome = await _service(store).handle_event(
        "conversation-1", _voice_event(reason), bootstrap=True
    )
    assert outcome.message == VOICE_RETRY_MESSAGES[reason]
    assert outcome.next_step is NextStep.LISTEN


async def test_pre_turn_record_rejects_identity_and_action_events() -> None:
    store = InMemorySessionDocumentStore()
    service = _service(store)
    await service.handle_event("conversation-1", _voice_event("NO_SPEECH"), bootstrap=True)
    writes_before = store.writes
    for event in (_identity_event("VALID"), _status_event()):
        with pytest.raises(IntegrationEventRejected) as excinfo:
            await service.handle_event("conversation-1", event, bootstrap=True)
        assert excinfo.value.reason is RejectionReason.PRE_TURN_EVENT_NOT_ALLOWED
    assert store.writes == writes_before


async def test_other_first_events_never_create_a_document() -> None:
    store = InMemorySessionDocumentStore()
    service = _service(store)
    for event in (
        _identity_event("VALID"),
        _identity_event("INVALID"),
        _identity_event("TECHNICAL_FAILURE"),
        _status_event(),
        _error_event(),
    ):
        with pytest.raises(IntegrationEventRejected):
            await service.handle_event("conversation-1", event, bootstrap=True)
    with pytest.raises(IntegrationEventRejected):
        await service.handle_event("conversation-1", _voice_event("NO_SPEECH"))
    assert store.writes == 0
    assert store.documents == {}


class _RacingStore(InMemorySessionDocumentStore):
    """Reads as absent once while a concurrent writer already stored a record."""

    def __init__(self, concurrent: SessionRecord) -> None:
        super().__init__()
        self.documents[concurrent.conversation_id] = session_record_to_document(concurrent)
        self._first_read = True

    async def read(self, conversation_id: str):  # type: ignore[no-untyped-def]
        if self._first_read:
            self._first_read = False
            return None
        return await super().read(conversation_id)


async def test_bootstrap_never_overwrites_a_concurrent_record() -> None:
    concurrent = make_record(goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1))
    store = _RacingStore(concurrent)
    outcome = await _service(store).handle_event(
        "conversation-1", _voice_event("LOW_CONFIDENCE"), bootstrap=True
    )
    assert outcome.next_step is NextStep.LISTEN
    stored = _stored(store)
    assert stored.turn_count == concurrent.turn_count
    assert stored.goal == concurrent.goal
    assert stored.voice_retry_count == 1


async def test_voice_failure_policy_transfers_after_four_consecutive_failures() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        make_record(goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1), identity=make_identity()),
    )
    service = _service(store)
    for expected_count in (1, 2, 3):
        outcome = await service.handle_event(
            "conversation-1", _voice_event("NO_SPEECH"), bootstrap=True
        )
        assert outcome.next_step is NextStep.LISTEN
        assert outcome.directive is IntegrationDirective.RETRY_SPEECH
        assert _stored(store).voice_retry_count == expected_count
    fourth = await service.handle_event("conversation-1", _voice_event("NO_SPEECH"), bootstrap=True)
    assert fourth.next_step is NextStep.TRANSFER
    assert fourth.directive is IntegrationDirective.ESCALATE
    assert fourth.message == VOICE_TRANSFER_MESSAGE
    assert _stored(store).voice_retry_count == MAX_VOICE_CAPTURE_FAILURES
    # Further failures keep the exhausted state bounded; no HTTP retry exists.
    fifth = await service.handle_event("conversation-1", _voice_event("TIMEOUT"), bootstrap=True)
    assert fifth.next_step is NextStep.TRANSFER
    assert _stored(store).voice_retry_count == MAX_VOICE_CAPTURE_FAILURES


@pytest.mark.parametrize("reason", ["NO_SPEECH", "LOW_CONFIDENCE", "TIMEOUT"])
async def test_every_voice_failure_reason_transfers_on_the_fourth(reason: str) -> None:
    store = InMemorySessionDocumentStore()
    service = _service(store)
    for _ in range(3):
        outcome = await service.handle_event("conversation-1", _voice_event(reason), bootstrap=True)
        assert outcome.next_step is NextStep.LISTEN
        assert outcome.message == VOICE_RETRY_MESSAGES[reason]
    fourth = await service.handle_event("conversation-1", _voice_event(reason), bootstrap=True)
    assert fourth.next_step is NextStep.TRANSFER
    stored = _stored(store)
    assert stored.voice_retry_count == MAX_VOICE_CAPTURE_FAILURES
    assert stored.turn_count == 0


async def test_voice_policy_never_touches_goal_identity_or_operation() -> None:
    store = InMemorySessionDocumentStore()
    _seed(
        store,
        make_record(
            goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1),
            identity=make_identity(NOW, failures=1),
        ),
    )
    service = _service(store)
    for _ in range(MAX_VOICE_CAPTURE_FAILURES):
        await service.handle_event("conversation-1", _voice_event("LOW_CONFIDENCE"), bootstrap=True)
    stored = _stored(store)
    assert stored.identity.validated_at == NOW
    assert stored.identity.caller_failures == 1
    assert stored.goal is not None and stored.goal.revision == 1
    assert stored.confirmation is None
    assert stored.dispatch is None
    assert stored.external_operation is None
    assert stored.turn_count == 2
    assert stored.revision == 2


async def test_rejection_reasons_are_a_closed_vocabulary() -> None:
    assert {reason.value for reason in RejectionReason} == {
        "unknown_session",
        "pre_turn_event_not_allowed",
        "operation_missing",
        "operation_mismatch",
        "action_mismatch",
        "dispatch_mismatch",
        "revision_mismatch",
        "illegal_transition",
        "poll_sequence_conflict",
        "password_presentation_conflict",
    }
