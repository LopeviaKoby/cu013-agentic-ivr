# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Add the `next-step-v1` pre-turn bootstrap: a valid v1 voice failure may
  create the minimal session through a create-only precondition (never
  overwriting a concurrent record) and advances a durable consecutive
  voice-retry counter. No other first event creates a document, legacy gains
  no bootstrap, and a valid persisted turn preserves the technical planes
  while resetting the counter.
- Add typed rejection reasons (`unknown_session`,
  `pre_turn_event_not_allowed`, `operation_missing`, `operation_mismatch`,
  `action_mismatch`, `dispatch_mismatch`, `revision_mismatch`,
  `illegal_transition`, `poll_sequence_conflict`,
  `password_presentation_conflict`) and a `(location, type)` projection of
  validation failures; the public error taxonomy and responses are
  unchanged.
- Add the shared `cu013` logging topology with one stderr handler and closed
  events (`response_contract_selected`, `turn_handled`,
  `integration_event_received`/`accepted`/`rejected`, `http_result`,
  `request_validation_failed`); baseline INFO carries no conversation, turn,
  operation, trace or request identifiers, no paths and no payload values.
- Add `load_existing` and `create_if_absent` to the thin session repository,
  with the Firestore create-only precondition and a deterministic double.

- Add the `next-step-v1` response contract: an explicit
  `CU013-Response-Contract` selector, a common
  `{message, next_step, operation_state, command}` envelope on both
  endpoints, a safe 400 `unsupported_response_contract` for empty, repeated
  or unknown versions, an unchanged legacy envelope without the header, and
  one domain transition feeding both temporary serializers.
- Add post-identity continuity: `IDENTITY_VALIDATION_RESULT/VALID` keeps the
  goal and its revision, replaces any previous challenge with one bound to
  the current action, revision and identity, and answers with the
  action-specific confirmation without a second model call.
- Add strict poll sequencing, SHA-256 fingerprint dedupe and a
  nine-observation budget to `next-step-v1`: exact replays are idempotent
  ACKs that consume no budget, jumps and mismatches are safe 409s, a
  dispatch error consumes no GET budget, and exhaustion answers `TRANSFER`
  without turning `PENDING`/`UNKNOWN` into `FAILED` and without re-POST.
- Add `IDENTITY_INPUT_FAILURE/CAPTURE_EXHAUSTED` (no attempt, no operation
  change, `TRANSFER`) and `PASSWORD_PRESENTATION_RESULT`
  (`DELIVER_PASSWORD` only for a confirmed reset without presentation,
  idempotent duplicate ACK, safe 409 for incompatible or late events, no
  delivery claim while `UNKNOWN`).
- Add the narrow polling feedback composer: closed PII-safe input, a
  message-only output that can never decide `next_step`, authorize or touch
  identity, validated and bounded to two persisted messages, silence with
  intact business state on timeout or inadmissible text, no fixed rotation
  and no second model call.
- Add `SessionRecord` v3 with separate `polling` and
  `password_presentation` planes and a fail-closed v1/v2 migration.
- Add whitespace normalization for the v1 envelope: CR/LF/tab collapse to a
  space while Unicode, apostrophes, ASCII quotes and backslash are
  preserved; passwords, documents and dates are never normalized.
- Add the deterministic next-step test suite: selector and envelope
  contract, poll sequence/dedupe/budget, capture exhaustion, password
  presentation, composer cadence and silence, PII canaries and prompt
  wording guard.

- Add the technical XCALLY ↔ CU013 account-action contract: `/turns` emits
  `EXECUTE_ACTION` with an opaque `command` only after the durable dispatch
  guard, and `/integration-events` carries the closed PII-safe event union
  (`IDENTITY_VALIDATION_RESULT`, `VOICE_INPUT_FAILURE`,
  `ACCOUNT_ACTION_STATUS`, `ACCOUNT_ACTION_ERROR`) with a flat
  `{acknowledged, operation_state, directive, message}` response. The
  external action command stays CU013-owned and never carries document,
  date, password, RD credentials or payloads.
- Add deterministic anti-silence progress for pending operations: a single
  runtime-owned message cadence with no model call per poll, idempotent
  `NONE`, safe terminal wording and no ungrounded claims.
- Add PII-safe identity handling separated from DTMF: raw identity was
  removed from the active turn contract, identity outcomes travel as local
  `VALID`/`INVALID`/`TECHNICAL_FAILURE`, and XCALLY maps its own lookup
  (`GET /validauser/TIVIT/{DOCUMENTO}` with `FOUND`/`NOT_FOUND`) plus the
  entry-date comparison against `resposta2` before calling CU013. `FOUND`
  does not equal a validated identity. Full E2E evidence is still pending.
