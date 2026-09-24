"""Active conversational model adapter over Vertex AI (google-genai, ADC).

The active conversational baseline is Gemini 3.5 Flash-Lite on Vertex AI,
model location ``global``, reasoning level ``MINIMAL``, structured output
enabled, mandatory structured procedure classification sent early in the
response schema, and a recent-conversation window of three completed
caller/assistant turn pairs rendered only for synthetic evaluation turns.

The system instruction is composed by the injected ``PromptSource``: the
active product path selects the precomposed core + catalog (+ the active
private runtime protocol of the durable goal) built once at startup, while the
evaluation baseline lane can replay a frozen static text.

Authentication is ADC only: never a Gemini API key or service-account JSON.
Exactly one generate_content call per turn, without streaming, tools or
hidden retries: the single-attempt policy and the explicit deadline keep
the baseline honest for latency.

Historic note: an earlier baseline used Gemini 2.5 Flash-Lite in
``us-east1`` with ``thinking_budget=0`` and no procedure/memory window.
Its history lives in the accepted ADR, Experiment 0009 and Git. The
active path never defaults to the historic model, location, budget or
prompt variants. Discarded compact-prompt and confirmation-request
variants were removed from the active path after evaluation; their
evidence lives in the experiment record, not in runtime flags.
"""

import json
import os
import time
from typing import Any, Literal

