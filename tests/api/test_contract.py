"""External contract tests: variants, response shape and route closure."""

import pytest
from pydantic import ValidationError

from app.api.contracts import (
    IdentityDataSlots,
    IdentityDataTurn,
    TranscriptTurn,
    TurnResponse,
)
from app.session.turns import Route
from tests.api.doubles import SYNTHETIC_DTMF, SYNTHETIC_TRANSCRIPT, turns_url
from tests.session.doubles import make_decision


async def test_transcript_turn_returns_the_cally_square_contract(client) -> None:
    response = await client.post(
        turns_url("conversation-1"),
        json={"transcript": SYNTHETIC_TRANSCRIPT, "asr_confidence": 0.0, "channel": "voice"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"message", "route", "turn_id"}
    assert body["message"] == "synthetic message"
    assert body["route"] == "CONTINUE"
    assert body["turn_id"]


async def test_transcript_variant_without_confidence_or_channel_is_accepted(client) -> None:
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 200


def test_identity_data_variant_is_typed() -> None:
    turn = IdentityDataTurn.model_validate(
        {"event": "IDENTITY_DATA", "slots": {"document_id": SYNTHETIC_DTMF}}
    )
    assert isinstance(turn.slots, IdentityDataSlots)
    assert turn.channel == "voice"


def test_request_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TranscriptTurn.model_validate({"transcript": SYNTHETIC_TRANSCRIPT, "unknown": True})


def test_response_model_rejects_a_route_outside_the_enum() -> None:
    with pytest.raises(ValidationError):
        TurnResponse(message="synthetic message", route="UNKNOWN", turn_id="turn-1")


async def test_every_emitted_route_stays_inside_the_closed_enum(client, model) -> None:
    """The runtime may only emit the four accepted routes, never a new one."""
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
