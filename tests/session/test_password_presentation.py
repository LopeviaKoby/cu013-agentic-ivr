"""Deterministic tests for the ephemeral voice password-presentation slice.

The synthetic secret must never leave the current request: these tests prove
the per-request path, the presentation lifecycle, the no-redispatch rule and
the privacy canaries with no model, network, Firestore or credentials.
"""

import logging

from pydantic import SecretStr

from app.session.actions import Action
from app.session.memory import RECENT_CONVERSATION_MEMORY, ExperimentalMemoryConfig
from app.session.outcome import NextStep
from app.session.record import (
    OperationStatus,
    PasswordPresentation,
    PlaybackVoice,
    session_record_from_document,
    session_record_to_document,
)
from app.session.repository import SessionRepository
from app.session.service import TurnService
from app.session.turns import (
    PRESENTATION_FINISHED_MESSAGE,
    PRESENTATION_WAITING_MESSAGE,
    Route,
    TurnInput,
    build_turn_graph,
)
from tests.session.doubles import (
    NOW,
    FakeTurnModel,
    FrozenClock,
    InMemorySessionDocumentStore,
    make_decision,
    make_dispatch,
    make_identity,
    make_operation,
    make_record,
)

SECRET = "A1b!z9-Qx"


def _presentation(**overrides: object) -> PasswordPresentation:
    values: dict[str, object] = {
        "operation_id": "operation-1",
        "action": Action.RESET_PASSWORD,
        "goal_revision": 1,
        "voice": PlaybackVoice.PLAYBACK_RETURNED,
        "presented_at": NOW,
    }
    values.update(overrides)
    return PasswordPresentation.model_validate(values)


def _seed(
    store: InMemorySessionDocumentStore,
    *,
    presentation: PasswordPresentation | None = None,
    with_operation: bool = True,
) -> None:
    if with_operation:
        record = make_record(
            goal=None,
            identity=make_identity(NOW),
            dispatch=make_dispatch(Action.RESET_PASSWORD, revision=1, operation_id="operation-1"),
            external_operation=make_operation(
                Action.RESET_PASSWORD, OperationStatus.CONFIRMED, operation_id="operation-1"
            ),
            password_presentation=presentation,
        )
    else:
        record = make_record(
            goal=None,
            identity=make_identity(NOW),
            dispatch=None,
            external_operation=None,
            password_presentation=presentation,
        )
    store.documents["conversation-1"] = session_record_to_document(record)


def _service(store: InMemorySessionDocumentStore, model: FakeTurnModel) -> TurnService:
    return TurnService(
        SessionRepository(store),
        build_turn_graph(model=model),
        clock=FrozenClock(),
    )


async def test_first_vocalization_uses_the_ephemeral_secret_without_persisting_it() -> None:
    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    _seed(store)
    model.decision = make_decision(
        route=Route.CONTINUE, message="Toma nota. Tu contraseña es A uno, be, signo."
    )
    result = await _service(store, model).handle_turn(
        "conversation-1", TurnInput(temporary_password=SecretStr(SECRET))
    )
    assert result.outcome is not None
    assert result.outcome.next_step is NextStep.DELIVER_PASSWORD
    assert model.calls[0]["delivery_secret"] == SECRET
    # The first vocalization never creates a presentation fact and the secret
    # never reaches the durable document.
    assert result.record.password_presentation is None
    assert SECRET not in repr(store.documents["conversation-1"])
    assert SECRET not in repr(result.record.model_dump())


async def test_repeat_turn_keeps_presentation_active_and_speaks_again() -> None:
    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    _seed(store, presentation=_presentation())
    model.decision = make_decision(route=Route.CONTINUE, message="Repito: A uno, be, signo.")
    result = await _service(store, model).handle_turn(
        "conversation-1",
        TurnInput(transcript="repítela completa", temporary_password=SecretStr(SECRET)),
    )
    assert result.outcome is not None
    assert result.outcome.next_step is NextStep.DELIVER_PASSWORD
    assert model.calls[0]["delivery_secret"] == SECRET
    assert result.record.password_presentation is not None
    assert result.record.password_presentation.caller_finished is False
    assert SECRET not in repr(store.documents["conversation-1"])


async def test_caller_finished_persists_only_the_boolean_and_listens() -> None:
    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    _seed(store, presentation=_presentation())
    model.decision = make_decision(
        route=Route.CONTINUE,
        message="Perfecto.",
        password_presentation_finished=True,
    )
    result = await _service(store, model).handle_turn(
        "conversation-1",
        TurnInput(transcript="ya está, la anoté", temporary_password=SecretStr(SECRET)),
    )
    assert result.outcome is not None
    assert result.outcome.next_step is NextStep.LISTEN
    assert result.outcome.message == PRESENTATION_FINISHED_MESSAGE
    assert result.record.password_presentation is not None
    assert result.record.password_presentation.caller_finished is True
    document = store.documents["conversation-1"]
    assert document["password_presentation"]["caller_finished"] is True  # type: ignore[index]
    assert SECRET not in repr(document)
    assert SECRET not in result.outcome.message


