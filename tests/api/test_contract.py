"""External contract tests: variants, response shape and route closure."""

import pytest
from pydantic import ValidationError

from app.api.contracts import (
    IdentityDataSlots,
    IdentityDataTurn,
    TranscriptTurn,
    TurnResponse,
)
from app.conversation.engine import Route, TurnOutcome
from tests.api.doubles import SYNTHETIC_DTMF, SYNTHETIC_TRANSCRIPT, turns_url


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


@pytest.mark.parametrize("route", list(Route))
async def test_every_emitted_route_stays_inside_the_closed_enum(client, engine, route) -> None:
    engine.outcome = TurnOutcome(message="synthetic message", route=route)
    response = await client.post(
        turns_url("conversation-1"), json={"transcript": SYNTHETIC_TRANSCRIPT}
    )
    assert response.status_code == 200
    assert response.json()["route"] == route.value
