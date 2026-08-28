---
name: cu013-testing
description: Operates and maintains test suites, test doubles, linting, and typecheck gates.
---

# cu013-testing

## Responsibility
Ensure fast, hermetic, and high-coverage automated unit, contract, and persistence tests across all system boundaries, enforcing the layered testing and evaluation hierarchy.

## Layered Testing & Evaluation Hierarchy

1. **Unit & Integration Tests (Deterministic)**:
   - Test application code, HTTP contracts, LangGraph execution, and session persistence using deterministic test doubles.
   - Prefer `httpx.AsyncClient + ASGITransport` for incoming XCALLY → FastAPI contracts without running a live server.
   - Reserve `respx`/`MockTransport` for outbound HTTP when external APIs exist.
   - Backend tests explicitly **do not test ASR or TTS** (that responsibility belongs to live voice validation).
   - An LLM test double represents a known structured output and **must never simulate Spanish NLU** via keywords, regex, or synonym maps.
   - Assertions must verify behavioral outcomes and contract invariants, not literal generated wording (unless contractual).
   - Every test must answer a clear functional question; never add tests solely for coverage metrics.
   - Standard `pytest` must run hermetically without cloud credentials or network access.

2. **Golden Evals (Real Gemini)**:
   - Test semantic intelligence, multi-turn context retention, and reasoning using real Gemini calls.
   - Run as a controlled, opt-in gate separate from standard `pytest`.

3. **Live Telephony Voice Validation (XCALLY / DEV)**:
   - Validates live audio UX, latency (ASR + Backend + TTS), turn-taking, and telephony signaling.
   - Cannot be replaced by automated unit or eval suites.
   - *None of these three testing layers replaces the others.*

## Turn & Model Budget Rules
- **Normal Turn**: Exactly 1 async Gemini request.
- **Sequential Calls**: `>2` sequential model calls in a turn require **STOP & REPORT**.

## Terminal & Environment Execution
- Run test and quality commands using the dedicated project virtual environment (e.g. `C:\Users\Pedro Lopevia\Escritorio\cu013-agente-xcally\.venv\Scripts\...` or active `.venv`).

## Allowed Changes
- Adding focused unit tests for new contracts, state transitions, or bug fixes.
- Enhancing hermetic test doubles for Firestore or Vertex AI.
- Adding controlled, opt-in golden eval scripts.
- Refining Ruff and MyPy configurations.

## Forbidden Changes
- Requiring live cloud credentials or network connections to pass `pytest`.
- Simulating Spanish NLU in test fakes via regex/keywords.
- Using `ignore_errors = true` globally in MyPy.
- Disabling Ruff lint rules globally to silence simple errors.
- Committing tests that depend on execution order or shared state.

## Inputs / Contracts
- `tests/` directory, `pyproject.toml` test configuration.

## Outputs / Contracts
- Clean green test suites and type/lint reports.

## Trusted References
- [tests/conftest.py](../../tests/conftest.py)
- [pyproject.toml](../../pyproject.toml)
- [docs/DEVELOPMENT_RULES.md](../../docs/DEVELOPMENT_RULES.md)

## Quality Checks
- `pytest tests/ -v`
- `ruff check app tests`
- `mypy app`

## STOP Conditions
- Test suite fails or exhibits non-deterministic flakiness.
- Normal turn exceeds 1 model call or sequential calls exceed 2.
