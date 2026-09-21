"""External contract tests: variants, response shape and enum closure."""

import pytest
from pydantic import ValidationError

from app.api.contracts import TranscriptTurn, TurnResponse
from app.session.turns import BoundaryRoute, ExternalActionCommand, Route
from tests.api.doubles import SYNTHETIC_TRANSCRIPT, turns_url
from tests.session.doubles import make_decision


async def test_transcript_turn_returns_the_cally_square_contract(client) -> None:
    response = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT, "asr_confidence": 0.0, "channel": "voice"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message", "route", "turn_id", "command"}
    assert body["message"] == "synthetic message"
    assert body["route"] == "CONTINUE"
    assert body["turn_id"]
    assert body["command"] is None


async def test_transcript_variant_without_confidence_or_channel_is_accepted(client) -> None:
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 200


def test_request_model_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TranscriptTurn.model_validate({"transcript": SYNTHETIC_TRANSCRIPT, "unknown": True})


def test_response_model_rejects_a_route_outside_the_enum() -> None:
    with pytest.raises(ValidationError):
        TurnResponse(message="synthetic message", route="UNKNOWN", turn_id="turn-1")


def test_route_enum_separates_model_and_boundary_contracts() -> None:
    assert {route.value for route in Route} == {
        "CONTINUE",
        "COLLECT_IDENTITY",
        "COMPLETE",
        "ESCALATE",
    }
    assert {route.value for route in BoundaryRoute} == {
        "CONTINUE",
        "COLLECT_IDENTITY",
        "COMPLETE",
        "ESCALATE",
        "EXECUTE_ACTION",
    }


def test_model_facing_contract_never_exposes_execute_action() -> None:
    """EXECUTE_ACTION is runtime-only: the LLM schema must not change."""
    import json

    from app.conversation.gemini import active_conversation_baseline, response_schema_for
    from app.session.turns import ModelTurnDecision

    decision_schema = json.dumps(ModelTurnDecision.model_json_schema())
    strict_schema = json.dumps(response_schema_for(active_conversation_baseline()))
    assert "EXECUTE_ACTION" not in decision_schema
    assert "EXECUTE_ACTION" not in strict_schema


def test_command_only_exists_with_execute_action() -> None:
    command = ExternalActionCommand(
        operation_id="operation-1", action="UNLOCK_ACCOUNT", goal_revision=1
    )
    with pytest.raises(ValidationError):
        TurnResponse(
            message="synthetic message",
            route=BoundaryRoute.CONTINUE,
            turn_id="turn-1",
            command=command,
        )
    with pytest.raises(ValidationError):
        TurnResponse(
            message="synthetic message",
            route=BoundaryRoute.EXECUTE_ACTION,
            turn_id="turn-1",
        )
    allowed = TurnResponse(
        message="synthetic message",
        route=BoundaryRoute.EXECUTE_ACTION,
        turn_id="turn-1",
        command=command,
    )
    assert allowed.command == command


async def test_model_routes_stay_inside_the_model_enum(client, model) -> None:
    """The model proposes only the four model routes; EXECUTE_ACTION is runtime-only."""
    observed: set[str] = set()
    for decision in (
        make_decision(route=Route.CONTINUE),
        make_decision(route=Route.COMPLETE),
        make_decision(
            route=Route.COLLECT_IDENTITY,
            goal={"intent": "REQUEST", "action": "UNLOCK_ACCOUNT"},
        ),
        make_decision(route=Route.ESCALATE, handoff_cause="CALLER_REQUEST"),
    ):
        model.decision = decision
        response = await client.post(
            turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
        )
        assert response.status_code == 200
        observed.add(response.json()["route"])
    assert observed == {route.value for route in Route}
    assert "EXECUTE_ACTION" not in observed
