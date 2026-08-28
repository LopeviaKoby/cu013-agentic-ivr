# v0.2.0 Architecture

This document reflects the minimal real conversational turn architecture.

## System Boundary

```
  Caller (Phone)
       │
       ▼
  XCALLY Motion / Cally Square
       │ (HTTP POST /turn)
       ▼
  FastAPI Application (`app.main`)
  ├── 1. Pydantic Request Validation (`app.contracts.TurnRequest`)
  ├── 2. Session Repository (`app.firestore` -> Firestore Native)
  ├── 3. Orchestration Engine (`app.graph` -> LangGraph StateGraph)
  │      └── Single Turn Node (`process_turn`)
  │          └── Model Boundary (`app.gemini` -> Vertex AI / Gemini 3.5 Flash-Lite)
  │              └── Native Structured Output (`ModelTurnOutput`)
  ├── 4. Session Persistence (`app.firestore` -> save updated history)
  └── 5. Structured Observability (`app.logging` -> JSON stdout -> Cloud Logging)
```

## Turn Request Lifecycle

```text
POST /turn
→ Validate request (conversation_id, text)
→ Load session document from Firestore (or initialize empty SessionData)
→ Build minimal LangGraph state (bounded recent turn history)
→ Execute compiled LangGraph workflow
→ Exactly 1 async Gemini request to Vertex AI
→ Validate structured model result (ModelTurnOutput)
→ Update conversational history (turn_count, turns, updated_at)
→ Persist session document in Firestore
→ Emit structured JSON log record with latency breakdown
→ Return validated TurnResponse (turn_id, route, text)
```

## Component Roles

- **`app/main.py`**: Exposes `GET /health` and `POST /turn`. Coordinates the request lifecycle, latency metrics, and error logging.
- **`app/contracts.py`**: Strict Pydantic models for HTTP requests (`TurnRequest`), responses (`TurnResponse`), route enums (`Route`), and model structured outputs (`ModelTurnOutput`).
- **`app/graph.py`**: Minimal compiled LangGraph `StateGraph` containing typed `ConversationState`, multi-turn content builder, and `process_turn_node`.
- **`app/gemini.py`**: Async Google GenAI SDK boundary managing process-level `genai.Client` singleton, Latin American Spanish IT system instructions, and structured JSON output validation.
- **`app/firestore.py`**: Async Firestore session repository managing minimal, bounded `SessionData` persistence.
- **`app/logging.py`**: Structured JSON formatter with built-in PII redaction suitable for Google Cloud Logging.
- **`app/config.py`**: Environment configuration via Pydantic `BaseSettings`.

