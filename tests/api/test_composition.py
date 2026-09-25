"""Composition tests: the DEV wiring builds a complete real boundary.

No network or credentials are involved: the genai and Firestore clients are
constructed lazily and only closed here.
"""

import pytest

import app.main as main
from app.api.security import API_KEY_ENV_VAR
from app.conversation.engine import SessionConversationEngine
from app.conversation.prompt_loader import PROTOCOL_DIR_ENV
from app.main import DEFAULT_FIRESTORE_COLLECTION, build_app
from app.session.integration import IntegrationEventService
from app.session.metrics import RecordingTurnMetrics
from tests.api.doubles import SYNTHETIC_API_KEY
from tests.conversation.prompt_fixtures import write_synthetic_protocols


@pytest.fixture
def protocol_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    """Synthetic private protocols: the product path never ships without them."""
    directory = write_synthetic_protocols(tmp_path)  # type: ignore[arg-type]
    monkeypatch.setenv(PROTOCOL_DIR_ENV, str(directory))


async def test_build_app_wires_the_real_boundary(
    monkeypatch: pytest.MonkeyPatch, protocol_dir: None
) -> None:
    monkeypatch.setenv(API_KEY_ENV_VAR, SYNTHETIC_API_KEY)
    metrics = RecordingTurnMetrics()
    app = build_app(metrics=metrics)
    try:
        assert isinstance(app.state.conversation_engine, SessionConversationEngine)
        assert isinstance(app.state.integration_events, IntegrationEventService)
        assert app.state.turn_metrics is metrics
        assert app.state.genai_client is not None
        assert app.state.firestore_client is not None
        paths = app.openapi()["paths"]
        assert "/api/v1/conversations/{conversation_id}/turns" in paths
        assert "/api/v1/conversations/{conversation_id}/integration-events" in paths
        assert DEFAULT_FIRESTORE_COLLECTION == "cu013dev_sessions"
    finally:
        await app.state.genai_client.aio.aclose()
        app.state.firestore_client.close()  # type: ignore[attr-defined]


async def test_build_app_uses_one_default_metrics_instance_everywhere(
    monkeypatch: pytest.MonkeyPatch, protocol_dir: None
) -> None:
    captured_model_metrics: list[object | None] = []

    class CapturingModel:
        def __init__(
            self, *args: object, prompts: object | None = None, metrics: object | None = None
        ) -> None:
            captured_model_metrics.append(metrics)

        async def decide(self, **kwargs: object) -> object:
            raise AssertionError("the composition test must not invoke the model")

    monkeypatch.setenv(API_KEY_ENV_VAR, SYNTHETIC_API_KEY)
    metrics = RecordingTurnMetrics()
    monkeypatch.setattr(main, "StructuredLogTurnMetrics", lambda: metrics)
    monkeypatch.setattr(main, "GeminiTurnModel", CapturingModel)
    app = build_app()
    try:
        service = app.state.conversation_engine._service
        assert app.state.turn_metrics is metrics
        assert service._metrics is metrics
        assert app.state.integration_events._metrics is metrics
        assert captured_model_metrics == [metrics]
    finally:
        await app.state.genai_client.aio.aclose()
        app.state.firestore_client.close()  # type: ignore[attr-defined]
