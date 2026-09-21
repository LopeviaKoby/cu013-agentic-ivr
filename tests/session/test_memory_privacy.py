"""Exp 0009 spoken-lane frontier and memory privacy tests (fake model only).

Two complementary findings, both with in-test synthetic canaries (never
fixtures, logs or artifacts):

1. PROTECTED (DTMF/event lane): a canary that travels the identity-event
   path never reaches model arguments, the window, the record or logs.
2. FRONTIER (normal ASR transcript lane): a spoken canary DOES reach the
   model via the current direct transcript concatenation, and the
   recent-memory window would retain it. This pins why textual memory
   stays disabled for real
   callers until an accepted retention/sanitization policy exists. No Vertex
   call is used; the exposure is demonstrated with the fake model only.
"""

import logging
import secrets

from app.session.memory import ExperimentalMemoryConfig, append_pair, make_pair
from app.session.repository import SessionRepository
from app.session.service import TurnService
from app.session.turns import IdentityOutcome, TurnInput, build_turn_graph
from tests.session.doubles import (
    FakeTurnModel,
    FrozenClock,
    InMemorySessionDocumentStore,
    make_decision,
)

RECENT_MEMORY = ExperimentalMemoryConfig(variant="recent_conversation_memory")


def _fresh_canary(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


async def test_identity_event_canary_never_reaches_model_or_memory(caplog) -> None:
    canary = _fresh_canary("SYNTHETIC-EVENT")
    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    service = TurnService(
        SessionRepository(store), build_turn_graph(model=model), clock=FrozenClock()
    )
    with caplog.at_level(logging.DEBUG):
        await service.handle_turn(
            "conversation-1",
            TurnInput(
                transcript="quiero desbloquear mi cuenta",
                identity_outcome=IdentityOutcome.CALLER_FAILURE,
            ),
            experimental=RECENT_MEMORY,
        )
    # The event outcome is structured (no raw value exists in TurnInput by
    # construction); the transcript lane carries no canary here either.
    for call in model.calls:
        assert canary not in call["transcript"]
        assert call["memory_context"] is None or canary not in call["memory_context"]
    record = store.documents["conversation-1"]
    assert canary not in repr(record)
    assert canary not in caplog.text


async def test_spoken_canary_reaches_the_model_through_the_transcript_lane() -> None:
    """Pins the current exposure: normal speech is forwarded verbatim."""
    canary = _fresh_canary("palabra-canaria")
    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    service = TurnService(
        SessionRepository(store), build_turn_graph(model=model), clock=FrozenClock()
    )
    await service.handle_turn(
        "conversation-1",
        TurnInput(transcript=f"quiero restablecer mi contraseña {canary}"),
        experimental=RECENT_MEMORY,
    )
    assert len(model.calls) == 1
    assert canary in model.calls[0]["transcript"]
    # ... and the experimental window would retain those words, which is
    # exactly why recent-memory text is synthetic-only and never enabled
    # for real callers in this iteration.
    window = service_stats_window(store)
    assert any(canary in pair.caller_text for pair in window)


def service_stats_window(store: InMemorySessionDocumentStore):  # type: ignore[no-untyped-def]
    from app.session.record import session_record_from_document

    return session_record_from_document(store.documents["conversation-1"]).experimental_window


async def test_window_text_never_enters_logs_or_metrics(caplog) -> None:
    marker = _fresh_canary("ventana")
    store = InMemorySessionDocumentStore()
    model = FakeTurnModel()
    model.decision = make_decision(message="respuesta sintética breve")
    service = TurnService(
        SessionRepository(store), build_turn_graph(model=model), clock=FrozenClock()
    )
    with caplog.at_level(logging.DEBUG):
        result = await service.handle_turn(
            "conversation-1",
            TurnInput(transcript=marker),
            experimental=RECENT_MEMORY,
        )
    assert marker not in caplog.text
    assert result.memory is not None
    assert marker not in repr(result.memory)
    # Metrics carry counts and bytes only.
    assert result.memory.memory_pairs == 1
    assert result.memory.memory_bytes > 0


def test_pure_append_never_copies_secrets_into_markers() -> None:
    canary = _fresh_canary("SYNTHETIC-PASSWORD")
    pair = make_pair(canary * 200, "respuesta", sequence=1, goal_revision=None)
    assert pair.omitted is True
    assert canary not in (pair.caller_text + pair.assistant_text)
    pairs, _ = append_pair((), pair, window_n=3)
    assert canary not in repr(pairs)
