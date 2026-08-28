# v0.2.0 Architecture (Increment 1)

This document reflects exclusively the architecture that exists in Increment 1.

## System Boundary

```
  Caller (Phone)
       │
       ▼
  XCALLY Motion / Cally Square
       │ (HTTP POST /turn)
       ▼
  FastAPI Application (`app.main`)
  ├── Pydantic Input Validation (`app.contracts`)
  ├── Session Store Boundary (`app.firestore` -> Firestore Native)
  ├── Orchestration Boundary (`app.graph` -> LangGraph StateGraph)
  ├── Model Boundary (`app.gemini` -> Vertex AI / Gemini 3.5 Flash-Lite)
  └── Structured Logging (`app.logging` -> JSON stdout -> Cloud Logging)
```

## Component Roles

- **`app/main.py`**: Entry point exposing `GET /health` and `POST /turn`. Orchestrates request lifecycle: validate -> load session -> invoke graph -> save session -> emit structured log -> return response.
- **`app/contracts.py`**: Strict Pydantic models for HTTP requests and responses. Validates against empty/whitespace fields.
- **`app/graph.py`**: Minimal compiled LangGraph `StateGraph` containing a single `process_turn` node and typed `ConversationState`.
- **`app/firestore.py`**: Async Firestore session repository managing minimal `SessionData` persistence.
- **`app/gemini.py`**: Async Google GenAI SDK boundary managing process-level `genai.Client` lifecycle and Vertex AI calls with ADC authentication.
- **`app/logging.py`**: Structured JSON formatter with built-in PII redaction suitable for Google Cloud Logging.
- **`app/config.py`**: Environment configuration via Pydantic `BaseSettings`.
