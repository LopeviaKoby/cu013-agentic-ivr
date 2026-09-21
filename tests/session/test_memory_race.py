"""Exp 0009 same-session race characterization; synthetic only, no network.

The Thin Firestore path does a separate load and a full-document save with
no compare-and-swap, so two overlapping requests for one conversation_id
can both read revision r and each write r+1. This test pins that behavior
deterministically with a barrier before either save: it asserts the final
revision, which update survives, and zero duplicate dispatch.

Per the experiment plan the mechanism is NOT changed here: the evidence is
reported, the installed write-path signatures are inspected, and
last-writer-wins stands while XCALLY processes one conversation
sequentially. No side effect ever runs inside a retried transaction.
"""

import asyncio
import inspect

import google.cloud.firestore
from google.cloud.firestore_v1.async_document import AsyncDocumentReference

from app.session.repository import SessionRepository
from app.session.service import TurnService
from app.session.turns import TurnInput, build_turn_graph
from tests.session.doubles import (
    FrozenClock,
    InMemorySessionDocumentStore,
    make_decision,
)


async def _wait_for(predicate, *, timeout_s: float = 5.0) -> None:
    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(_poll(), timeout=timeout_s)


async def test_same_session_overlap_loses_one_update_without_dup_dispatch() -> None:
    store = InMemorySessionDocumentStore()
    clock = FrozenClock()
    repository = SessionRepository(store)

    seed_service = TurnService(repository, build_turn_graph(), clock=clock)
    seed = await seed_service.handle_turn("conversation-race", TurnInput())
    assert seed.record.revision == 1
    assert (store.reads, store.writes) == (1, 1)

    # Close the write gate only now: both racing requests must read revision
    # 1 before either saves.
    store.write_gate = asyncio.Event()

    model_a = _scripted_request("UNLOCK_ACCOUNT")
    model_b = _scripted_request("RESET_PASSWORD")
    service_a = TurnService(repository, build_turn_graph(model=model_a), clock=clock)
    service_b = TurnService(repository, build_turn_graph(model=model_b), clock=clock)

    # Both requests read revision 1 before either saves: the barrier is the
    # closed write gate, released only after both writes are pending.
    task_a = asyncio.create_task(
        service_a.handle_turn("conversation-race", TurnInput(transcript="turno A"))
    )
    await _wait_for(lambda: store.writes == 2)
    task_b = asyncio.create_task(
        service_b.handle_turn("conversation-race", TurnInput(transcript="turno B"))
    )
    await _wait_for(lambda: store.writes == 3)
    store.write_gate.set()

    result_a, result_b = await asyncio.gather(task_a, task_b)
    # Both computed from revision 1, so both wrote revision 2: one increment
    # — and one goal update — is lost. This is accepted last-writer-wins.
    assert result_a.record.revision == 2
    assert result_b.record.revision == 2
    final = store.documents["conversation-race"]
    assert final["revision"] == 2
    assert final["turn_count"] == 2
    assert final["goal"] in (
        {"action": "UNLOCK_ACCOUNT", "revision": 1},
        {"action": "RESET_PASSWORD", "revision": 1},
    )
    # No duplicate dispatch was produced by the overlap.
    assert result_a.record.dispatch is None
    assert result_b.record.dispatch is None
    assert final["dispatch"] is None
    assert (store.reads, store.writes) == (3, 3)


def _scripted_request(action: str):
    from tests.session.doubles import FakeTurnModel

    model = FakeTurnModel()
    model.decision = make_decision(goal={"intent": "REQUEST", "action": action})
    return model


def test_installed_firestore_write_path_signatures() -> None:
    """Pin the effective write-path API before any optimistic-concurrency talk.

    Installed google-cloud-firestore 2.30.0 exposes ``option`` (precondition
    support) on ``update()`` but not on ``set()``; the full-document ``set``
    the repository uses has no compare-and-swap. Behavior against the
    effective backend stays unverified; this test only records the client
    surface the plan must choose from if the race ever needs a decision.
    """
    assert google.cloud.firestore.__version__ == "2.30.0"
    update_params = inspect.signature(AsyncDocumentReference.update).parameters
    set_params = inspect.signature(AsyncDocumentReference.set).parameters
    assert "option" in update_params
    assert "option" not in set_params
    assert "retry" in update_params and "timeout" in update_params
