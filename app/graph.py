from typing import Any, TypedDict

from google.genai import types
from langgraph.graph import END, START, StateGraph

from app.contracts import Route
from app.gemini import generate_turn_response_async


class ConversationState(TypedDict, total=False):
    """Minimal typed state for LangGraph execution."""

    conversation_id: str
    text: str
    turn_id: str
    turn_count: int
    history: list[dict[str, Any]]
    route: str
    response_text: str
    model_call_count: int
    model_latency_ms: float
    gemini_client: Any


def build_gemini_contents(history: list[dict[str, Any]], current_text: str) -> list[types.Content]:
    """Build multi-turn Content list from recent history and current turn."""
    contents: list[types.Content] = []
    for past_turn in history:
        user_txt = past_turn.get("user_text")
        bot_txt = past_turn.get("bot_text")
        if user_txt:
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=user_txt)],
                )
            )
        if bot_txt:
            contents.append(
                types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=bot_txt)],
                )
            )
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=current_text)],
        )
    )
    return contents


async def process_turn_node(state: ConversationState) -> dict[str, Any]:
    """Single meaningful node that invokes Gemini and produces structured response."""
    current_count = state.get("turn_count", 0) + 1
    history = state.get("history", [])
    current_text = state.get("text", "")
    client = state.get("gemini_client")

    contents = build_gemini_contents(history, current_text)

    # Normal turn executes exactly 1 async Gemini request
    model_output, model_latency_ms = await generate_turn_response_async(
        contents=contents,
        client=client,
    )

    return {
        "turn_count": current_count,
        "route": Route.CONTINUE.value,
        "response_text": model_output.response_text,
        "model_call_count": 1,
        "model_latency_ms": model_latency_ms,
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
