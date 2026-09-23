---
name: conversation-evaluation
description: Mandatory eval-driven paired procedure for any CU013 change to prompt, conversational schema, conversational policy, model or memory/tool-choice behavior. Compares a candidate against the accepted baseline over the versioned corpus instead of patching individual utterances, and concludes ACCEPT / REJECT / NEEDS OWNER DECISION.
compatibility: opencode
metadata:
  project: cu013
  workflow: conversation-evaluation
---

# Conversation Evaluation

Eval-driven change procedure for the CU013 conversational backend. It prevents
patch-driven prompting: individual failures become corpus cases, and only a
demonstrated missing or incorrect general property changes prompt, policy,
schema or model. It is also the paired candidate gate: the candidate is
compared against the owner-accepted baseline with the pure comparator.

Long-conversation memory behavior and future tool-choice behavior are part of
this skill; there are no separate memory or tool skills.

## When to use (trigger)

Mandatory before accepting any change to:

- the system prompt (`app/conversation/prompts.py`) or any prompt text sent to
  the model;
- the conversational schema (model decision fields, routes, durable
  conversational state);
- conversational policy (routing rules, confirmation rules, escalation rules);
- the model or provider (baseline swap, thinking budget, model version);
- memory/continuity behavior or tool-choice behavior when a future
  capability is added.

Not for pure runtime refactors with no behavioral surface, or for
infrastructure changes.

## Risk-based validation ladder

Evidence scales with the risk of the change, never with ceremony:

1. **Deterministic (always).** Unit, contract, state-machine, fake/stub-model
   and deterministic code-evaluator tests plus offline replay/regression on
   existing sanitized artifacts. Zero real model calls. A red deterministic
   gate stops the iteration.
2. **Targeted live smoke (when the change touches language or one concrete
   model call, and level 1 is green).** A small core case set, one repetition
   per case, no LLM judge, manual review plus code evaluator, explicit bounded
   budget. A semantic failure stops the iteration.
3. **Full paired evaluation (only when decision semantics change).** Required
   for model, decision schema, tool choice, semantic routing, authorization,
   memory semantics or broad system-policy changes, and for the pre-voice gate
   of a conversational candidate.

A change verifiable by deterministic assertions and the offline corpus (for
example accepted wording such as entry-date phrasing) does not require the
full ladder by itself. A decision-semantics change is never accepted on a
smoke alone.

## Required inputs

- The baselines: the active reproducible profile is derived from
  `config.yaml` and `app/conversation`, with its full fingerprint
  calculated in runtime by the harness. Selection history lives in the
  accepted ADR, Experiment 0009 and Git; generated run outputs in
  `evals/results/` are evidence, not canonical documentation.
- The proposed candidate and its sanitized evidence (no PII, no raw DTMF, no
  real transcripts).
- The versioned corpus: `evals/conversation/cases.yaml` and its README.
- The applicable SPEC sections ([system](../../../docs/specs/system.md),
  [account-actions](../../../docs/specs/account-actions.md)).
- The evaluator `evals/conversation_eval.py`, the comparator
  `evals/conversation_compare.py` and the deterministic gates.

## Procedure

1. **Define the comparison question.** State the observable property the
   candidate is expected to change, in terms of route, goal, confirmation,
   eligibility, dispatch or claims — never wording.
2. **Identify the accepted baseline.** Use the effective profile from
   `config.yaml` and `app/conversation` with its runtime fingerprint;
   never redefine the baseline silently. Record baseline and candidate
   full identifiers.
3. **Freeze candidate/baseline dimensions.** Freeze prompt, model, schema,
   runtime, corpus and evaluator versions; declare the one variable under
   test and any accepted confounders.
4. **Select corpus families.** Run the affected families plus their controls;
   the full corpus for release-level evidence, focused families for a
   diagnosed rerun.
5. **Run deterministic gates first.** Corpus validation, deterministic tests,
   Ruff, MyPy. A red deterministic gate stops the evaluation.
6. **Run the real-model validation at the level the risk demands.** Apply the
   risk-based ladder above: targeted live smoke for narrow language changes,
   full paired evaluation when decision semantics change. For a full paired
   run, default three valid repetitions per independent trial or sequence,
   one fixed warmup for both sides, events simulated as domain events. No ADC
   means the honest verdict is "not executable", never fabricated evidence.
7. **Separate INFRA.** INFRA is classified at repetition level, valid
   repetitions are preserved and only the missing paired repetition is
   re-run; invalid structured model output is a model failure, not INFRA.
8. **Inspect per-property and per-state differences.** Compare property
   verdict distributions, route distributions, first divergent turns,
   dispatch counts and critical guard evidence; runtime-blocked unsafe
   proposals are model semantic failures, not executed violations.
