"""Shared deterministic fixtures for the Thin Session Repository tests."""

import pytest

from app.session.repository import SessionRepository
from app.session.service import TurnService
from app.session.turns import build_turn_graph
from tests.session.doubles import InMemorySessionDocumentStore


@pytest.fixture
def store() -> InMemorySessionDocumentStore:
    return InMemorySessionDocumentStore()


@pytest.fixture
def repository(store: InMemorySessionDocumentStore) -> SessionRepository:
    return SessionRepository(store)


@pytest.fixture
def service(repository: SessionRepository) -> TurnService:
    return TurnService(repository, build_turn_graph())
