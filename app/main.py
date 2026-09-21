"""DEV composition root wiring real Gemini and Firestore into the boundary.

Builds the FastAPI boundary with the real conversational engine. The genai
and Firestore async clients are reused process-wide and closed on shutdown
through the FastAPI lifespan.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from google.cloud.firestore import AsyncClient as FirestoreAsyncClient
from google.genai import Client
from google.genai.types import HttpOptions

from app.api.app import create_app
from app.conversation.engine import SessionConversationEngine
from app.conversation.gemini import GeminiBaseline, GeminiTurnModel
from app.session.integration import IntegrationEventService
from app.session.metrics import StructuredLogTurnMetrics, TurnMetrics
from app.session.repository import FirestoreSessionDocumentStore, SessionRepository
from app.session.service import TurnService
from app.session.turns import build_turn_graph

FIRESTORE_COLLECTION_ENV = "CU013_FIRESTORE_COLLECTION"
DEFAULT_FIRESTORE_COLLECTION = "cu013dev_sessions"


def build_app(*, metrics: TurnMetrics | None = None) -> FastAPI:
    """Compose the real DEV application; clients close with the lifespan."""
    effective_metrics = metrics if metrics is not None else StructuredLogTurnMetrics()
    baseline = GeminiBaseline.from_env()
    genai_client = Client(
        vertexai=True,
        project=baseline.project,
        location=baseline.location,
        http_options=HttpOptions(api_version=baseline.api_version),
    )
    collection = os.environ.get(FIRESTORE_COLLECTION_ENV, DEFAULT_FIRESTORE_COLLECTION)
    firestore_client = FirestoreAsyncClient(project=baseline.project)
    store = FirestoreSessionDocumentStore(firestore_client, collection)
    model = GeminiTurnModel(genai_client, baseline, metrics=effective_metrics)
    repository = SessionRepository(store)
    service = TurnService(
        repository,
        build_turn_graph(model=model),
        metrics=effective_metrics,
    )
    integration_events = IntegrationEventService(repository, metrics=effective_metrics)
    app = create_app(
        engine=SessionConversationEngine(service), integration_events=integration_events
    )
    app.state.turn_metrics = effective_metrics
    app.state.genai_client = genai_client
    app.state.firestore_client = firestore_client

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await genai_client.aio.aclose()
            firestore_client.close()  # type: ignore[no-untyped-call]

    app.router.lifespan_context = lifespan
    return app
