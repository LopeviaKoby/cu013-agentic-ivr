# Development Rules & Workflow
 
 ## The Core Acceptance Loop
 
 ```
 Small Focused Change
   ──> Unit & Contract Tests (`pytest tests/`) [Hermetic / Deterministic Doubles]
   ──> Static Analysis (`ruff check`, `mypy app`)
   ──> Container Build (`docker build`)
   ──> Controlled Golden Evals (Real Gemini, opt-in)
   ──> Deploy to DEV Environment (when conversational behavior changes)
   ──> Live Phone Call Verification (XCALLY voice validation)
   ──> Inspect Telephony Logs
   ──> PASS
   ──> Git Commit on `dev`
 ```
 
 ## Testing & Evaluation Policy
 
 1. **Layered Verification**:
    - **Unit & Integration Tests**: Test code, HTTP contracts, LangGraph flows, and persistence with deterministic test doubles.
    - **Backend Test Scope**: Tests strictly do **not test ASR or TTS**. ASR/TTS performance is evaluated only during live telephony validation.
    - **HTTP Testing**: Use `httpx.AsyncClient + ASGITransport` for incoming XCALLY → FastAPI contracts. Reserve `respx`/`MockTransport` for outbound external APIs.
    - **LLM Test Doubles**: Fakes represent predefined structured model outputs. Fakes **never simulate Spanish NLU** using keywords, regex, or synonym maps.
    - **Behavioral Assertions**: Assert behavior, state transitions, and schemas, not literal generated natural language wording (unless contractual).
    - **Golden Evals (Real Gemini)**: Test semantic intelligence as an isolated, opt-in gate.
    - **Voice Validation (XCALLY)**: Validates real telephony audio UX and end-to-end latency.
    - *No single layer replaces another.*
 
 2. **Turn & Model Budget**:
    - **Normal Turn**: Exactly 1 async Gemini model request.
    - **Limit**: `>2` sequential model requests in a single turn require **STOP & REPORT**.
 
 3. **Hermetic Execution & Virtualenv**:
    - Standard `pytest` must run without cloud credentials or network access.
    - Execute commands in the terminal using the established project virtual environment (e.g. `C:\Users\Pedro Lopevia\Escritorio\cu013-agente-xcally\.venv` or local `.venv`).
 
 4. **Strict Typing & Linting**:
    - MyPy must pass across `app/` with no global error suppression.
    - Ruff must pass without disabling rules to bypass fixes.
 
 5. **Structured Logging**:
    - Every turn must emit a JSON log record with `conversation_id`, `turn_id`, `route`, and latency measurements.
 
 6. **No Premature Architecture**:
    - Add nodes, state fields, or abstractions only when a demonstrated failure necessitates them.

