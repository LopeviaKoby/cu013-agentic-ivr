"""Boundary tests for the ephemeral voice password vocalization.

The synthetic secret is generated per test, never stored in a fixture, and
the assertions only inspect closed, non-sensitive facts plus the privacy
canaries.
"""

import logging

from app.api.contracts_next_step import NEXT_STEP_CONTRACT, RESPONSE_CONTRACT_HEADER
from app.session.actions import Action
from app.session.record import (
    OperationStatus,
    PasswordPresentation,
    PlaybackVoice,
    session_record_to_document,
)
from tests.api.doubles import turns_url
from tests.session.doubles import (
    NOW,
    FakeTurnModel,
    InMemorySessionDocumentStore,
    make_decision,
    make_dispatch,
    make_identity,
    make_operation,
    make_record,
)

NEXT_STEP_HEADERS = {RESPONSE_CONTRACT_HEADER: NEXT_STEP_CONTRACT}
SECRET = "Zx9!q2-Mw"


def _seed(
    store: InMemorySessionDocumentStore,
    *,
    plane: bool = False,
    caller_finished: bool = False,
) -> None:
    presentation = (
        PasswordPresentation(
            operation_id="operation-1",
            action=Action.RESET_PASSWORD,
            goal_revision=1,
            voice=PlaybackVoice.PLAYBACK_RETURNED,
            caller_finished=caller_finished,
            presented_at=NOW,
        )
        if plane
        else None
    )
    store.documents["conversation-1"] = session_record_to_document(
        make_record(
            goal=None,
            identity=make_identity(NOW),
            dispatch=make_dispatch(Action.RESET_PASSWORD, revision=1, operation_id="operation-1"),
            external_operation=make_operation(
                Action.RESET_PASSWORD, OperationStatus.CONFIRMED, operation_id="operation-1"
            ),
            password_presentation=presentation,
        )
    )


async def test_first_vocalization_accepts_a_null_transcript_and_delivers(
    client, model: FakeTurnModel, store: InMemorySessionDocumentStore, caplog
) -> None:  # type: ignore[no-untyped-def]
    _seed(store)
    model.decision = make_decision(route="CONTINUE", message="Toma nota. Tu contraseña es Zeta.")
    with caplog.at_level(logging.INFO):
        response = await client.post(
            turns_url("conversation-1"),
            json={"temporary_password": SECRET},
            headers=NEXT_STEP_HEADERS,
        )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message", "next_step", "operation_state", "command"}
    assert body["next_step"] == "DELIVER_PASSWORD"
    assert body["command"] is None
    assert body["message"]
    assert model.calls[0]["delivery_secret"] == SECRET
    assert SECRET not in repr(store.documents["conversation-1"])
    assert SECRET not in caplog.text


async def test_legacy_lane_rejects_the_ephemeral_secret(client, store) -> None:  # type: ignore[no-untyped-def]
    _seed(store)
    response = await client.post(
        turns_url("conversation-1"),
        json={"transcript": "hola", "temporary_password": SECRET},
    )
    assert response.status_code == 422


async def test_turn_without_transcript_or_password_is_rejected(client, store) -> None:  # type: ignore[no-untyped-def]
    _seed(store)
    response = await client.post(
        turns_url("conversation-1"),
        json={},
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 422


async def test_repeat_turn_keeps_delivering_and_never_redispatches(
    client, model: FakeTurnModel, store: InMemorySessionDocumentStore
) -> None:  # type: ignore[no-untyped-def]
    _seed(store)
    model.decision = make_decision(route="CONTINUE", message="Repito: Zeta, equis, nueve.")
    response = await client.post(
        turns_url("conversation-1"),
        json={"transcript": "repítela desde el nueve", "temporary_password": SECRET},
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["next_step"] == "DELIVER_PASSWORD"
    document = store.documents["conversation-1"]
    assert document["goal"] is None
    assert document["dispatch"]["operation_id"] == "operation-1"  # type: ignore[index]
    assert document["external_operation"]["status"] == "confirmed"  # type: ignore[index]
    assert SECRET not in repr(document)


async def test_caller_finished_listens_and_leaves_the_secret_out(
    client, model: FakeTurnModel, store: InMemorySessionDocumentStore
) -> None:  # type: ignore[no-untyped-def]
    # A playback plane must exist before the finish can be persisted.
    _seed(store, plane=True)
    model.decision = make_decision(
        route="CONTINUE",
        message="Perfecto.",
        password_presentation_finished=True,
    )
    response = await client.post(
        turns_url("conversation-1"),
        json={"transcript": "ya está, gracias", "temporary_password": SECRET},
        headers=NEXT_STEP_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["next_step"] == "LISTEN"
    assert SECRET not in response.text
    document = store.documents["conversation-1"]
    assert document["password_presentation"]["caller_finished"] is True  # type: ignore[index]
    assert SECRET not in repr(document)


async def test_legacy_lane_keeps_requiring_a_transcript(client, store) -> None:  # type: ignore[no-untyped-def]
    _seed(store)
    response = await client.post(turns_url("conversation-1"), json={})
    assert response.status_code == 422
