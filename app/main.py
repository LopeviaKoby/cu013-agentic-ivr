import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status

from app.config import get_settings
from app.contracts import HealthResponse, Route, TurnRequest, TurnResponse
from app.firestore import SessionData, get_session, save_session
from app.graph import compiled_graph
from app.logging import logger, setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for startup and shutdown events."""
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info(
        "Application starting",
        extra={
            "app_name": settings.app_name,
            "version": settings.app_version,
            "env": settings.app_env,
        },
    )
    yield
    logger.info("Application shutting down")


app = FastAPI(
    title="CU013 Conversational Backend",
    version="0.2.0",
    description="Conversational IT-support backend for XCALLY IVR",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse, tags=["Observability"])
async def health_check() -> HealthResponse:
    """Fast, local health check endpoint for Cloud Run and load balancers."""
    settings = get_settings()
    return HealthResponse(status="ok", version=settings.app_version)


@app.post(
    "/turn",
    response_model=TurnResponse,
    status_code=status.HTTP_200_OK,
    tags=["Telephony Contract"],
)
async def handle_turn(request: TurnRequest) -> TurnResponse:
    """Handle a single conversational turn from the telephony IVR."""
    start_time = time.perf_counter()
    turn_id = f"turn-{uuid.uuid4().hex[:12]}"

    try:
        # 1. Load existing session from Firestore
        fs_read_start = time.perf_counter()
        session = await get_session(request.conversation_id)
        fs_read_ms = round((time.perf_counter() - fs_read_start) * 1000, 2)

        if session is None:
            session = SessionData(conversation_id=request.conversation_id)

        # 2. Build minimal LangGraph state & execute minimal graph
        # Bounded history window (last 10 turns) to prevent unbounded prompt size
        recent_history = session.turns[-10:] if session.turns else []

        graph_input = {
            "conversation_id": request.conversation_id,
            "text": request.text,
            "turn_id": turn_id,
            "turn_count": session.turn_count,
            "history": recent_history,
        }

        graph_result = await compiled_graph.ainvoke(graph_input)

        route_val = graph_result.get("route", Route.CONTINUE.value)
        response_text = graph_result.get("response_text", "")
        new_turn_count = graph_result.get("turn_count", session.turn_count + 1)
        model_call_count = graph_result.get("model_call_count", 1)
        model_latency_ms = graph_result.get("model_latency_ms", 0.0)

        # 3. Update conversation history & persist session in Firestore
        session.turn_count = new_turn_count
        session.turns.append(
            {
                "turn_id": turn_id,
                "user_text": request.text,
                "bot_text": response_text,
                "route": route_val,
            }
        )
        # Keep stored session history bounded (last 20 turns)
        if len(session.turns) > 20:
            session.turns = session.turns[-20:]

        fs_write_start = time.perf_counter()
        await save_session(session)
        fs_write_ms = round((time.perf_counter() - fs_write_start) * 1000, 2)

        # 4. Compute latency & emit structured log
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.info(
            "Turn processed successfully",
            extra={
                "conversation_id": request.conversation_id,
                "turn_id": turn_id,
                "route": route_val,
                "graph_node": "process_turn",
                "turn_count": new_turn_count,
                "model_call_count": model_call_count,
                "model_latency_ms": model_latency_ms,
                "firestore_read_latency_ms": fs_read_ms,
                "firestore_write_latency_ms": fs_write_ms,
                "total_backend_latency_ms": elapsed_ms,
            },
        )

        return TurnResponse(
            turn_id=turn_id,
            route=Route(route_val),
            text=response_text,
        )

    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.error(
            "Error processing turn",
            extra={
                "conversation_id": request.conversation_id,
                "turn_id": turn_id,
                "error_class": exc.__class__.__name__,
                "total_backend_latency_ms": elapsed_ms,
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error processing conversational turn",
        ) from exc
