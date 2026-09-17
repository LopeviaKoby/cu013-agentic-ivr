"""Gemini adapter deterministic tests: config, parsing and error mapping.

No Vertex AI, network or credentials are involved: the genai client is a
recording double and every value is synthetic.
"""

from typing import Any

import pytest
from google.genai.errors import APIError

from app.conversation.errors import (
    InvalidModelOutputError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.conversation.gemini import GeminiBaseline, GeminiTurnModel, parse_decision
from app.session.metrics import RecordingTurnMetrics
from app.session.record import Action, DeliveryStatus, ExternalOperation, OperationStatus
from app.session.turns import GoalIntent, ModelTurnDecision, Route
from tests.session.doubles import make_challenge, make_goal

VALID_DECISION_JSON = '{"message": "hola", "route": "CONTINUE"}'


class FakeUsage:
    def __init__(self) -> None:
        self.prompt_token_count = 12
        self.candidates_token_count = 7
        self.total_token_count = 19


class FakeResponse:
    def __init__(self, text: str | None, usage: object | None = None) -> None:
        self._text = text
        self.usage_metadata = usage

    @property
    def text(self) -> str:
        if self._text is None:
            raise ValueError("model produced no text")
        return self._text


class FakeModels:
    def __init__(self, owner: "FakeGenaiClient") -> None:
        self._owner = owner

    async def generate_content(self, *, model: str, contents, config):
        self._owner.calls.append((model, contents, config))
        if self._owner.error is not None:
            raise self._owner.error
        return self._owner.response


class FakeAio:
    def __init__(self, owner: "FakeGenaiClient") -> None:
        self.models = FakeModels(owner)


class FakeGenaiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.response = FakeResponse(VALID_DECISION_JSON)
        self.error: Exception | None = None
        self.aio = FakeAio(self)


class ConnectError(Exception):
    """Stands in for httpx/httpx2 ConnectError by type name."""


def make_baseline(**overrides: object) -> GeminiBaseline:
    values: dict[str, object] = {
        "project": "synthetic-project",
        "location": "synthetic-location",
        "model": "synthetic-model",
        "api_version": "v1",
        "thinking_budget": 0,
        "timeout_ms": 15000,
        "attempts": 1,
    }
    values.update(overrides)
    return GeminiBaseline(**values)


def make_model(
    client: FakeGenaiClient, *, metrics: RecordingTurnMetrics | None = None
) -> GeminiTurnModel:
    return GeminiTurnModel(client, make_baseline(), metrics=metrics)  # type: ignore[arg-type]


async def decide(model: GeminiTurnModel, **overrides: Any) -> ModelTurnDecision:
    values: dict[str, Any] = {
        "transcript": "synthetic transcript 0000",
        "goal": None,
        "identity_validated": False,
        "confirmation": None,
        "external_operation": None,
    }
    values.update(overrides)
    return await model.decide(**values)


def test_parse_decision_accepts_the_typed_contract() -> None:
    decision = parse_decision(VALID_DECISION_JSON)
    assert decision.message == "hola"
    assert decision.route is Route.CONTINUE
    assert decision.goal is None
    assert decision.confirmation_request is False
    assert decision.claims == ()


def test_parse_decision_accepts_a_goal_proposal_and_claims() -> None:
    decision = parse_decision(
        '{"message": "ok", "route": "COLLECT_IDENTITY", '
        '"goal": {"intent": "REQUEST", "action": "RESET_PASSWORD"}, '
        '"claims": [{"kind": "IDENTITY_VALID"}]}'
    )
    assert decision.goal is not None
    assert decision.goal.intent is GoalIntent.REQUEST
    assert decision.goal.action is Action.RESET_PASSWORD
    assert decision.claims[0].kind.value == "IDENTITY_VALID"


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        '{"message": "hola"}',
        '{"message": "hola", "route": "UNKNOWN"}',
        '{"message": "", "route": "CONTINUE"}',
        '{"message": "hola", "route": "CONTINUE", "extra": 1}',
        '{"message": "hola", "route": "CONTINUE", "identity_validated": true}',
        '{"message": "hola", "route": "CONTINUE", "goal": {"intent": "BREAK"}}',
        '{"message": "hola", "route": "CONTINUE", "claims": [{"kind": "UNDELIVERED"}]}',
    ],
)
def test_parse_decision_rejects_invalid_output(text: str) -> None:
    with pytest.raises(InvalidModelOutputError):
        parse_decision(text)


async def test_decide_calls_generate_content_once_with_the_baseline_config() -> None:
    client = FakeGenaiClient()
    model = make_model(client)
    decision = await decide(model)
    assert decision.message == "hola"
    assert len(client.calls) == 1
    model_name, contents, config = client.calls[0]
    assert model_name == "synthetic-model"
    assert "synthetic transcript 0000" in contents
    assert "objetivo: ninguno" in contents
    assert "identidad_validada: no" in contents
    assert "confirmación_pendiente: ninguna" in contents
    assert "operación_externa: ninguna" in contents
    assert config.thinking_config.thinking_budget == 0  # type: ignore[attr-defined]
    assert config.response_mime_type == "application/json"  # type: ignore[attr-defined]
    assert config.response_schema is not None  # type: ignore[attr-defined]
    assert config.http_options.timeout == 15000  # type: ignore[attr-defined]
    assert config.http_options.retry_options.attempts == 1  # type: ignore[attr-defined]


