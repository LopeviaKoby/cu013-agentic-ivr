---
name: conversation-evaluation
description: Mandatory eval-driven procedure for any CU013 change to prompt, conversational schema, conversational policy or model. Compares semantics against the versioned corpus instead of patching individual utterances.
compatibility: opencode
metadata:
  project: cu013
  workflow: conversation-evaluation
---

# Conversation Evaluation

Eval-driven change procedure for the CU013 conversational backend. It prevents
patch-driven prompting: individual failures become corpus cases, and only a
demonstrated missing or incorrect general property changes prompt, policy,
schema or model.

## When to use (trigger)

Mandatory before accepting any change to:

- the system prompt (`app/conversation/prompts.py`) or any prompt text sent to
  the model;
- the conversational schema (model decision fields, routes, durable
  conversational state);
- conversational policy (routing rules, confirmation rules, escalation rules);
- the model or provider (baseline swap, thinking budget, model version).

Not for pure runtime refactors with no behavioral surface, or for
infrastructure changes.

## Required inputs

- The observed failure or the proposed change, with sanitized evidence
  (no PII, no raw DTMF, no real transcripts).
- The versioned corpus: `evals/conversation/cases.yaml` and its README.
- The applicable SPEC sections ([system](../../../docs/specs/system.md),
  [account-actions](../../../docs/specs/account-actions.md)).
- The current baseline runner: `evals/conversation_baseline_eval.py`.

## Procedure

1. **Register the case.** Add the failure or behavior as one or more corpus
   cases with paraphrases and opposite (positive/negative) controls. No
   phrase-matching expectations.
2. **Reproduce.** Run the baseline runner against the corpus with the current
   model and record the observed routes and semantic fields.
3. **Identify the general property.** State the missing or incorrect general
   property in terms of observable behavior (route, goal, confirmation,
   eligibility, claims), not wording.
4. **Change the smallest correct layer.** Prompt, policy, schema or runtime —
   whichever the evidence supports; never more than one layer without
   justification.
5. **Deterministic tests.** Encode the property in deterministic tests that
   run without the model.
6. **Real-model eval.** Re-run the runner over the affected families plus
   their controls; multiple paraphrases per property; a single repeated
   utterance is not generalization evidence.
7. **Report.** Summarize per family: route matches, semantic proposal fields,
   latency, and any `NOT REPRESENTABLE IN CURRENT CONTRACT` checks.

## Required evidence

- Corpus diff showing the added cases and controls before the fix.
- Baseline runner output before and after the change (same corpus version).
- Deterministic test results (`python -m pytest`).
- Per-family comparison with no critical regressions; if a field cannot be
  expressed by the current contract, it must be reported as
  `NOT REPRESENTABLE IN CURRENT CONTRACT`, not approximated.

## STOP conditions

- The change requires semantics not authorized by the SPECs or an Accepted
  ADR.
- Evidence only supports an individual utterance fix with no general property.
- The real-model eval shows a regression in another family and the property
  cannot be corrected without a policy decision.
- The change would require more than two sequential model calls in a normal
  turn.
- Required XCALLY behavior is unknown (route contract, ASR/TTS behavior).

## Outputs

- Corpus cases added or updated.
- Runner before/after results per family.
- Layer changed (prompt/policy/schema/runtime) with the property it restores.
- Deterministic tests added.
- Open follow-ups (e.g., voice validation) recorded in `docs/gaps.md` or the
  iteration notes.

## What this skill must NOT decide

- New product semantics, handoff causes or confirmation rules (SPEC
  authority).
- XCALLY/AD contracts or payload shapes (evidence authority).
- Model selection or provider changes (owner decision; this skill only
  measures).
- Whether the change ships: acceptance requires DEV voice validation through
  the `xcally-voice-validation` skill when spoken behavior is affected.
