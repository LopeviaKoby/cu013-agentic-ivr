import pytest

from app.contracts import Route
from app.graph import create_conversation_graph


@pytest.mark.asyncio
async def test_langgraph_compilation_and_traversal() -> None:
    """Minimal StateGraph compiles and executes single-turn traversal."""
    graph = create_conversation_graph()
    assert graph is not None

    initial_state = {
        "conversation_id": "test-conv-001",
        "text": "Tengo problemas con FortiClient",
        "turn_id": "turn-test-1",
        "turn_count": 0,
    }

    result = await graph.ainvoke(initial_state)

    assert isinstance(result, dict)
    assert result["turn_count"] == 1
    assert result["route"] == Route.CONTINUE.value
    assert isinstance(result["response_text"], str)
    assert len(result["response_text"]) > 0
