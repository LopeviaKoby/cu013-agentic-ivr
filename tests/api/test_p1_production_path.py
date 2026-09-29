"""The productive boundary engine always renders P1 derived context.

One deterministic proof, no model calls: an UNDECIDED RESET turn through
SessionConversationEngine must reach the model with the closed obligation
block, while the raw service seam keeps rendering nothing by default
(evaluation baselines opt out explicitly).
"""

from app.conversation.engine import ConversationTurn, SessionConversationEngine
from app.session.actions import Action
from app.session.record import AssistanceMode, session_record_to_document
from app.session.repository import SessionRepository
from app.session.service import TurnService
from app.session.turns import TurnInput, build_turn_graph
from tests.session.doubles import (
    NOW,
    FakeTurnModel,
    FrozenClock,
    InMemorySessionDocumentStore,
    make_goal,
    make_identity,
    make_record,
)


def _seeded(conversation_id: str = "p1-path") -> InMemorySessionDocumentStore:
    store = InMemorySessionDocumentStore()
    store.documents[conversation_id] = session_record_to_document(
        make_record(
            conversation_id=conversation_id,
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.UNDECIDED),
            identity=make_identity(NOW),
        )
    )
    return store


async def test_boundary_engine_renders_p1_obligation() -> None:
    store = _seeded()
    model = FakeTurnModel()
    engine = SessionConversationEngine(
        TurnService(SessionRepository(store), build_turn_graph(model=model), clock=FrozenClock())
    )
    outcome = await engine.handle_turn(
        ConversationTurn(conversation_id="p1-path", transcript="hola")
    )
    assert outcome.next_step is not None
    assert len(model.calls) == 1
    block = model.calls[0]["semantic_obligation"]
    assert block is not None
    assert "ASSISTANCE_MODE_CHOICE" in block
    assert "RESET_PASSWORD" in block
    assert "transcript" not in block


async def test_raw_service_seam_defaults_to_no_obligation() -> None:
    store = _seeded("p1-baseline")
    model = FakeTurnModel()
    service = TurnService(
        SessionRepository(store), build_turn_graph(model=model), clock=FrozenClock()
    )
    await service.handle_turn(
        "p1-baseline",
        TurnInput(transcript="hola"),
        experimental=None,
    )
    assert len(model.calls) == 1
    assert model.calls[0]["semantic_obligation"] is None
    assert model.calls[0]["memory_context"] is None
