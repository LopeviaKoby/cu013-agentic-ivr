from unittest.mock import AsyncMock, MagicMock

import pytest

from app.gemini import generate_content_async


@pytest.mark.asyncio
async def test_gemini_async_boundary_with_mock() -> None:
    """Async Gemini boundary correctly passes prompts and returns response text
    without real API calls."""
    mock_response = MagicMock()
    mock_response.text = "Hola, puedo ayudarte con tu conexión VPN."

    mock_aio_models = MagicMock()
    mock_aio_models.generate_content = AsyncMock(return_value=mock_response)

    mock_client = MagicMock()
    mock_client.aio.models = mock_aio_models

    result = await generate_content_async(
        prompt="Hola",
        system_instruction="Eres un asistente de TI",
        client=mock_client,
    )

    assert result == "Hola, puedo ayudarte con tu conexión VPN."
    mock_aio_models.generate_content.assert_awaited_once()

    # Verify model and content args
    call_kwargs = mock_aio_models.generate_content.await_args.kwargs
    assert call_kwargs["contents"] == "Hola"
    assert call_kwargs["config"].system_instruction == "Eres un asistente de TI"
