import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.contracts import ModelTurnOutput
from app.gemini import generate_turn_response_async, get_genai_client, reset_genai_client


@pytest.mark.asyncio
async def test_gemini_async_boundary_single_call_and_structured_output() -> None:
    """Async Gemini boundary executes exactly 1 async call and returns validated ModelTurnOutput."""
    mock_response = MagicMock()
    mock_response.text = json.dumps({"response_text": "Hola, puedo ayudarte con tu conexión VPN."})

    mock_aio_models = MagicMock()
    mock_aio_models.generate_content = AsyncMock(return_value=mock_response)

    mock_client = MagicMock()
    mock_client.aio.models = mock_aio_models

    output, latency_ms = await generate_turn_response_async(
        contents="Hola",
        client=mock_client,
    )

    assert isinstance(output, ModelTurnOutput)
    assert output.response_text == "Hola, puedo ayudarte con tu conexión VPN."
    assert latency_ms >= 0.0
    mock_aio_models.generate_content.assert_awaited_once()

    call_kwargs = mock_aio_models.generate_content.await_args.kwargs
    assert call_kwargs["contents"] == "Hola"
    assert call_kwargs["config"].response_mime_type == "application/json"
    assert call_kwargs["config"].response_schema == ModelTurnOutput


@pytest.mark.asyncio
async def test_gemini_async_boundary_rejects_invalid_json() -> None:
    """When the model returns non-JSON or invalid schema, a ValueError is raised."""
    mock_response = MagicMock()
    mock_response.text = "This is not valid JSON"

    mock_aio_models = MagicMock()
    mock_aio_models.generate_content = AsyncMock(return_value=mock_response)

    mock_client = MagicMock()
    mock_client.aio.models = mock_aio_models

    with pytest.raises(ValueError, match="Failed to validate model structured response"):
        await generate_turn_response_async(
            contents="Hola",
            client=mock_client,
        )

    mock_aio_models.generate_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_gemini_async_boundary_rejects_empty_response() -> None:
    """When the model returns empty response text, a ValueError is raised."""
    mock_response = MagicMock()
    mock_response.text = ""
    mock_response.candidates = []

    mock_aio_models = MagicMock()
    mock_aio_models.generate_content = AsyncMock(return_value=mock_response)

    mock_client = MagicMock()
    mock_client.aio.models = mock_aio_models

    with pytest.raises(ValueError, match="Model returned empty response content"):
        await generate_turn_response_async(
            contents="Hola",
            client=mock_client,
        )

    mock_aio_models.generate_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_gemini_async_boundary_propagates_provider_exception() -> None:
    """Provider exceptions/timeouts propagate immediately without hidden retries."""
    mock_aio_models = MagicMock()
    mock_aio_models.generate_content = AsyncMock(
        side_effect=TimeoutError("Vertex AI deadline exceeded")
    )

    mock_client = MagicMock()
    mock_client.aio.models = mock_aio_models

    with pytest.raises(TimeoutError, match="Vertex AI deadline exceeded"):
        await generate_turn_response_async(
            contents="Hola",
            client=mock_client,
        )

    mock_aio_models.generate_content.assert_awaited_once()


def test_genai_client_singleton_reuse() -> None:
    """genai.Client is reused at process-level and reset cleanly."""
    reset_genai_client()
    client1 = get_genai_client()
    client2 = get_genai_client()
    assert client1 is client2
    reset_genai_client()
