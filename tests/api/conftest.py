"""Shared deterministic fixtures for the HTTP boundary tests."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.api.security import API_KEY_ENV_VAR
from app.session.repository import SessionRepository
from app.session.service import TurnService
from app.session.turns import build_turn_graph
from tests.api.doubles import SYNTHETIC_API_KEY, RecordingConversationEngine
from tests.session.doubles import InMemorySessionDocumentStore

BASE_URL = "http://testserver"


@pytest.fixture
def store() -> InMemorySessionDocumentStore:
    return InMemorySessionDocumentStore()


@pytest.fixture
def service(store: InMemorySessionDocumentStore) -> TurnService:
    return TurnService(SessionRepository(store), build_turn_graph())


@pytest.fixture
def engine(service: TurnService) -> RecordingConversationEngine:
    return RecordingConversationEngine(service=service)


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(API_KEY_ENV_VAR, SYNTHETIC_API_KEY)
    return SYNTHETIC_API_KEY


@pytest.fixture
def app(engine: RecordingConversationEngine) -> FastAPI:
    return create_app(engine=engine)


def build_client(app: FastAPI, *, headers: dict[str, str] | None = None) -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url=BASE_URL, headers=headers)


@pytest.fixture
async def client(app: FastAPI, api_key: str) -> AsyncIterator[AsyncClient]:
    async with build_client(app, headers={"X-API-Key": SYNTHETIC_API_KEY}) as http_client:
        yield http_client


@pytest.fixture
async def anonymous_client(app: FastAPI, api_key: str) -> AsyncIterator[AsyncClient]:
    async with build_client(app) as http_client:
        yield http_client
