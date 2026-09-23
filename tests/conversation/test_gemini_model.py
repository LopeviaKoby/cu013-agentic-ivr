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


def test_baseline_from_env_uses_the_active_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in (
        "CU013_VERTEX_PROJECT",
        "CU013_VERTEX_LOCATION",
        "CU013_VERTEX_MODEL",
        "CU013_VERTEX_TIMEOUT_MS",
        "CU013_VERTEX_THINKING_LEVEL",
        "CU013_VERTEX_STRICT_PROC_OBS",
    ):
        monkeypatch.delenv(var, raising=False)
    baseline = GeminiBaseline.from_env()
    assert baseline.provider == "vertex_ai"
    assert baseline.project == "cu013-xcally-agentic"
    assert baseline.location == "global"
    assert baseline.model == "gemini-3.5-flash-lite"
    assert baseline.api_version == "v1"
    assert baseline.thinking_level == "MINIMAL"
    assert baseline.strict_procedure_observation is True
    assert baseline.timeout_ms == 30000
    assert baseline.attempts == 1


def test_baseline_from_env_reads_operational_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CU013_VERTEX_PROJECT", "synthetic-project")
    monkeypatch.setenv("CU013_VERTEX_LOCATION", "synthetic-location")
    monkeypatch.setenv("CU013_VERTEX_MODEL", "synthetic-model")
    monkeypatch.setenv("CU013_VERTEX_TIMEOUT_MS", "9000")
    monkeypatch.setenv("CU013_VERTEX_THINKING_LEVEL", "MINIMAL")
    baseline = GeminiBaseline.from_env()
    assert baseline.project == "synthetic-project"
    assert baseline.location == "synthetic-location"
    assert baseline.model == "synthetic-model"
    assert baseline.timeout_ms == 9000
    assert baseline.thinking_level == "MINIMAL"
    assert baseline.attempts == 1


def test_active_conversation_baseline_is_explicit_and_reproducible() -> None:
    from app.conversation.gemini import (
        ACTIVE_API_VERSION,
        ACTIVE_ATTEMPTS,
        ACTIVE_CONVERSATION_MODEL,
        ACTIVE_MODEL_LOCATION,
        ACTIVE_THINKING_LEVEL,
        ACTIVE_TIMEOUT_MS,
        active_conversation_baseline,
    )

    baseline = active_conversation_baseline()
    assert baseline.model == ACTIVE_CONVERSATION_MODEL == "gemini-3.5-flash-lite"
    assert baseline.location == ACTIVE_MODEL_LOCATION == "global"
    assert baseline.api_version == ACTIVE_API_VERSION == "v1"
    assert baseline.thinking_level == ACTIVE_THINKING_LEVEL == "MINIMAL"
    assert baseline.strict_procedure_observation is True
    assert baseline.timeout_ms == ACTIVE_TIMEOUT_MS == 30000
    assert baseline.attempts == ACTIVE_ATTEMPTS == 1
    # Gemini 3 request carries only the level, never a budget.
    from google.genai.types import ThinkingLevel

    client = FakeGenaiClient()
    active_config = GeminiTurnModel(client, baseline)._config()  # type: ignore[arg-type]
    assert active_config.thinking_config is not None
    assert active_config.thinking_config.thinking_level == ThinkingLevel.MINIMAL
    assert active_config.thinking_config.thinking_budget is None


def test_thinking_level_selects_the_gemini3_path_without_budget() -> None:
    from google.genai.types import ThinkingLevel

    client = FakeGenaiClient()
    baseline = make_baseline(model="gemini-3.1-flash-lite", thinking_level="MINIMAL")
    model = GeminiTurnModel(client, baseline)  # type: ignore[arg-type]
    config = model._config()
    assert config.thinking_config is not None
    assert config.thinking_config.thinking_level == ThinkingLevel.MINIMAL
    assert config.thinking_config.thinking_budget is None


def test_budget_path_never_sends_a_thinking_level() -> None:
    client = FakeGenaiClient()
    model = make_model(client)
    config = model._config()
    assert config.thinking_config is not None
    assert config.thinking_config.thinking_budget == 0
    assert config.thinking_config.thinking_level is None


def test_baseline_from_env_reads_thinking_level_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CU013_VERTEX_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setenv("CU013_VERTEX_LOCATION", "us")
    monkeypatch.setenv("CU013_VERTEX_THINKING_LEVEL", "MINIMAL")
    baseline = GeminiBaseline.from_env()
    assert baseline.model == "gemini-3.1-flash-lite"
    assert baseline.location == "us"
    assert baseline.thinking_level == "MINIMAL"


