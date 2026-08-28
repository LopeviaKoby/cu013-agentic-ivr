from typing import Any

from google import genai
from google.genai import types

from app.config import get_settings

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


async def generate_content_async(
    prompt: str,
    system_instruction: str | None = None,
    client: genai.Client | None = None,
) -> str:
    """Generate content asynchronously via Vertex AI Gemini.

    Ensures client reuse and disables automatic SDK tool loops.
    """
    settings = get_settings()
    active_client = client or get_genai_client()

    config = types.GenerateContentConfig()
    if system_instruction:
        config.system_instruction = system_instruction

    # Use the async client (.aio)
    response: Any = await active_client.aio.models.generate_content(
        model=settings.vertex_model,
        contents=prompt,
        config=config,
    )

    if response.text:
        return str(response.text)
    return ""
