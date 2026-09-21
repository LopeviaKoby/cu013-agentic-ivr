---
name: xcally-call-evidence-analysis
description: Analyze the evidence of a real XCALLY call the owner already executed and supplied. Correlates caller observation, XCALLY capture, conversation_id/UNIQUEID, turn_id, request/trace id, Cloud Run logs, semantic state, route, ASR and TTS timing. Interactive analysis only; never places calls, listens in background, captures logs automatically or monitors telephony.
compatibility: opencode
metadata:
  project: cu013
  workflow: xcally-call-evidence-analysis
---

# XCALLY Call Evidence Analysis

Post-hoc analysis procedure for one real XCALLY call whose evidence the owner
already produced. The analysis explains what happened on the real voice
channel; it never produces the call itself.

## What this skill is not

- It does not place, schedule or simulate calls.
- It does not listen in the background, capture logs automatically, poll
  telephony or monitor a live channel.
- It does not replace `conversation-evaluation`: real-model evals measure the
  agent against the corpus; this skill explains one real call.

## When to use (trigger)

The owner has already executed or identified a real XCALLY call and has
supplied its evidence or pointed to where it lives:

- an XCALLY capture, transcript excerpt or flow response;
- a Cloud Run / Cloud Logging window, request id or trace;
- a `conversation_id`/`UNIQUEID` and optionally a `turn_id`;
- a caller observation (what the caller heard, said or experienced).

Not for exploratory "can we hear something" work and not for calls that were
never made.

## Required inputs

- The caller observation, sanitized (no PII, no raw DTMF, no full
  transcript): what the caller said, what the assistant sounded like, what
  the caller expected.
- The XCALLY evidence: capture entries, flow responses, local time window.
- The correlation identifiers available for that call:
  `conversation_id`/`UNIQUEID`, `turn_id`, request id, `x-cloud-trace-context`.
- Read-only access to the applicable Cloud Logging window and to the durable
  semantic state when the owner has authorized it.

## Procedure

1. **Fix the window and the identifiers.** Record the call's local time and
   the UTC window, `conversation_id`/`UNIQUEID`, `turn_id` and any request
   id or trace available. State explicitly which identifiers are missing.
2. **Confirm the served revision.** Read-only: which Cloud Run revision
   served the window, its image tag/digest and the commit it corresponds to.
   A finding against an unknown revision is not evidence.
3. **Correlate the layers**, keeping every hop separate:
   caller observation → XCALLY capture → boundary request (id, status) →
   Cloud Run logs (`turn_metric` segments, route when present) → semantic
   state (identity authorization, plan, confirmation challenge, dispatch,
   external operation) → response route → ASR timing (when available) →
   TTS timing / first useful audio (when available).
4. **Reconstruct the semantic turn.** Using the correlated state and the
   route, explain what the runtime decided and why. Distinguish the model's
   proposal from the runtime's emitted route; the runtime keeps the last
   word on legality and state.
5. **Classify every finding** as `OBSERVED` (directly present in the
   evidence), `DERIVED` (computed from observed values, with the derivation
   stated) or `NOT AVAILABLE` (the channel or identifier does not provide
   it). Never promote a DERIVED or missing value into OBSERVED.
6. **Compare against the corpus property** the call was exercising, when
   one applies. A mismatch is a corpus or policy finding; it is never
   reinterpreted as a pass.
7. **Record.** Sanitized evidence only, with the correlation chain and the
   classification of each measurement, in an experiment record or iteration
   notes. No PII, no raw DTMF, no full transcripts in any stored artifact.

## Required evidence to report

- Served revision verification (revision, tag/digest, traffic).
- Correlation chain per hop, with the window and identifiers used.
- Per-measurement classification: OBSERVED, DERIVED, NOT AVAILABLE.
- Observed route and semantic state, separated from what was expected.
- Timing where available: ASR endpointing, backend segments, TTS/first
  useful audio, each classified.
- Open correlation gaps (for example a missing per-turn identifier) pointed
  at `docs/gaps.md` instead of being papered over.

## STOP conditions

- No real call exists or the evidence is not attributable to one call.
- The served revision cannot be confirmed.
- The window is ambiguous and the correlation chain cannot be defended.
- The analysis would require inventing an XML/AD/Cally Square contract that
  has not been observed.
- A finding contradicts a SPEC invariant: stop and report before drawing
  conclusions.

## Outputs

- A sanitized call-evidence analysis in an experiment or iteration record.
- Findings classified OBSERVED / DERIVED / NOT AVAILABLE.
- New or updated gaps in `docs/gaps.md` when evidence contradicts
  expectations.
- Input for the iteration closeout (`iteration-closeout` skill).

## What this skill must NOT decide

- XCALLY/Cally Square XML, AD/TIVIT payloads or event contracts (evidence
  authority; gaps XC-001..XC-006 govern their discovery).
- Product semantics or handoff causes (SPEC authority).
- Whether a change ships: that requires the conversation-evaluation gate and
  explicit deploy authorization first.
