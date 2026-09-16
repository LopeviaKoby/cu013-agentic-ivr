# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Add the versioned system prompt module `app/conversation/prompts.py` with the
  prior-request policy: when the caller prepends an explicit question or
  informational request to an action, the assistant answers it briefly with
  `CONTINUE` and does not start identity collection.
- Add deterministic policy tests, a boundary regression that keeps a pre-auth
  action intent transient, the manual real-model probe
  `evals/conversation_policy_eval.py` and Experiment 0005 diagnosing the real
  XCALLY voice turn.
- Minimal productive Thin Session Repository core in `app/session`: semantic
  whitelisted `SessionRecord`, durable `pending_operation`, ephemeral
  `GraphState`, a deterministic single-node LangGraph turn without persistent
  checkpointer, an async Firestore repository with a narrow document seam and a
  turn service with exactly one load and one save.
- Deterministic test suite for the session core, including continuity,
  crash-before-save recovery, durable pending operation, PII and whitelist
  exclusion and async repository behavior.
- `requirements.lock` with the exact reproducible production pins, verified in
  a clean environment and reviewed against current OSV advisories.
- GCP DEV/SPIKE baseline in `us-east1`.
- Firestore `(default)` in Native mode, Standard edition.
- Artifact Registry DEV repository.
- Dedicated spike, runtime and deployer service accounts.
- Reproducible GCP bootstrap and verification runbook and PowerShell scripts.
- Versioned non-sensitive `config.yaml`.
- Versioned source manifest for local corporate IOPs.
- Engineering standards for Python, reliability and testing.
- Add the CU013 iteration-closeout agent skill.
- Add the provisional DEV FastAPI boundary baseline for Cally Square at
  `POST /api/v1/conversations/{conversation_id}/turns`, with typed ASR
  transcript and `IDENTITY_DATA` variants, environment-only `X-API-Key`
  authentication, a per-request `turn_id` and a safe error taxonomy.
- Add the minimal `ConversationEngine` seam for the next Gemini iteration; no
  deterministic conversational logic is implemented.
- Add the deterministic boundary test suite: contract closure, authentication,
  DTMF containment, sanitized validation errors, session identity, turn ids
  and safe dependency/internal errors.
- Add the real Gemini 2.5 Flash-Lite engine (`GeminiTurnModel`) behind the
  `ConversationEngine` seam: Vertex AI over ADC, typed structured output,
  `thinking_budget=0`, one call and one attempt per normal turn, no streaming
  and no tools.
- Add the PII-safe `TurnMetrics` seam with fixed segment names and token
  counters, and the DEV backend latency benchmark in
  `evals/backend_latency.py` (5 warmups, 30 sequential measured requests
  through the real boundary).
- Add the minimal production container (Python 3.12 slim, single uvicorn
  process with factory entrypoint, non-root, runtime-only install constrained
  by the lock) and `uvicorn` as the runtime HTTP dependency with a regenerated
  lock and clean OSV review.
- Add the Cloud Run DEV benchmark tooling: idempotent deploy, stop and
  read-only verify scripts, the HTTPS E2E client that reads `CU013_API_KEY`
  from the environment only, and the operations runbook.

### Changed

- Move the system prompt out of `GeminiTurnModel` into the dedicated prompt
  module; the Gemini adapter keeps only baseline config, transport, parsing and
  error mapping, with no model, schema, thinking-budget or call-count change.
- Replace the transitional `packages = []` packaging with explicit `app`
  package discovery; editable DEV install verified.
- Raise dev tooling to advisory-free floors: `pytest>=9.0.3` and
  `pytest-asyncio>=1.4.0`.
- Remove the experimental Firestore spike documents (111 documents) under the
  documented `cu013spike_meas_*` prefixes.
- Adopt Thin Firestore Session Repository for durable voice-session state.
- Contain raw DTMF at the HTTP boundary: accepted only in the transient
  `IDENTITY_DATA` model and never persisted, logged, echoed or forwarded to
  the conversational seam; receiving DTMF never marks a validated identity.
- Route model failures to the error taxonomy: `dependency_timeout` (504) and
  `dependency_unavailable` (503); invalid structured model output stays a
  safe `internal` error.
- Document the measured DEV backend baseline in Experiment 0003 and
  re-evaluate FS-002: it remains open; SDK defaults are not productive
  policy and in-region Cloud Run plus ASR/TTS/XCALLY segments are the
  missing evidence.
- Document the Cloud Run warm baseline in Experiment 0004: 30/30 measured
  requests through the real HTTPS boundary on revision `00006-hn4`, roughly
  half the local latency at p50/p95, service returned to `min=0`.
- Document the provisional XCALLY conversational boundary baseline and
  reconcile XC-001, FS-002 and the new identity-validation gap.
- Reject persistent LangGraph checkpointing for the production voice path.
- Raise the LangGraph security floor to `langgraph>=1.0.10` and
  `langgraph-checkpoint>=4.1.1`; defer the exact production lock to the first
  minimal production implementation.

- Documented reproducible `gcloud` bootstrap before Terraform.
- Resolved the infrastructure blocker for Firestore persistence.
- Moved the deadline for evaluating a Gemini alternative to 16-10-2026.
- Clarified business-authority precedence, account-action paths, experiment retention and the documentation lifecycle.
- Clarified the automated account-action and ticketing boundary.