async def test_finished_presentation_no_longer_receives_the_secret() -> None:
    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    _seed(store, presentation=_presentation(caller_finished=True))
    model.decision = make_decision(route=Route.CONTINUE, message="Con gusto.")
    result = await _service(store, model).handle_turn(
        "conversation-1",
        TurnInput(transcript="gracias, eso era todo", temporary_password=SecretStr(SECRET)),
    )
    assert result.outcome is not None
    assert result.outcome.next_step is NextStep.LISTEN
    assert model.calls[0]["delivery_secret"] is None


async def test_password_absent_during_active_presentation_does_not_invent() -> None:
    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    _seed(store, presentation=_presentation())
    model.decision = make_decision(route=Route.CONTINUE, message="Repito lo que tengo.")
    result = await _service(store, model).handle_turn(
        "conversation-1", TurnInput(transcript="¿me la repites?")
    )
    assert result.outcome is not None
    assert result.outcome.next_step is NextStep.LISTEN
    assert result.outcome.message == PRESENTATION_WAITING_MESSAGE
    assert model.calls[0]["delivery_secret"] is None
    assert result.record.password_presentation is not None
    assert result.record.password_presentation.caller_finished is False


async def test_password_outside_presentation_is_ignored() -> None:
    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    _seed(store, with_operation=False)
    model.decision = make_decision(route=Route.CONTINUE, message="Claro.")
    result = await _service(store, model).handle_turn(
        "conversation-1",
        TurnInput(transcript="hola", temporary_password=SecretStr(SECRET)),
    )
    assert result.outcome is not None
    assert result.outcome.next_step is NextStep.LISTEN
    assert model.calls[0]["delivery_secret"] is None
    assert SECRET not in repr(store.documents["conversation-1"])


async def test_presentation_never_registers_a_new_goal_or_redispatches() -> None:
    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    _seed(store, presentation=_presentation())
    model.decision = make_decision(
        route=Route.CONTINUE,
        message="Te la repito.",
        goal={"intent": "REQUEST", "action": "RESET_PASSWORD"},
        confirmation_request=True,
    )
    result = await _service(store, model).handle_turn(
        "conversation-1",
        TurnInput(transcript="repítela otra vez", temporary_password=SecretStr(SECRET)),
    )
    assert result.outcome is not None
    assert result.outcome.next_step is NextStep.DELIVER_PASSWORD
    assert result.record.goal is None
    assert result.record.confirmation is None
    assert result.record.dispatch is not None
    assert result.record.dispatch.operation_id == "operation-1"
    assert result.record.external_operation is not None
    assert result.record.external_operation.operation_id == "operation-1"
    assert result.record.external_operation.status is OperationStatus.CONFIRMED


async def test_presentation_turns_are_excluded_from_recent_memory() -> None:
    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    _seed(store, presentation=_presentation())
    model.decision = make_decision(route=Route.CONTINUE, message="Repito: A uno.")
    config = ExperimentalMemoryConfig(variant=RECENT_CONVERSATION_MEMORY, window_n=3)
    result = await _service(store, model).handle_turn(
        "conversation-1",
        TurnInput(transcript="repítela", temporary_password=SecretStr(SECRET)),
        experimental=config,
    )
    assert model.calls[0]["memory_context"] is None
    assert result.record.experimental_window == ()
    assert SECRET not in repr(result.record.model_dump())


async def test_the_secret_never_reaches_logs(caplog) -> None:  # type: ignore[no-untyped-def]
    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    _seed(store, presentation=_presentation())
    model.decision = make_decision(route=Route.CONTINUE, message="Repito: A uno.")
    with caplog.at_level(logging.INFO):
        await _service(store, model).handle_turn(
            "conversation-1",
            TurnInput(transcript="repítela", temporary_password=SecretStr(SECRET)),
        )
    assert SECRET not in caplog.text


def test_v4_document_migrates_with_caller_finished_false_and_keeps_legacy_email() -> None:
    document = session_record_to_document(
        make_record(
            goal=None,
            identity=make_identity(NOW),
            dispatch=None,
            external_operation=None,
            password_presentation=_presentation(email_requested=1),
        )
    )
    document["schema_version"] = 4
    migrated = session_record_from_document(document)
    assert migrated.schema_version == 5
    assert migrated.password_presentation is not None
    assert migrated.password_presentation.caller_finished is False
    assert migrated.password_presentation.email_requested == 1
