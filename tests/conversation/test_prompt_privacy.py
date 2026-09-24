"""Privacy tests: private protocol content stays in the authorized model input.

The protocol body may travel only as the system instruction of the active
capability. It must never appear in the turn contents, the durable session
document, retained evaluation fingerprints or logs. All text here is
synthetic; no private owner protocol is used.
"""

from __future__ import annotations

import json
import logging

from app.conversation.gemini import GeminiTurnModel
from app.conversation.prompt_renderer import hash_prompt_text
from app.session.actions import Action
from app.session.record import ConversationGoal, session_record_to_document
from tests.conversation.prompt_fixtures import SYNTHETIC_RESET_BODY, make_bundle
from tests.conversation.test_gemini_model import FakeGenaiClient, make_baseline
from tests.session.doubles import make_goal, make_record


def reset_goal() -> ConversationGoal:
    return ConversationGoal(action=Action.RESET_PASSWORD, revision=1)


async def test_protocol_body_is_only_the_authorized_system_instruction() -> None:
    client = FakeGenaiClient()
    model = GeminiTurnModel(client, make_baseline(), prompts=make_bundle())  # type: ignore[arg-type]
    await model.decide(
        transcript="synthetic transcript 0000",
        goal=reset_goal(),
        identity_validated=False,
        confirmation=None,
        external_operation=None,
    )
    _, contents, config = client.calls[0]
    assert SYNTHETIC_RESET_BODY in config.system_instruction  # type: ignore[attr-defined]
    assert SYNTHETIC_RESET_BODY not in contents


def test_protocol_body_never_enters_the_durable_document() -> None:
    record = make_record(goal=make_goal(Action.RESET_PASSWORD, revision=1))
    document = session_record_to_document(record)
    assert SYNTHETIC_RESET_BODY not in json.dumps(document, default=str)


def test_protocol_body_never_appears_in_composition_identity() -> None:
    from evals.conversation_eval import prompt_composition_identity

    identity = prompt_composition_identity(make_bundle())
    payload = json.dumps(identity, default=str)
    assert SYNTHETIC_RESET_BODY not in payload
    assert identity["system_instruction_hashes"]["base"] == hash_prompt_text(
        make_bundle().system_instructions(None)
    )


async def test_protocol_body_never_reaches_logs(caplog) -> None:  # type: ignore[no-untyped-def]
    client = FakeGenaiClient()
    model = GeminiTurnModel(client, make_baseline(), prompts=make_bundle())  # type: ignore[arg-type]
    with caplog.at_level(logging.DEBUG):
        await model.decide(
            transcript="synthetic transcript 0000",
            goal=reset_goal(),
            identity_validated=False,
            confirmation=None,
            external_operation=None,
        )
    assert SYNTHETIC_RESET_BODY not in caplog.text
