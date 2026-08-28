import time
from typing import Any

from google import genai
from google.genai import types

from app.config import get_settings
from app.contracts import ModelTurnOutput

DEFAULT_SYSTEM_INSTRUCTION = (
    "Eres el asistente telefónico de soporte TI para colaboradores de la empresa en "
    "español latinoamericano. Brinda respuestas claras, amables, naturales y concisas "
    "aptas para ser leídas por un sintetizador de voz (TTS). "
    "Utiliza el contexto de la conversación previa para responder con continuidad. "
    "No inventes hechos ni procedimientos empresariales que no te hayan sido dados. "
    "No afirmes que ejecutaste acciones en sistemas externos."
)


_client: genai.Client | None = None


def get_genai_client() -> genai.Client:
    """Return a process-level singleton Google GenAI client configured for Vertex AI."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = genai.Client(
            vertexai=True,
            project=settings.gcp_project_id,
            location=settings.vertex_location,
        )
    return _client


def reset_genai_client() -> None:
    """Reset the cached client instance (primarily for test isolation)."""
    global _client
    _client = None


async def generate_turn_response_async(
    contents: str | list[types.Content] | list[Any],
    system_instruction: str | None = None,
    client: genai.Client | None = None,
) -> tuple[ModelTurnOutput, float]:
    """Generate structured conversational turn response asynchronously via Vertex AI Gemini.

    Ensures process-level client reuse, enforces structured output schema,
    disables tool loops, and measures inference latency.
    """
    settings = get_settings()
    active_client = client or get_genai_client()

    config = types.GenerateContentConfig(
        system_instruction=system_instruction or DEFAULT_SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_schema=ModelTurnOutput,
        temperature=0.2,
    )

    start_time = time.perf_counter()
    response: Any = await active_client.aio.models.generate_content(
        model=settings.vertex_model,
        contents=contents,
        config=config,
    )
    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    raw_text = response.text if hasattr(response, "text") and response.text else ""
    if not raw_text and hasattr(response, "candidates") and response.candidates:
        candidate = response.candidates[0]
        if candidate.content and candidate.content.parts:
            raw_text = "".join(
                part.text for part in candidate.content.parts if hasattr(part, "text") and part.text
            )

    if not raw_text:
        raise ValueError("Model returned empty response content")

    try:
        validated_output = ModelTurnOutput.model_validate_json(raw_text)
    except Exception as exc:
        raise ValueError(f"Failed to validate model structured response: {exc}") from exc

    return validated_output, latency_ms


async def generate_content_async(
    prompt: str,
    system_instruction: str | None = None,
    client: genai.Client | None = None,
) -> str:
    """Backward-compatible helper for simple text generation."""
    output, _ = await generate_turn_response_async(
        contents=prompt,
        system_instruction=system_instruction,
        client=client,
    )
    return output.response_text