async def test_contents_carry_only_the_semantic_projection() -> None:
    client = FakeGenaiClient()
    model = make_model(client)
    await decide(
        model,
        goal=make_goal(Action.UNLOCK_ACCOUNT, revision=2),
        identity_validated=True,
        confirmation=make_challenge(Action.RESET_PASSWORD, revision=1),
        external_operation=ExternalOperation(
            operation_id="operation-1",
            action=Action.RESET_PASSWORD,
            status=OperationStatus.CONFIRMED,
            delivery=DeliveryStatus.PENDING,
        ),
    )
    _, contents, _ = client.calls[0]
    assert "objetivo: UNLOCK_ACCOUNT (revisión 2)" in contents
    assert "identidad_validada: sí" in contents
    assert "confirmación_pendiente: RESET_PASSWORD (revisión 1)" in contents
    assert "operación_externa: RESET_PASSWORD (confirmed) entrega=pending" in contents


async def test_api_error_maps_to_model_unavailable() -> None:
    client = FakeGenaiClient()
    client.error = APIError(code=503, response_json={"error": {"message": "outage"}})
    model = make_model(client)
    with pytest.raises(ModelUnavailableError):
        await decide(model)


async def test_timeout_maps_to_model_timeout() -> None:
    client = FakeGenaiClient()
    client.error = TimeoutError()
    model = make_model(client)
    with pytest.raises(ModelTimeoutError):
        await decide(model)


async def test_connect_error_maps_to_model_unavailable() -> None:
    client = FakeGenaiClient()
    client.error = ConnectError("synthetic connect failure")
    model = make_model(client)
    with pytest.raises(ModelUnavailableError):
        await decide(model)


async def test_unknown_errors_propagate_unchanged() -> None:
    client = FakeGenaiClient()
    client.error = RuntimeError("synthetic unexpected failure")
    model = make_model(client)
    with pytest.raises(RuntimeError, match="synthetic unexpected failure"):
        await decide(model)


async def test_response_without_text_is_invalid_output() -> None:
    client = FakeGenaiClient()
    client.response = FakeResponse(None)
    model = make_model(client)
    with pytest.raises(InvalidModelOutputError):
        await decide(model)


async def test_usage_is_recorded_as_token_counts_only() -> None:
    client = FakeGenaiClient()
    client.response = FakeResponse(VALID_DECISION_JSON, usage=FakeUsage())
    metrics = RecordingTurnMetrics()
    model = make_model(client, metrics=metrics)
    await decide(model)
    assert dict(metrics.counters) == {
        "prompt_tokens": 12,
        "completion_tokens": 7,
        "total_tokens": 19,
    }
    segment_names = [name for name, _ in metrics.segments]
    assert segment_names == ["model"]


async def test_model_segment_is_recorded_even_on_failure() -> None:
    client = FakeGenaiClient()
    client.error = TimeoutError()
    metrics = RecordingTurnMetrics()
    model = make_model(client, metrics=metrics)
    with pytest.raises(ModelTimeoutError):
        await decide(model)
    assert [name for name, _ in metrics.segments] == ["model"]


def test_baseline_from_env_uses_the_session_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in (
        "CU013_VERTEX_PROJECT",
        "CU013_VERTEX_LOCATION",
        "CU013_VERTEX_MODEL",
        "CU013_VERTEX_TIMEOUT_MS",
    ):
        monkeypatch.delenv(var, raising=False)
    baseline = GeminiBaseline.from_env()
    assert baseline.provider == "vertex_ai"
    assert baseline.project == "cu013-xcally-agentic"
    assert baseline.location == "us-east1"
    assert baseline.model == "gemini-2.5-flash-lite"
    assert baseline.api_version == "v1"
    assert baseline.thinking_budget == 0
    assert baseline.timeout_ms == 15000
    assert baseline.attempts == 1


def test_baseline_from_env_reads_operational_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CU013_VERTEX_PROJECT", "synthetic-project")
    monkeypatch.setenv("CU013_VERTEX_LOCATION", "synthetic-location")
    monkeypatch.setenv("CU013_VERTEX_MODEL", "synthetic-model")
    monkeypatch.setenv("CU013_VERTEX_TIMEOUT_MS", "9000")
    baseline = GeminiBaseline.from_env()
    assert baseline.project == "synthetic-project"
    assert baseline.location == "synthetic-location"
    assert baseline.model == "synthetic-model"
    assert baseline.timeout_ms == 9000
    assert baseline.thinking_budget == 0
    assert baseline.attempts == 1