async def test_thought_counts_are_recorded_as_reasoning_only() -> None:
    class ThoughtUsage(FakeUsage):
        def __init__(self) -> None:
            super().__init__()
            self.thoughts_token_count = 5

    client = FakeGenaiClient()
    client.response = FakeResponse(VALID_DECISION_JSON, usage=ThoughtUsage())
    metrics = RecordingTurnMetrics()
    model = make_model(client, metrics=metrics)
    await decide(model)
    assert dict(metrics.counters)["reasoning_tokens"] == 5


async def test_absent_thought_counts_stay_missing() -> None:
    client = FakeGenaiClient()
    client.response = FakeResponse(VALID_DECISION_JSON, usage=FakeUsage())
    metrics = RecordingTurnMetrics()
    model = make_model(client, metrics=metrics)
    await decide(model)
    assert "reasoning_tokens" not in dict(metrics.counters)


def _decision_json_with_procedure_observation() -> str:
    return '{"message": "hola", "route": "CONTINUE", "procedure_observation": "REGRESS"}'


async def test_emission_counter_records_an_explicit_cue_only() -> None:
    client = FakeGenaiClient()
    client.response = FakeResponse(_decision_json_with_procedure_observation())
    metrics = RecordingTurnMetrics()
    await decide(make_model(client, metrics=metrics))
    assert ("procedure_observation_emitted", 1) in metrics.counters


async def test_emission_counter_stays_absent_when_default_fills() -> None:
    client = FakeGenaiClient()
    client.response = FakeResponse(VALID_DECISION_JSON)
    metrics = RecordingTurnMetrics()
    await decide(make_model(client, metrics=metrics))
    assert all(name != "procedure_observation_emitted" for name, _ in metrics.counters)


def test_strict_schema_requires_and_reorders_the_cue() -> None:
    from app.conversation.gemini import response_schema_for

    base = response_schema_for(make_baseline(strict_procedure_observation=False))
    assert base is ModelTurnDecision
    strict = response_schema_for(make_baseline(strict_procedure_observation=True))
    assert isinstance(strict, dict)
    assert set(strict["properties"]) == set(ModelTurnDecision.model_fields)
    assert list(strict["properties"]).index("procedure_observation") < list(
        strict["properties"]
    ).index("goal")
    assert "procedure_observation" in strict["required"]
    assert "default" not in strict["properties"]["procedure_observation"]
    assert strict["propertyOrdering"].index("procedure_observation") < strict[
        "propertyOrdering"
    ].index("goal")


def test_config_sends_the_strict_schema_only_when_flagged() -> None:
    client = FakeGenaiClient()
    strict_model = GeminiTurnModel(  # type: ignore[arg-type]
        client, make_baseline(strict_procedure_observation=True)
    )
    assert isinstance(strict_model._config().response_schema, dict)
    relaxed_model = GeminiTurnModel(  # type: ignore[arg-type]
        client, make_baseline(strict_procedure_observation=False)
    )
    assert isinstance(relaxed_model._config().response_schema, type)


def test_strict_flag_defaults_to_required_and_reads_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("CU013_VERTEX_STRICT_PROC_OBS",):
        monkeypatch.delenv(var, raising=False)
    assert GeminiBaseline.from_env().strict_procedure_observation is True
    monkeypatch.setenv("CU013_VERTEX_STRICT_PROC_OBS", "1")
    assert GeminiBaseline.from_env().strict_procedure_observation is True
    monkeypatch.setenv("CU013_VERTEX_STRICT_PROC_OBS", "0")
    assert GeminiBaseline.from_env().strict_procedure_observation is False


def test_lenient_parsing_fills_defaults_without_procedure_cue() -> None:
    decision = parse_decision(VALID_DECISION_JSON)
    assert decision.confirmation_request is False
    strict_decision = parse_decision(
        '{"message": "hola", "route": "CONTINUE", "procedure_observation": "NONE"}'
    )
    assert strict_decision.confirmation_request is False
    assert strict_decision.procedure_observation.value == "NONE"


def test_decision_contract_shape_unchanged() -> None:
    fields = ModelTurnDecision.model_fields
    assert set(fields) == {
        "message",
        "route",
        "goal",
        "confirmation_request",
        "confirmation_observation",
        "procedure_observation",
        "handoff_cause",
        "claims",
    }
    assert ModelTurnDecision.model_config.get("extra") == "forbid"
    goal_fields = fields["goal"]
    assert goal_fields.annotation is not None


