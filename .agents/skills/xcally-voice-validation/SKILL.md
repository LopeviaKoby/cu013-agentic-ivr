---
name: xcally-voice-validation
description: Mandatory DEV voice-call validation procedure for accepted CU013 changes that affect routing, spoken responses, ASR/TTS behavior, timing or handoff. Gathers correlated caller evidence; never invents XCALLY/AD contracts.
compatibility: opencode
metadata:
  project: cu013
  workflow: xcally-voice-validation
---

# XCALLY Voice Validation

DEV voice validation gate for accepted conversational changes. Local tests and
real-model evals never substitute real ASR/TTS and a real call.

## When to use (trigger)

Mandatory when an accepted change affects:

- routing behavior (any `route` transition the caller can observe);
- spoken response behavior (wording the caller hears, message content policy);
- ASR/TTS behavior (capture windows, confidence handling, synthesis);
- timing (anything in the `end-of-speech → first useful audio` path);
- handoff (escalation causes or flow).

Not for changes that provably never reach the spoken path (e.g., internal
tooling, docs-only iterations).

## Required inputs

- The accepted change and the corpus cases that justify it
  (`evals/conversation/`, per the `conversation-evaluation` skill).
- A deployed DEV revision containing the change (deploy requires explicit
  owner authorization; the deployed revision must equal the inspected HEAD).
- XCALLY/Cally Square DEV flow able to place real calls to the boundary.
- Read-only access to Cloud Logging for the PII-safe correlation window.

## Procedure

1. **Confirm the served revision.** Verify read-only that the Cloud Run
   revision serving traffic corresponds to the accepted commit (tag == HEAD).
2. **Define observable properties.** Before calling, write down the expected
   observable properties per case: route, spoken behavior class, timing
   budget, and forbidden claims.
3. **Run DEV calls.** Place real voice calls through XCALLY exercising the
   changed properties and their opposite controls.
4. **Correlate evidence.** Within a narrow time window, collect the XCALLY
   capture and the Cloud Logging `turn_metric` lines; attribute requests
   without assuming per-turn identifiers (see gap XC-002).
5. **Measure.** Record OBSERVED values, DERIVED values, and explicitly list
   NOT AVAILABLE measurements (e.g., first useful audio) without inventing
   them.
6. **Compare.** Check the observed behavior against the expected properties
   and the corpus expectations; do not reinterpret failures as passes.
7. **Record.** Store the evidence in an experiment record or iteration notes
   with sanitized (PII-free) artifacts only.

## Required evidence

- Served revision verification (revision, tag/digest, traffic).
- Per-call correlation: conversation/turn identifiers, window, HTTP status.
- Observed vs expected per property, including controls.
- Timing measurements where available, explicitly marked OBSERVED, DERIVED or
  NOT AVAILABLE.
- No PII, no raw DTMF, no full transcripts in any stored artifact.

## STOP conditions

- The served revision does not contain the accepted change.
- The XCALLY/Cally Square flow required to exercise the change does not exist
  or cannot be authorized.
- The evidence cannot be correlated to specific calls (window ambiguity).
- The observed behavior contradicts a SPEC invariant (STOP before accepting).
- Validation would require inventing an XML/AD/Cally Square contract that has
  not been observed.

## Outputs

- Voice validation evidence record (experiment or iteration notes).
- Pass/fail per observable property, with controls.
- New or updated gaps in `docs/gaps.md` when evidence contradicts expectations.
- Input for the iteration closeout (`iteration-closeout` skill).

## What this skill must NOT decide

- XCALLY/Cally Square XML, AD/TIVIT payloads or event contracts (evidence
  authority; gaps XC-001..XC-006 govern their discovery).
- Product semantics or handoff causes (SPEC authority).
- Whether an unvalidated change may ship (this skill is the gate that says
  when validation is still missing).
