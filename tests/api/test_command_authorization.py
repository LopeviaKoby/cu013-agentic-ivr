"""Authorization fixtures for the EXECUTE_ACTION order at the HTTP boundary.

The runtime creates the external action command only when the durable
dispatch guard is legal and persisted. These tests drive the real flow
(goal, identity validation event, challenge, affirmative) and pin that an
illegal or failed turn never emits a command.
"""

from app.session.record import session_record_to_document
from app.session.turns import PROCESSING_MESSAGE
from tests.api.doubles import (
    SYNTHETIC_TRANSCRIPT,
    integration_events_url,
    turns_url,
)
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

GOAL_TRANSCRIPT = "quiero desbloquear mi cuenta"
CONFIRMATION_TRANSCRIPT = "sí, adelante"


def _identity_valid_body() -> dict[str, str]:
    return {"event": "IDENTITY_VALIDATION_RESULT", "outcome": "VALID"}


async def _start_goal(client, model, action: str = "UNLOCK_ACCOUNT") -> None:
    model.decision = make_decision(
        route="COLLECT_IDENTITY",
        goal={"intent": "REQUEST", "action": action},
    )
    response = await client.post(turns_url("conversation-1"), json={"transcript": GOAL_TRANSCRIPT})
    assert response.status_code == 200


async def _validate_identity(client) -> None:
    response = await client.post(
        integration_events_url("conversation-1"), json=_identity_valid_body()
    )
    assert response.status_code == 200


async def _open_challenge(client, model) -> None:
    model.decision = make_decision(route="CONTINUE", confirmation_request=True)
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": "continúa, por favor"}
    )
    assert response.status_code == 200


async def test_legal_dispatch_returns_one_stable_order(client, model, store) -> None:
    await _start_goal(client, model)
    await _validate_identity(client)
    await _open_challenge(client, model)

    model.decision = make_decision(route="CONTINUE", confirmation_observation="AFFIRMATIVE")
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": CONFIRMATION_TRANSCRIPT}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "EXECUTE_ACTION"
    assert body["message"] == PROCESSING_MESSAGE
    assert body["command"] is not None
    assert set(body["command"]) == {"operation_id", "action", "goal_revision"}
    assert body["command"]["action"] == "UNLOCK_ACCOUNT"
    assert body["command"]["goal_revision"] == 1
    operation_id = body["command"]["operation_id"]

    document = store.documents["conversation-1"]
    assert document["dispatch"] is not None
    assert document["dispatch"]["operation_id"] == operation_id
    assert document["external_operation"]["operation_id"] == operation_id
    assert document["external_operation"]["status"] == "pending"
    assert document["confirmation"] is None

    # A repeated affirmative cannot create a second order: the challenge is
    # consumed and the active operation blocks a new one.
    repeated = await client.post(
        turns_url("conversation-1"), json={"transcript": CONFIRMATION_TRANSCRIPT}
    )
    assert repeated.status_code == 200
    assert repeated.json()["command"] is None
    assert repeated.json()["route"] == "CONTINUE"
    assert document["dispatch"]["operation_id"] == operation_id
    assert document["external_operation"]["operation_id"] == operation_id


async def test_dispatch_without_identity_never_emits_a_command(client, model, store) -> None:
    await _start_goal(client, model)
    model.decision = make_decision(
        route="CONTINUE", confirmation_observation="AFFIRMATIVE", goal_focus="PROGRESS"
    )
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": CONFIRMATION_TRANSCRIPT}
    )
    assert response.status_code == 200
    assert response.json()["command"] is None
    # The pending goal without authorization requires identity capture, so the
    # runtime never stays silent and never emits an unauthorized command.
    assert response.json()["route"] == "COLLECT_IDENTITY"
    assert store.documents["conversation-1"]["dispatch"] is None


async def test_valid_identity_opens_the_challenge_before_any_command(client, model, store) -> None:
    """The runtime, not a second model call, presents the confirmation.

    Valid identity keeps the goal and its revision, opens the specific
    challenge and answers with the action-specific confirmation; only the
    caller's later affirmative can authorize the dispatch.
    """
    from app.session.integration import UNLOCK_CONFIRMATION_MESSAGE

    await _start_goal(client, model)
    validated = await client.post(
        integration_events_url("conversation-1"), json=_identity_valid_body()
    )
    assert validated.status_code == 200
    assert validated.json()["message"] == UNLOCK_CONFIRMATION_MESSAGE
    document = store.documents["conversation-1"]
    assert document["confirmation"] is not None
    assert document["confirmation"]["action"] == "UNLOCK_ACCOUNT"
    assert document["confirmation"]["goal_revision"] == 1
    assert document["dispatch"] is None

    model.decision = make_decision(route="CONTINUE", confirmation_observation="AFFIRMATIVE")
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": CONFIRMATION_TRANSCRIPT}
    )
    assert response.status_code == 200
    assert response.json()["route"] == "EXECUTE_ACTION"
    assert response.json()["command"] is not None
    assert store.documents["conversation-1"]["dispatch"] is not None


