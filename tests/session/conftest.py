"""Shared deterministic fixtures for the Thin Session Repository tests."""

from datetime import UTC, datetime

import pytest

from app.session.repository import SessionRepository
from app.session.service import TurnService
from app.session.turns import build_turn_graph
from tests.session.doubles import FakeTurnModel, FrozenClock, InMemorySessionDocumentStore

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def store() -> InMemorySessionDocumentStore:
    return InMemorySessionDocumentStore()


@pytest.fixture
def repository(store: InMemorySessionDocumentStore) -> SessionRepository:
    return SessionRepository(store)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def service(repository: SessionRepository, clock: FrozenClock) -> TurnService:
    return TurnService(repository, build_turn_graph(), clock=clock)


@pytest.fixture
def model() -> FakeTurnModel:
    return FakeTurnModel()


@pytest.fixture
def service_with_model(
    repository: SessionRepository, model: FakeTurnModel, clock: FrozenClock
) -> TurnService:
    return TurnService(repository, build_turn_graph(model=model), clock=clock)