- Reconcile repository readiness and the evaluation harness: experimental
  short aliases are removed from active code/tests/docs and blocked by the
  readiness gate, the confirmation-affirmative oracle matches the accepted
  one-active-operation authority, and the harness computes worktree
  identity with explicit UTF-8 decoding.
- Select the active synthetic conversational baseline: Gemini 3.5
  Flash-Lite on Vertex AI (`global`, `MINIMAL`, structured output,
  mandatory procedure classification, three-pair recent memory) with
  ADR-0011. Synthetic scope only; not voice-validated and not
  production-accepted.
- Add the agent evaluation lab: `evals/conversation_lab.py` (shared pure
  schema, oracles, fingerprints, statistics and sanitization),
  `evals/conversation_eval.py` (real-model runner with explicit
  `independent_trial` / `sequence` trial kinds, null-as-absence oracle
  semantics, clean/absent-field `NOT ORACLED` reporting, sanitized run /
  case / repetition / turn evidence, fixed warmups excluded from verdicts,
  repetition-level INFRA, invalid structured output as model failure,
  focused-rerun scope metadata, deterministic variant fingerprint and
  Git-ignored artifacts under `evals/results/`) and
  `evals/conversation_compare.py` (pure paired comparator with a hard
  critical-violation gate, semantic and efficiency gates, INFRA separation,
  rerun merging that never erases original evidence, and a manual
  spoken-quality review template with MEETS / CONCERN / NOT EVIDENCED).
- Add the owner-authorized local conversational baseline reference at
  `21896d12e04da173eda5b0fb4949ac5841812fdd` with synthetic scope and the
  Experiment 0006 evidence reference; not voice-validated and not
  production-accepted.
- Add the deterministic lab test suite `tests/evals/` covering fresh
  independent paraphrases, sequence retention, per-repetition verdicts,
  `NOT ORACLED` / `NOT REPRESENTABLE` properties, null-as-absence,
  repetition-level INFRA, invalid output as model failure, focused-rerun
  merging, comparator acceptance logic, missing token usage and evidence
  sanitization.
- Add the credential-free GitHub Actions workflow
  `.github/workflows/ci.yml` (corpus validation, pytest, Ruff and MyPy; no
  ADC, no secrets, no cloud mutation).
- Add Experiment 0007 documenting the lab, the harness-validation real-model
  run against the accepted baseline and the defects it surfaced.
- Materialize the accepted product policy in the specs: transversal
  conversational invariants (durable semantic plan, goal/identity/
  confirmation/dispatch/operation separation, 30-minute identity TTL, HITL
  verbal confirmation with timeout/re-prompt semantics), first-slice behavior
  (three caller identity failures, handoff causes, no sensitivity-based
  escalation, SendMail-gated reset, IOP-MDA-012 Firestore exception) and the
  voice-confirmation policy note in the XCALLY boundary spec.
- Add ADR-0010: durable semantic plan separated from authorization,
  confirmation and external-operation truth, with durable guard before side
  effects, one active operation per conversation and UNKNOWN after uncertain
  dispatch.
- Add the eval-driven testing methodology (real failure → corpus case →
  general property → smallest layer → deterministic tests → real-model eval →
  DEV voice validation) and the confirmation/operation reliability
  invariants.
- Add the versioned PII-free conversation eval corpus
  (`evals/conversation/cases.yaml`, 34 cases, 30 families, including the
  Experiment 0005 provenance case with paraphrases and opposite controls and
  the owner-decision cases for unsupported requests, human requests, goal
  cancellation, technical identity failure and side questions) and the manual
  runtime semantic runner `evals/conversation_baseline_eval.py` (renamed to
  `evals/conversation_eval.py` by the evaluation-lab iteration): PASS / FAIL /
  NOT ORACLED / NOT REPRESENTABLE / INFRA per case and family, `UNSPECIFIED`
  route and `not_valid`/`not_oracled` confirmation semantics, model/runtime/
  turn latency percentiles, prompt/completion tokens and accumulated tokens
  for multi-turn cases, plus `--validate-only` static corpus validation with
  no model or ADC.
- Add the durable semantic runtime (schema v2) materializing ADR-0010:
  conversational plan, identity authorization with absolute 30-minute TTL,
  per-operation confirmation challenge, durable dispatch guard and external
  operation truth in separate planes, with a fail-closed v1→v2 migration and
  deterministic legality guards (no dispatch without a valid identity and a
  matching challenge, one active external operation, UNKNOWN never
  redispatched, model claims never create business truth).