def test_active_prompt_and_contents_are_single_baseline() -> None:
    from app.conversation.gemini import contents_for, system_instructions_for
    from app.conversation.prompts import SYSTEM_INSTRUCTIONS

    assert system_instructions_for(make_baseline()) == SYSTEM_INSTRUCTIONS
    assert system_instructions_for(make_baseline(strict_procedure_observation=False)) == (
        SYSTEM_INSTRUCTIONS
    )
    contents = contents_for(state_block="objetivo: ninguno", transcript="hola")
    assert "objetivo: ninguno" in contents
    assert "hola" in contents


def test_active_config_uses_single_baseline_prompt() -> None:
    from app.conversation.prompts import SYSTEM_INSTRUCTIONS

    client = FakeGenaiClient()
    base_model = GeminiTurnModel(client, make_baseline())  # type: ignore[arg-type]
    assert base_model._config().system_instruction == SYSTEM_INSTRUCTIONS


# --- narrow polling feedback composer ---------------------------------------


def make_composer(client: FakeGenaiClient, *, metrics: RecordingTurnMetrics | None = None):  # type: ignore[no-untyped-def]
    from app.conversation.gemini import GeminiPollingFeedbackComposer

    return GeminiPollingFeedbackComposer(client, make_baseline(), metrics=metrics)  # type: ignore[arg-type]


def feedback_request():  # type: ignore[no-untyped-def]
    from app.session.feedback import (
        FeedbackObservationKind,
        FeedbackOperationState,
        PollingFeedbackRequest,
    )

    return PollingFeedbackRequest(
        action=Action.UNLOCK_ACCOUNT,
        goal_revision=2,
        confirmation_obtained=True,
        operation_state=FeedbackOperationState.PENDING,
        observation_kind=FeedbackObservationKind.PENDING,
        poll_sequence=3,
        observations_used=3,
        observation_limit=9,
        previous_messages=("Sigo con tu solicitud.",),
    )


async def test_feedback_composer_calls_once_and_returns_the_message() -> None:
    from app.conversation.gemini import PollingFeedbackOutput
    from app.conversation.prompts import POLLING_FEEDBACK_INSTRUCTIONS

    client = FakeGenaiClient()
    client.response = FakeResponse('{"message": "Sigo con tu solicitud."}')
    composer = make_composer(client)
    message = await composer.compose(feedback_request())
    assert message == "Sigo con tu solicitud."
    assert len(client.calls) == 1
    _, contents, config = client.calls[0]
    assert config.system_instruction == POLLING_FEEDBACK_INSTRUCTIONS  # type: ignore[attr-defined]
    assert config.response_schema is PollingFeedbackOutput  # type: ignore[attr-defined]
    assert "UNLOCK_ACCOUNT" in contents
    assert "PENDING" in contents
    assert "Sigo con tu solicitud." in contents


async def test_feedback_contents_never_carry_pii_or_internal_ids() -> None:
    from app.conversation.gemini import feedback_contents_for

    contents = feedback_contents_for(feedback_request())
    for canary in (
        "operation-1",
        "SYNTHETIC-DOC-0000",
        "1900-01-01-SYNTHETIC",
        "SYNTHETIC-PASSWORD-0000",
        "SYNTHETIC-TRANSCRIPT-0000",
        "synthetic@example.test",
    ):
        assert canary not in contents


async def test_feedback_composer_invalid_output_is_a_safe_failure() -> None:
    client = FakeGenaiClient()
    client.response = FakeResponse('{"message": "", "next_step": "COMPLETE"}')
    composer = make_composer(client)
    with pytest.raises(InvalidModelOutputError):
        await composer.compose(feedback_request())


async def test_feedback_composer_transport_errors_are_classified() -> None:
    client = FakeGenaiClient()
    client.error = TimeoutError()
    composer = make_composer(client)
    with pytest.raises(ModelTimeoutError):
        await composer.compose(feedback_request())


async def test_feedback_composer_records_its_own_segment_and_tokens() -> None:
    client = FakeGenaiClient()
    client.response = FakeResponse('{"message": "ok"}', usage=FakeUsage())
    metrics = RecordingTurnMetrics()
    composer = make_composer(client, metrics=metrics)
    await composer.compose(feedback_request())
    assert [name for name, _ in metrics.segments] == ["feedback_model"]
    assert dict(metrics.counters) == {"feedback_total_tokens": 19}
