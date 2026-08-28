from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.contracts import Route


class ConversationState(TypedDict, total=False):
    """Minimal typed state for LangGraph execution."""

    conversation_id: str
    text: str
    turn_id: str
    turn_count: int
    route: str
    response_text: str


async def process_turn_node(state: ConversationState) -> dict[str, Any]:
    """Single meaningful scaffolding node that processes the turn and forms a response."""
    current_count = state.get("turn_count", 0) + 1

    # Scaffolding behavior for Increment 1: acknowledge receipt and continue
    return {
        "turn_count": current_count,
        "route": Route.CONTINUE.value,
        "response_text": "Entendido. ¿En qué más puedo ayudarte?",
    }


def create_conversation_graph() -> Any:
    """Build and compile the minimal LangGraph workflow."""
    workflow = StateGraph(ConversationState)

    # Add the single meaningful node
    workflow.add_node("process_turn", process_turn_node)

    # Simple linear flow
    workflow.add_edge(START, "process_turn")
    workflow.add_edge("process_turn", END)

    return workflow.compile()


# Process-level compiled graph
compiled_graph = create_conversation_graph()