- Add the deterministic legality suite for the semantic runtime and the
  owner-decision controls (unsupported request never a handoff cause, explicit
  human request preserving the goal, no challenge from a side question,
  invalidated challenge replaced by a new one).
- Add the `conversation-evaluation` and `xcally-voice-validation` agent skills
  and the mandatory skill matrix to `AGENTS.md`.
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

- Rename the response-contract selector to the canonical
  `X-CU013-Response-Contract`; the name without `X-` is no longer read and is
  not kept as an alias because it had no accredited real consumer. A real
  call had been served the legacy envelope while the XCALLY switch expected
  `next_step` (`HEADER_MISMATCH`), and its default branch transferred.
- Derive `next_step` from the consolidated state instead of only the model
  proposal: with a supported goal pending, no valid identity and no active
  operation, the residual `CONTINUE` route projects onto `COLLECT_IDENTITY`
  while the model message still answers the immediate need.
- Bump the durable contract to v4 with `voice_retry_count` and a fail-closed
  v3 to v4 migration; a valid turn preserves `polling` and
  `password_presentation` instead of rebuilding the record partially.
- Move the runtime outcome vocabulary to `NextStep`: the domain speaks the
  canonical step, the legacy adapter projects it onto `BoundaryRoute` and
  `IntegrationDirective`, and no domain logic consumes the legacy enums.
- Change the active prompt wording from fecha de nacimiento to fecha de
  ingreso with a deterministic guard test; the decision schema, model and
  model selection are unchanged.
- Scale conversational validation by risk in the testing standard and the
  `conversation-evaluation` skill: deterministic/unit/contract/replay, then
  targeted live smoke, and full paired evaluation only when decision
  semantics change.
- Reconcile the boundary, account-action, system, reliability and testing
  specifications and Experiment 0010 with the `next-step-v1` candidate, its
  open E2E questions and the v3 durable contract.

- Rename the XCALLY skill to `xcally-call-evidence-analysis`: it analyzes the
  evidence of a real call the owner already executed and supplied and never
  places calls, monitors telephony or captures logs automatically.
- Extend `conversation-evaluation` with the paired candidate procedure
  against the accepted baseline (memory and tool-choice behavior included)
  and the pre-voice gate checklist.
- Define the three validation layers and the pre-voice gate in the testing
  standard; update README and AGENTS entry points, the mandatory skill matrix
  and the `.gitignore` skill whitelist.
- Extend the corpus with explicit `scenario_kind`, `handoff_cause` oracles,
  per-turn checkpoints for sequences and the `long-conversation-memory`
  intentional sequence (35 cases / 31 families).
- Reduce `AGENTS.md` to workflow/authority/matrix and point product rules to
  the specs.
- Move the system prompt out of `GeminiTurnModel` into the dedicated prompt
  module; the Gemini adapter keeps only baseline config, transport, parsing and
  error mapping, with no model, schema, thinking-budget or call-count change.
- State the owner decisions as general prompt properties: scope redirection
  without handoff for unsupported or out-of-scope requests, explicit human
  request without cancelling the goal, side questions that never start or
  restart the confirmation, and confirmation-answer classification that only
  treats abandoning the whole goal as `CANCEL`.
- Close the handoff causes to caller request and terminal failure
  (`HandoffCause` no longer offers an unsupported-operation cause), and
  reconcile the specs: unsupported requests never imply handoff, the goal is
  only cancelled on explicit request, and an invalidated challenge is never
  reused.
- Stamp a brand-new session record with the injected turn clock instead of the
  wall clock, keeping `created_at <= updated_at` deterministic.
- Fix the corpus runner token accounting (prompt/completion/total were summed
  together) and update the focused policy probe to the v2 decision contract.
- Document the semantic runtime candidate in Experiment 0006 and resolve
  `CNV-001`.
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
- Reconcile the active runtime to the selected profile (model, `global`
  location separate from `us-east1` infrastructure, `MINIMAL` without
  budget, required procedure schema, single prompt text) and the harness
  (content-hashed worktree identity, null budget with level, model
  location, comparator and gate identity).
- Remove the discarded multi-provider benchmark lane from the active
  runtime (endpoint, adapter, deploy script and exclusive tests) after
  archiving source hashes and methodology; the historic scorer stays as
  evidence only.

### Removed

- Remove discarded compact-prompt and confirmation-request variants from
  the active prompt/schema path; evidence remains in Experiment 0009.
