from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.contracts import ModelTurnOutput, Route
from app.graph import build_gemini_contents, create_conversation_graph


def test_build_gemini_contents_multi_turn() -> None:
    """Multi-turn history maps to alternating user/model Content objects
    followed by current text."""
    history = [
        {"turn_id": "t1", "user_text": "Estoy en Perú", "bot_text": "Entendido."},
        {"turn_id": "t2", "user_text": "Uso FortiClient", "bot_text": "¿Cuál es el error?"},
    ]
    current_text = "Dice error 404"

    contents = build_gemini_contents(history, current_text)

    assert len(contents) == 5
    for c in contents:
        assert c.parts is not None
        assert len(c.parts) > 0

    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "Estoy en Perú"  # type: ignore[index]
    assert contents[1].role == "model"
    assert contents[1].parts[0].text == "Entendido."  # type: ignore[index]
    assert contents[2].role == "user"
    assert contents[2].parts[0].text == "Uso FortiClient"  # type: ignore[index]
    assert contents[3].role == "model"
    assert contents[3].parts[0].text == "¿Cuál es el error?"  # type: ignore[index]
    assert contents[4].role == "user"
    assert contents[4].parts[0].text == "Dice error 404"  # type: ignore[index]


@pytest.mark.asyncio
async def test_langgraph_compilation_and_traversal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Minimal StateGraph compiles and executes single-turn traversal
    with deterministic model output."""

    mock_model_call = AsyncMock(
        return_value=(
            ModelTurnOutput(response_text="Entendido, te puedo ayudar con FortiClient."),
            35.5,
        )
    )
    monkeypatch.setattr("app.graph.generate_turn_response_async", mock_model_call)

    graph = create_conversation_graph()
    assert graph is not None

    initial_state: dict[str, Any] = {
        "conversation_id": "test-conv-001",
        "text": "Tengo problemas con FortiClient",
        "turn_id": "turn-test-1",
        "turn_count": 0,
        "history": [],
    }

    result = await graph.ainvoke(initial_state)

    assert isinstance(result, dict)
    assert result["turn_count"] == 1
    assert result["route"] == Route.CONTINUE.value
    assert result["response_text"] == "Entendido, te puedo ayudar con FortiClient."
    assert result["model_call_count"] == 1
    assert result["model_latency_ms"] == 35.5
    mock_model_call.assert_awaited_once()