9. **Inspect long-conversation memory behavior where relevant.** Use the
   intentional sequences; check goal retention, revision transitions,
   challenge absence/change and dispatch-count stability per turn.
10. **Inspect future tool-choice behavior when relevant.** When a tool
    capability exists, check selected capability, required/forbidden
    arguments, prerequisites, runtime allow/block, duplicate decisions and
    operation attribution — schemas only before the capability exists.
11. **Compare latency and tokens.** Matching case/trial/turn positions;
    model, runtime-semantic and total turn latency; prompt and completion
    tokens; missing usage stays missing. Say "faster/slower" only with
    controlled paired evidence; otherwise report provider variance as a
    confounder. Never invent an SLO.
12. **Perform the targeted spoken-quality review.** Changed/failing families
    and their controls, by case/turn ID, rated MEETS / CONCERN / NOT
    EVIDENCED for relevance, voice brevity, answer-first clarity,
    non-repetition, factual restraint, natural transition back to the active
    goal and transfer wording. No LLM judge and no wording oracle; runtime
    legality and structured business truth come first.
13. **Avoid phrase patches.** No case-specific prompt hacks, keyword lists or
    utterance matchers; a fix must restore the general property and keep the
    opposite controls passing.
14. **Conclude ACCEPT / REJECT / NEEDS OWNER DECISION.** REJECT on any new
    executed critical violation (unauthorized dispatch, duplicate side
    effect, false business result, PII/DTMF leak, invalid identity
    authorization, stale challenge reuse, illegal handoff, UNKNOWN
    redispatch). NEEDS OWNER DECISION on unresolved unrelated regressions,
    targeted regressions, incomplete paired evidence or unexplained
    efficiency deterioration. ACCEPT only with complete paired evidence, no
    new critical violations and no unexplained regressions.

## Memory/procedure candidate runs (Exp 0009, synthetic lane only)

Memory comparisons run on the repository lane with the same corpus,
runner and repetition rules, declaring `--variable memory_variant`:

- no-memory: `--lane repository --memory-variant no_recent_memory`
  (current behavior rerun).
- procedure-only: `--lane repository --memory-variant procedure_progress_only`
  (guided progress only).
- recent-memory: `--lane repository --memory-variant recent_conversation_memory`
  (progress plus the three-pair recent window; `--memory-n` stays 3 unless
  the experiment's escalation condition is met).

The comparator treats `memory_variant`/`memory_n` as prompt-explaining
when declared, since the variable changes the rendered model input by
construction; token/latency deltas are still reported. New per-turn
oracles (`procedure_current`, `procedure_last_completed`, `window_pairs`)
fail on no-memory by construction and read as targeted improvements. The
`sensitive-input-never-memory`, restart and same-session race evidence
comes from deterministic tests with in-test canaries, never corpus
fixtures. Real-caller textual memory stays out of scope until an accepted
retention policy exists.

## Required evidence

- Corpus diff with the added cases and controls before the fix.
- Baseline and candidate run artifacts (`evals/results/<run-id>.json`,
  Git-ignored) plus the comparator output with its verdict and reasons.
- Deterministic gate results (`python -m pytest`, Ruff, MyPy, corpus
  `--validate-only`).
- Per-property comparison with no critical regressions; unrepresentable
  fields reported as `NOT REPRESENTABLE IN CURRENT CONTRACT`, not
  approximated.
- Manual spoken-quality review for changed/failing families and controls.

## Pre-voice gate (before seeking deployment authorization)

All of these must hold:

- deterministic gates green;
- complete paired real-model repetitions;
- zero new critical violations and no new PII/security problem;
- target families reviewed and controls reviewed;
- unrelated regressions resolved or explicitly owner-accepted;
- INFRA separated (repetitions or focused reruns, never hidden);
- manual spoken-quality review completed;
- latency/tokens compared with the accepted baseline;
- baseline, candidate, corpus and evaluator identities recorded;
- known residual weaknesses explicitly accepted by the owner.

Only then: explicit deploy authorization → deploy the exact candidate to
controlled DEV → the owner performs the call → `xcally-call-evidence-analysis`.

## STOP conditions

- The change requires semantics not authorized by the SPECs or an Accepted
  ADR.
- Evidence only supports an individual utterance fix with no general property.
- The real-model eval shows a regression in another family and the property
  cannot be corrected without a policy decision.
- The change would require more than two sequential model calls in a normal
  turn.
- Required XCALLY behavior is unknown (route contract, ASR/TTS behavior).
- The candidate cannot be compared because identities or evidence are
  incompatible and no variable/confounder explains it.

## Outputs

- Corpus cases added or updated.
- Baseline/candidate run artifacts and the comparison verdict with reasons.
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
- Whether the change ships: acceptance requires the pre-voice gate above and
  then a real owner-executed call analyzed with
  `xcally-call-evidence-analysis`.
