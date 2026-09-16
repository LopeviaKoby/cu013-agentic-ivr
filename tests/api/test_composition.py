"""Composition tests: the DEV wiring builds a complete real boundary.

No network or credentials are involved: the genai and Firestore clients are
constructed lazily and only closed here.
"""

import pytest

from app.api.security import API_KEY_ENV_VAR
from app.conversation.engine import SessionConversationEngine
from app.main import DEFAULT_FIRESTORE_COLLECTION, build_app
from app.session.metrics import RecordingTurnMetrics
from tests.api.doubles import SYNTHETIC_API_KEY


async def test_build_app_wires_the_real_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_KEY_ENV_VAR, SYNTHETIC_API_KEY)
    metrics = RecordingTurnMetrics()
    app = build_app(metrics=metrics)
    try:
        assert isinstance(app.state.conversation_engine, SessionConversationEngine)
        assert app.state.turn_metrics is metrics
        assert app.state.genai_client is not None
        assert app.state.firestore_client is not None
        paths = app.openapi()["paths"]
        assert "/api/v1/conversations/{conversation_id}/turns" in paths
        assert DEFAULT_FIRESTORE_COLLECTION == "cu013dev_sessions"
    finally:
        await app.state.genai_client.aio.aclose()
        app.state.firestore_client.close()  # type: ignore[attr-defined]
