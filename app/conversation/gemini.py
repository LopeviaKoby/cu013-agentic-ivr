"""Gemini 2.5 Flash-Lite turn model over Vertex AI (google-genai, ADC).

The baseline configuration is replaceable in one place with optional
environment overrides. Authentication is ADC only: never a Gemini API key
or service-account JSON. Exactly one generate_content call per turn,
without streaming, tools or hidden retries: the single-attempt policy and
the explicit deadline keep the DEV baseline honest for latency.
"""

import os
import time
from typing import Literal

from google.genai import Client
from google.genai.errors import APIError
from google.genai.types import (
    GenerateContentConfig,
    GenerateContentResponse,
    HttpOptions,
    HttpRetryOptions,
    ThinkingConfig,
)
from pydantic import BaseModel, ConfigDict, ValidationError

from app.conversation.errors import (
    InvalidModelOutputError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from app.session.metrics import NullTurnMetrics, TurnMetrics
from app.session.record import Action, PendingOperation
from app.session.turns import ModelTurnDecision

PROVIDER: Literal["vertex_ai"] = "vertex_ai"


class GeminiBaseline(BaseModel):
    """Effective Vertex AI baseline for the DEV measurement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["vertex_ai"] = PROVIDER
    project: str
    location: str
    model: str
    api_version: str
    thinking_budget: int
    timeout_ms: int
    attempts: int

    @classmethod
    def from_env(cls) -> "GeminiBaseline":
        """Baseline fixed by the session; project/location/model/model-timeout
        remain overridable through the environment for operational drift."""
        return cls(
            project=os.environ.get("CU013_VERTEX_PROJECT", "cu013-xcally-agentic"),
            location=os.environ.get("CU013_VERTEX_LOCATION", "us-east1"),
            model=os.environ.get("CU013_VERTEX_MODEL", "gemini-2.5-flash-lite"),
            api_version="v1",
            thinking_budget=0,
            timeout_ms=int(os.environ.get("CU013_VERTEX_TIMEOUT_MS", "15000")),
            attempts=1,
        )


SYSTEM_INSTRUCTIONS = (
    "Eres el asistente telefónico de la Mesa de Ayuda. Ayudas a las personas a "
    "restablecer su contraseña o desbloquear su cuenta. Habla en español, con "
    "frases breves y naturales, aptas para lectura en voz alta.\n"
    "\n"
    "Responde únicamente con un objeto JSON con exactamente tres campos:\n"
    "- message: texto breve que se leerá al llamante.\n"
    "- route: una de CONTINUE, COLLECT_IDENTITY, COMPLETE, ESCALATE.\n"
    "- action_requested: RESET_PASSWORD, UNLOCK_ACCOUNT o null.\n"
    "\n"
    "Reglas:\n"
    "- Usa COLLECT_IDENTITY cuando falte capturar el documento o la fecha de "
    "nacimiento del llamante; se capturan por tonos, así que no pidas que los "
    "lea en voz alta.\n"
    "- Usa action_requested solo cuando el llamante haya pedido explícitamente "
    "la acción y el estado del sistema indique identidad_validada: sí.\n"
    "- Nunca inventes resultados: no digas que una contraseña fue restablecida "
    "ni que una cuenta fue desbloqueada; solo el sistema confirma resultados.\n"
    "- Si hay una operación pendiente, di que la solicitud está en proceso.\n"
    "- No pidas ni menciones documentos o fechas de nacimiento completos; nunca "
    "recibes esos valores.\n"
    "- Usa ESCALATE cuando el llamante necesite ayuda humana o el autoservicio "
    "no sea posible.\n"
    "- Usa COMPLETE solo para cerrar la conversación."
)


def _state_block(
    identity_validated: bool,
    requested_action: Action | None,
    pending_operation: PendingOperation | None,
) -> str:
    """Render only the allowed semantic projection of the durable record."""
    lines = [
        f"identidad_validada: {'sí' if identity_validated else 'no'}",
        f"acción_solicitada: {requested_action.value if requested_action else 'ninguna'}",
    ]
    if pending_operation is None:
        lines.append("operación_pendiente: ninguna")
    else:
        lines.append(
            f"operación_pendiente: {pending_operation.action.value} "
            f"({pending_operation.status.value})"
        )
    return "\n".join(lines)


def parse_decision(text: str) -> ModelTurnDecision:
    """Validate model JSON against the typed decision contract."""
    try:
        return ModelTurnDecision.model_validate_json(text)
    except ValidationError as exc:
        raise InvalidModelOutputError("model output violated the decision contract") from exc


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
        metrics: TurnMetrics | None = None,
    ) -> None:
        self._client = client
        self._baseline = baseline
        self._metrics: TurnMetrics = metrics or NullTurnMetrics()

    async def decide(
        self,
        *,
        transcript: str,
        identity_validated: bool,
        requested_action: Action | None,
        pending_operation: PendingOperation | None,
    ) -> ModelTurnDecision:
        start = time.monotonic()
        try:
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._baseline.model,
                    contents=(
                        "Estado del sistema:\n"
                        + _state_block(identity_validated, requested_action, pending_operation)
                        + "\nTurno del llamante:\n"
                        + transcript
                    ),
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
            self._metrics.record_segment("model", (time.monotonic() - start) * 1000.0)
        self._record_usage(response)
        try:
            text = response.text
        except ValueError as exc:
            raise InvalidModelOutputError("model produced no text") from exc
        if text is None:
            raise InvalidModelOutputError("model produced no text")
        return parse_decision(text)

    def _config(self) -> GenerateContentConfig:
        baseline = self._baseline
        return GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTIONS,
            response_mime_type="application/json",
            response_schema=ModelTurnDecision,
            thinking_config=ThinkingConfig(thinking_budget=baseline.thinking_budget),
            http_options=HttpOptions(
                timeout=baseline.timeout_ms,
                retry_options=HttpRetryOptions(attempts=baseline.attempts),
            ),
        )

    def _record_usage(self, response: GenerateContentResponse) -> None:
        """Record token counts only; never any content."""
        usage = response.usage_metadata
        if usage is None:
            return
        if usage.prompt_token_count is not None:
            self._metrics.record_counter("prompt_tokens", usage.prompt_token_count)
        if usage.candidates_token_count is not None:
            self._metrics.record_counter("completion_tokens", usage.candidates_token_count)
        if usage.total_token_count is not None:
            self._metrics.record_counter("total_tokens", usage.total_token_count)