async def test_ambiguous_confirmation_never_emits_a_command(client, model, store) -> None:
    await _start_goal(client, model)
    await _validate_identity(client)
    await _open_challenge(client, model)
    model.decision = make_decision(route="CONTINUE", confirmation_observation="AMBIGUOUS")
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": "eh... puede ser"}
    )
    assert response.status_code == 200
    assert response.json()["command"] is None
    document = store.documents["conversation-1"]
    assert document["dispatch"] is None
    assert document["confirmation"] is None


async def test_stale_challenge_never_emits_a_command(client, model, store) -> None:
    await _start_goal(client, model)
    await _validate_identity(client)
    await _open_challenge(client, model)

    # A goal correction bumps the revision and invalidates the challenge.
    model.decision = make_decision(
        route="CONTINUE", goal={"intent": "CORRECT", "action": "UNLOCK_ACCOUNT"}
    )
    corrected = await client.post(
        turns_url("conversation-1"), json={"transcript": "mejor desbloquea mi otra cuenta"}
    )
    assert corrected.status_code == 200
    assert corrected.json()["command"] is None
    assert store.documents["conversation-1"]["confirmation"] is None

    model.decision = make_decision(route="CONTINUE", confirmation_observation="AFFIRMATIVE")
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": CONFIRMATION_TRANSCRIPT}
    )
    assert response.status_code == 200
    assert response.json()["command"] is None
    assert store.documents["conversation-1"]["dispatch"] is None


async def test_failed_guard_write_never_emits_a_command(client, model, store) -> None:
    await _start_goal(client, model)
    await _validate_identity(client)
    await _open_challenge(client, model)

    store.fail_writes = True
    model.decision = make_decision(route="CONTINUE", confirmation_observation="AFFIRMATIVE")
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": CONFIRMATION_TRANSCRIPT}
    )
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal", "message": "internal error"}}
    assert "EXECUTE_ACTION" not in response.text
    document = store.documents["conversation-1"]
    assert document["dispatch"] is None
    assert document["external_operation"] is None


async def test_active_operation_blocks_a_new_challenge_and_command(client, model, store) -> None:
    await _start_goal(client, model)
    await _validate_identity(client)
    await _open_challenge(client, model)
    model.decision = make_decision(route="CONTINUE", confirmation_observation="AFFIRMATIVE")
    dispatched = await client.post(
        turns_url("conversation-1"), json={"transcript": CONFIRMATION_TRANSCRIPT}
    )
    assert dispatched.json()["route"] == "EXECUTE_ACTION"
    operation_id = dispatched.json()["command"]["operation_id"]

    model.decision = make_decision(route="CONTINUE", confirmation_request=True)
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": "podemos intentarlo otra vez"}
    )
    assert response.status_code == 200
    assert response.json()["command"] is None
    document = store.documents["conversation-1"]
    assert document["confirmation"] is None
    assert document["external_operation"]["operation_id"] == operation_id


async def test_exhausted_identity_attempts_block_dispatch(client, model, store) -> None:
    record = make_record(
        goal=make_goal("UNLOCK_ACCOUNT", revision=1),
        identity=make_identity(NOW, failures=3),
        confirmation=make_challenge("UNLOCK_ACCOUNT", revision=1),
    )
    store.documents["conversation-1"] = session_record_to_document(record)
    model.decision = make_decision(route="CONTINUE", confirmation_observation="AFFIRMATIVE")
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": CONFIRMATION_TRANSCRIPT}
    )
    assert response.status_code == 200
    assert response.json()["route"] == "ESCALATE"
    assert response.json()["command"] is None
    assert store.documents["conversation-1"]["dispatch"] is None


async def test_expired_identity_blocks_dispatch(client, model, store) -> None:
    from datetime import timedelta

    expired_at = NOW - timedelta(minutes=31)
    record = make_record(
        goal=make_goal("UNLOCK_ACCOUNT", revision=1),
        identity=make_identity(expired_at),
        confirmation=make_challenge("UNLOCK_ACCOUNT", revision=1, identity_validated_at=expired_at),
    )
    store.documents["conversation-1"] = session_record_to_document(record)
    model.decision = make_decision(route="CONTINUE", confirmation_observation="AFFIRMATIVE")
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": CONFIRMATION_TRANSCRIPT}
    )
    assert response.status_code == 200
    assert response.json()["command"] is None
    assert store.documents["conversation-1"]["dispatch"] is None


async def test_dispatch_guard_is_durable_with_a_single_operation(client, model, store) -> None:
    record = make_record(
        goal=make_goal("UNLOCK_ACCOUNT", revision=2),
        identity=make_identity(NOW),
        confirmation=make_challenge("UNLOCK_ACCOUNT", revision=2),
        dispatch=make_dispatch("UNLOCK_ACCOUNT", revision=2, operation_id="operation-7"),
        external_operation=make_operation("UNLOCK_ACCOUNT", operation_id="operation-7"),
    )
    store.documents["conversation-1"] = session_record_to_document(record)
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 200
    document = store.documents["conversation-1"]
    assert document["dispatch"]["operation_id"] == "operation-7"
    assert document["external_operation"]["operation_id"] == "operation-7"