from google.genai import Client
from google.genai.errors import APIError
from google.genai.types import (
    GenerateContentConfig,
    GenerateContentResponse,
    HttpOptions,
    HttpRetryOptions,
    ThinkingConfig,
    ThinkingLevel,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.conversation.errors import (
    InvalidModelOutputError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.conversation.prompt_renderer import PromptSource
from app.conversation.prompts import POLLING_FEEDBACK_INSTRUCTIONS
from app.session.feedback import PollingFeedbackRequest
from app.session.metrics import NullTurnMetrics, TurnMetrics
from app.session.record import (
    ConfirmationChallenge,
    ConversationGoal,
    ExternalOperation,
)
from app.session.state_projection import (
    ModelStateProjection,
    projection_from_turn_inputs,
)
from app.session.turns import ModelTurnDecision

PROVIDER: Literal["vertex_ai"] = "vertex_ai"

# Active conversational baseline (descriptive, no experimental codes).
# Infrastructure regions (Cloud Run, Firestore) stay in us-east1; the model
# location below is the Vertex AI serving location, not infrastructure.
ACTIVE_CONVERSATION_MODEL = "gemini-3.5-flash-lite"
ACTIVE_MODEL_LOCATION = "global"
ACTIVE_API_VERSION = "v1"
ACTIVE_THINKING_LEVEL = "MINIMAL"
ACTIVE_TIMEOUT_MS = 30000
ACTIVE_ATTEMPTS = 1


class GeminiBaseline(BaseModel):
    """Effective Vertex AI baseline for measurement.

    Gemini 2 mediated thinking with ``thinking_budget`` (0 disables thought
    content on 2.5 Flash-Lite); Gemini 3 uses ``thinking_level`` instead and
    the API rejects combining both or sending a level to a pre-3 model.
    Exactly one of the two is ever sent: when ``thinking_level`` is set the
    request carries only the level and the identity reports
    ``thinking_budget=None``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["vertex_ai"] = PROVIDER
    project: str
    location: str
    model: str
    api_version: str
    thinking_budget: int
    thinking_level: str | None = None
    strict_procedure_observation: bool = True
    timeout_ms: int
    attempts: int

    @classmethod
    def from_env(cls) -> "GeminiBaseline":
        """Active baseline with operational overrides only.

        Defaults describe the accepted conversational baseline. Project,
        model location, model id and timeout remain overridable through the
        environment for operational drift or historic replay; reasoning
        level defaults to MINIMAL and structured procedure classification
        defaults to required.
        """
        thinking_level = os.environ.get("CU013_VERTEX_THINKING_LEVEL", ACTIVE_THINKING_LEVEL)
        strict_raw = os.environ.get("CU013_VERTEX_STRICT_PROC_OBS", "1")
        return cls(
            project=os.environ.get("CU013_VERTEX_PROJECT", "cu013-xcally-agentic"),
            location=os.environ.get("CU013_VERTEX_LOCATION", ACTIVE_MODEL_LOCATION),
            model=os.environ.get("CU013_VERTEX_MODEL", ACTIVE_CONVERSATION_MODEL),
            api_version=ACTIVE_API_VERSION,
            thinking_budget=0,
            thinking_level=thinking_level or None,
            strict_procedure_observation=strict_raw == "1",
            timeout_ms=int(os.environ.get("CU013_VERTEX_TIMEOUT_MS", str(ACTIVE_TIMEOUT_MS))),
            attempts=ACTIVE_ATTEMPTS,
        )


def active_conversation_baseline(*, project: str = "cu013-xcally-agentic") -> GeminiBaseline:
    """Explicit active conversational baseline (no hidden historic defaults)."""
    return GeminiBaseline(
        project=project,
        location=ACTIVE_MODEL_LOCATION,
        model=ACTIVE_CONVERSATION_MODEL,
        api_version=ACTIVE_API_VERSION,
        thinking_budget=0,
        thinking_level=ACTIVE_THINKING_LEVEL,
        strict_procedure_observation=True,
        timeout_ms=ACTIVE_TIMEOUT_MS,
        attempts=ACTIVE_ATTEMPTS,
    )


def contents_for(
    *,
    state_block: str,
    transcript: str,
) -> str:
    """Effective model contents: semantic projection plus current transcript."""
    return "Estado del sistema:\n" + state_block + "\nTurno del llamante:\n" + transcript


def response_schema_for(baseline: GeminiBaseline) -> Any:
    """Return the response schema actually sent for one baseline.

    The active path sends a transformed copy of the shared decision
    contract: the existing ``procedure_observation`` (structured procedure
    classification: NONE for keep, ADVANCE when the caller completed the
    current guided step, REGRESS when the caller did not finish it without
    changing the goal, PAUSE/RESUME for temporary suspension) becomes
    required with no default and is ordered before the goal-mutating
    fields, so the model classifies progress explicitly and early.
    Parsing always stays lenient (the base contract with its NONE/False
    defaults), so an omission can never become a new turn-failure mode —
    it is measured as defaulted instead.
    """
    if not baseline.strict_procedure_observation:
        return ModelTurnDecision
    schema = ModelTurnDecision.model_json_schema()
    properties = schema.get("properties", {})
    order = [
        "message",
        "route",
        "procedure_observation",
        "goal",
        "confirmation_request",
        "confirmation_observation",
        "handoff_cause",
        "claims",
    ]
    assert set(order) == set(properties), "strict schema must mirror the decision contract"
    schema["properties"] = {name: properties[name] for name in order}
    schema["propertyOrdering"] = list(order)
    required = [name for name in schema.get("required", []) if name in order]
    if "procedure_observation" not in required:
        required.append("procedure_observation")
    schema["required"] = required
    proc = schema["properties"]["procedure_observation"]
    proc.pop("default", None)
    return schema


STATE_PROJECTION_OPEN = "<conversation_state>"
STATE_PROJECTION_CLOSE = "</conversation_state>"


def render_state_projection(projection: ModelStateProjection) -> str:
    """Render the transient projection as one compact, stable JSON block.

    Deterministic key order keeps the block reproducible and hash-friendly;
    only closed semantic values travel, never caller text.
    """
    payload = json.dumps(projection.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return f"{STATE_PROJECTION_OPEN}\n{payload}\n{STATE_PROJECTION_CLOSE}"


def parse_decision(text: str) -> ModelTurnDecision:
    """Validate model JSON against the typed decision contract."""
    try:
        return ModelTurnDecision.model_validate_json(text)
    except ValidationError as exc:
        raise InvalidModelOutputError("model output violated the decision contract") from exc


class PollingFeedbackOutput(BaseModel):
    """The only field the narrow feedback composer may return."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str = Field(min_length=1)


def parse_feedback_output(text: str) -> PollingFeedbackOutput:
    """Validate the composer JSON against its one-field contract."""
    try:
        return PollingFeedbackOutput.model_validate_json(text)
    except ValidationError as exc:
        raise InvalidModelOutputError("feedback output violated its contract") from exc


def feedback_contents_for(request: PollingFeedbackRequest) -> str:
    """Render the closed PII-safe projection the composer may see.

    Only semantic operation facts travel: no transcript, no textual caller or
    assistant memory, no identity values or timestamps, no ``operation_id``, no
    RD body, no raw unknown status, no password, no email.
    """
    previous = (
        "\n".join(f"- {message}" for message in request.previous_messages)
        if request.previous_messages
        else "(ninguno)"
    )
    return (
        "Estado de la operación:\n"
        f"accion: {request.action.value}\n"
        f"revision: {request.goal_revision}\n"
        f"confirmacion_obtenida: {'sí' if request.confirmation_obtained else 'no'}\n"
        f"estado: {request.operation_state.value}\n"
        f"observacion: {request.observation_kind.value}\n"
        f"secuencia: {request.poll_sequence}\n"
        f"observaciones_usadas: {request.observations_used} "
        f"de {request.observation_limit}\n"
        "mensajes_previos:\n"
        f"{previous}"
    )


def _classify_transport_error(exc: Exception) -> Exception | None:
    """Map SDK transport errors by type name without importing httpx/httpx2."""
    for base in type(exc).__mro__:
        name = base.__name__
        if name in {"TimeoutException", "TimeoutError"}:
            return ModelTimeoutError("vertex ai call exceeded its deadline")
        if name in {"ConnectError", "NetworkError"}:
            return ModelUnavailableError("vertex ai is not reachable")
    return None


class GeminiTurnModel:
    """Vertex AI adapter implementing TurnModel; one call per normal turn."""

    def __init__(
        self,
        client: Client,
        baseline: GeminiBaseline,
        *,
        prompts: PromptSource,
        metrics: TurnMetrics | None = None,
    ) -> None:
        self._client = client
        self._baseline = baseline
        self._prompts = prompts
        self._metrics: TurnMetrics = metrics or NullTurnMetrics()

    async def decide(
        self,
        *,
        transcript: str,
        goal: ConversationGoal | None,
        identity_validated: bool,
        confirmation: ConfirmationChallenge | None,
        external_operation: ExternalOperation | None,
        memory_context: str | None = None,
        procedure_current: str | None = None,
        state_projection: ModelStateProjection | None = None,
    ) -> ModelTurnDecision:
        start = time.monotonic()
        try:
            try:
                # The runtime-built projection is the authoritative view; the
                # adapter fallback only mirrors the facts it already received.
                projection = state_projection or projection_from_turn_inputs(
                    goal=goal,
                    identity_validated=identity_validated,
                    confirmation=confirmation,
                    external_operation=external_operation,
                    procedure_current=procedure_current,
                )
                # Synthetic evaluation lane only: the rendered
                # recent-pair/procedure block follows the projection and
                # precedes the current transcript. Real-caller textual memory
                # stays disabled until an accepted retention policy exists.
                state_block = render_state_projection(projection)
                if memory_context:
                    state_block += "\n" + memory_context
                response = await self._client.aio.models.generate_content(
                    model=self._baseline.model,
                    contents=contents_for(
                        state_block=state_block,
                        transcript=transcript,
                    ),
                    config=self._config(goal, procedure_current),
                )
            except APIError as exc:
                raise ModelUnavailableError("vertex ai request failed") from exc
            except Exception as exc:
                classified = _classify_transport_error(exc)
                if classified is not None:
                    raise classified from exc
                raise
        finally:
            self._metrics.record_segment("model", (time.monotonic() - start) * 1000.0)
        self._record_usage(response)
        try:
            text = response.text
        except ValueError as exc:
            raise InvalidModelOutputError("model produced no text") from exc
        if text is None:
            raise InvalidModelOutputError("model produced no text")
        self._record_emission(text)
        return parse_decision(text)

    def _record_emission(self, text: str) -> None:
        """Record whether the model emitted the procedure cue explicitly.

        Key presence in the raw JSON only — never values, transcripts or
        message text. An omission is filled by the NONE default downstream
        and measured here as defaulted.
        """
        try:
            payload = json.loads(text)
        except ValueError:
            return
        if isinstance(payload, dict) and "procedure_observation" in payload:
            self._metrics.record_counter("procedure_observation_emitted", 1)

    def _config(
        self, goal: ConversationGoal | None, procedure_current: str | None = None
    ) -> GenerateContentConfig:
        baseline = self._baseline
        if baseline.thinking_level is not None:
            # Gemini 3 path: discrete level only; the API rejects combining
            # a level with thinking_budget. An unknown level fails closed
            # here, before any request.
            thinking = ThinkingConfig(thinking_level=ThinkingLevel(baseline.thinking_level))
        else:
            thinking = ThinkingConfig(thinking_budget=baseline.thinking_budget)
        return GenerateContentConfig(
            system_instruction=self._prompts.system_instructions(goal, procedure_current),
            response_mime_type="application/json",
            response_schema=response_schema_for(baseline),
            thinking_config=thinking,
            http_options=HttpOptions(
                timeout=baseline.timeout_ms,
                retry_options=HttpRetryOptions(attempts=baseline.attempts),
            ),
        )

    def _record_usage(self, response: GenerateContentResponse) -> None:
        """Record token counts only; never any content.

        Thought/reasoning tokens (Gemini 3) are counts only and are never
        persisted as conversational memory.
        """
        usage = response.usage_metadata
        if usage is None:
            return
        if usage.prompt_token_count is not None:
            self._metrics.record_counter("prompt_tokens", usage.prompt_token_count)
        if usage.candidates_token_count is not None:
            self._metrics.record_counter("completion_tokens", usage.candidates_token_count)
        if usage.total_token_count is not None:
            self._metrics.record_counter("total_tokens", usage.total_token_count)
        thoughts = getattr(usage, "thoughts_token_count", None)
        if thoughts is not None:
            self._metrics.record_counter("reasoning_tokens", thoughts)
        # Cache hits are counts only: implicit caching is provider-side and
        # this counter records whatever the effective SDK reports.
        cached = getattr(usage, "cached_content_token_count", None)
        if cached is not None:
            self._metrics.record_counter("cached_tokens", cached)


class GeminiPollingFeedbackComposer:
    """Narrow Vertex AI adapter for one waiting-feedback message.

    It receives only the closed PII-safe projection, returns only a message and
    can never decide the next step, authorize, dispatch or touch identity.
    Exactly one call per invocation, no streaming, no tools, no hidden retries;
    a timeout or invalid output stays a failure the runtime turns into silence.
    """

    def __init__(
        self,
        client: Client,
        baseline: GeminiBaseline,
        *,
        metrics: TurnMetrics | None = None,
    ) -> None:
        self._client = client
        self._baseline = baseline
        self._metrics: TurnMetrics = metrics or NullTurnMetrics()

    async def compose(self, request: PollingFeedbackRequest) -> str | None:
        start = time.monotonic()
        try:
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._baseline.model,
                    contents=feedback_contents_for(request),
                    config=self._config(),
                )
            except APIError as exc:
                raise ModelUnavailableError("vertex ai request failed") from exc
            except Exception as exc:
                classified = _classify_transport_error(exc)
                if classified is not None:
                    raise classified from exc
                raise
        finally:
            self._metrics.record_segment("feedback_model", (time.monotonic() - start) * 1000.0)
        usage = response.usage_metadata
        if usage is not None and usage.total_token_count is not None:
            self._metrics.record_counter("feedback_total_tokens", usage.total_token_count)
        try:
            text = response.text
        except ValueError as exc:
            raise InvalidModelOutputError("feedback model produced no text") from exc
        if text is None:
            raise InvalidModelOutputError("feedback model produced no text")
        return parse_feedback_output(text).message

    def _config(self) -> GenerateContentConfig:
        baseline = self._baseline
        if baseline.thinking_level is not None:
            thinking = ThinkingConfig(thinking_level=ThinkingLevel(baseline.thinking_level))
        else:
            thinking = ThinkingConfig(thinking_budget=baseline.thinking_budget)
        return GenerateContentConfig(
            system_instruction=POLLING_FEEDBACK_INSTRUCTIONS,
            response_mime_type="application/json",
            response_schema=PollingFeedbackOutput,
            thinking_config=thinking,
            http_options=HttpOptions(
                timeout=baseline.timeout_ms,
                retry_options=HttpRetryOptions(attempts=baseline.attempts),
            ),
        )
