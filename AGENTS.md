# CU013 Agentic IVR — Operational Constitution

This document defines the binding operational and architectural rules for the `cu013-agentic-IVR` repository.

## IMMUTABLE BASELINE

- XCALLY Motion + Cally Square are immutable.
- This is a conversational agent, not a spoken form.
- The repository is brand new; legacy code is not architecture.
- Gemini owns natural-language conversational behavior.
- Runtime owns business legality and truth.
- Firestore is the durable session store.
- LangGraph is the orchestration framework; use only required features.
- No keyword/regex semantic routing.
- Tools represent external capabilities, never internal state mutation.
- Normal turns target one model request.
- >2 sequential model requests require STOP & REPORT.
- No large conversational FSM.
- No new infrastructure without demonstrated benefit and approval.
- Accepted conversational changes require DEV voice validation.
- Accepted changes must be committed before the next iteration.
- Normal Git workflow uses dev and main only.

## Source Precedence

When resolving architectural, technical, or behavioral questions, adhere strictly to this precedence hierarchy:

1. **Actual live-call behavior** (telephony observations, real caller interactions)
2. **Runtime logs** (structured Cloud Logging traces, latency metrics)
3. **Source-code contracts** (FastAPI endpoints, Pydantic schemas, LangGraph state)
4. **Version-matched official documentation** (Google GenAI SDK, LangGraph, Firestore)
5. **Official general documentation** (GCP, Python 3.12, FastAPI)
6. **Engineering case studies** (benchmarks, postmortems)
7. **Inference** (hypotheses must be validated against higher levels)

## Engineering & Architectural Principles

### Separation of Concerns
- **LLM Responsibility**: Natural language comprehension, multi-fact extraction, contextual clarifications, handling caller corrections, formulating conversational explanations, steering multi-turn dialogue.
- **Runtime Responsibility**: Business invariant enforcement, tool authorization, external side-effects, session persistence, latency boundaries, security and PII redaction.

### Minimalism & Anti-Abstraction Rules
- Before adding any file, class, interface, dependency, state field, graph node, or abstraction layer, ask: *What concrete failure does this solve?*
- Do not add speculative layers (e.g., Manager, Resolver, Strategy, Factory, Registry, Coordinator, Ports/Adapters) when a simple function or flat module is sufficient.
- Keep the module hierarchy shallow and explicit.

### Model Call Budget
- **Target**: Exactly 1 async Gemini request per normal conversational turn.
- **Hard Limit**: If an interaction requires >2 sequential model calls within a single turn, the system must **STOP & REPORT**.

### Logging & Observability
- All logs must be structured JSON, PII-safe, and compatible with Google Cloud Logging.
- Never log raw credentials, full caller transcripts, passwords, tokens, or unredacted personal data.
- Capture: `conversation_id`, `turn_id`, `route`, `latency_ms`, `model_call_count`, `error_class`.

## STOP & REPORT Rules

Halt execution and report immediately before creating speculative solutions if you encounter:
- Unknown XCALLY / telephony behavior required for implementation.
- Ambiguous business rule required for current code.
- Unknown external API contract.
- Need for a new framework, database, vector store, or RAG infrastructure.
- Need for a secondary LLM provider.
- >2 sequential model calls in a turn.
- Need for a large conversational FSM.
- Need for new IAM roles, Service Accounts, or Artifact Registry repositories.
- Need to modify Spanner schema or migrate GCP regions.
- Conflict with the `IMMUTABLE BASELINE`.

## Acceptance & Quality Gates

Every code iteration must pass:
1. `ruff check app tests` (no lint errors)
2. `ruff format --check app tests` (consistent formatting)
3. `mypy app` (strict type check, no global ignores)
4. `pytest tests/` (focused unit tests passing)
5. `docker build` (clean non-root container image build)
6. Real voice validation on DEV before conversational behavior changes are merged.

## Git Rules

- Work on `dev`.
- `main` tracks accepted releases.
- Never commit broken tests, failed lints, or untyped code.
- Commit clean, validated increments with descriptive messages.
