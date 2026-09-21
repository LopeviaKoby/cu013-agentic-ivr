# CU013 conversation evaluation corpus

Versioned, synthetic, PII-free conversation cases for eval-driven
development of the CU013 conversational backend.

## What this is

- The shared semantic corpus for real-model evals (manual, outside CI) and
  for the deterministic runtime tests that encode accepted properties.
- Organized by family; every case states observable expectations, never
  exact wording.
- The active baseline (Gemini 3.5 Flash-Lite, Vertex AI model location
  `global`, reasoning level `MINIMAL`, mandatory structured procedure
  classification, recent memory of three completed pairs) is derived from
  `config.yaml` and `app/conversation`; the harness calculates its
  fingerprint in runtime. Selection history lives in the accepted ADR,
  Experiment 0009 and Git.

## What this is NOT

- No phrase matching, no keyword/regex rules, no ASR string matching.
  Cases exercise semantic properties; the evaluator compares decisions and
  state, not sentences.
- No PII, no raw DTMF, no real transcripts. Every utterance is synthetic
  and safe to commit.
- Not a voice validation and not a production acceptance: those are separate
  gates (`xcally-call-evidence-analysis`, deployment authorization).

## Case schema

Each case in `cases.yaml` has:

```yaml
case_id: kebab-case identifier
family: one of the families below
scenario_kind: independent_trial|sequence
description: what property the case probes
initial_state:
  identity_validated: true|false
  conversation_goal: <goal|null>        # semantic, not a class name
  goal_revision: <int>
  confirmation: <pending|authorized|none|null>
  confirmation_goal_revision: <int>     # optional; binds a challenge to an older revision
  pending_operation: <pending|unknown|confirmed|failed|null>
  identity_failure_count: <int>         # optional
  identity_validated_at_expired: true   # optional
turns:
  - transcript: synthetic caller utterance
    events:                             # optional per-turn simulated domain events
      - event: <identity_validation|confirmation_timeout|dispatch_timeout|result|late_result|delivery|goal_revision>
        result: <structured outcome>
        detail: synthetic payload description
    expect:                             # optional per-turn checkpoints (sequences)
      route: <CONTINUE|COLLECT_IDENTITY|COMPLETE|ESCALATE|UNSPECIFIED>
      goal: <goal|null|unchanged>
      goal_transition: <absent|created|retained|changed|cleared|not_oracled>
      revision_transition: <same|incremented|created|cleared|not_oracled>
      confirmation: <absent|pending|changed|new_challenge|authorized|invalidated|cancelled|not_valid|not_oracled>
      identity_valid: true|false
      dispatch_count_unchanged: true
      operation: <none|active|pending|unknown|confirmed|failed|not_oracled>
      obsolete_goal_absent: true
external_events:                         # case-level events attach to the last turn
  - event: <...>
    result: <...>
expected:
  route: <CONTINUE|COLLECT_IDENTITY|COMPLETE|ESCALATE|UNSPECIFIED>
  conversation_goal: <goal|null|unchanged>
  handoff_cause: <CALLER_REQUEST|TERMINAL_FAILURE|null|not_oracled>
  confirmation_state: <pending|authorized|invalidated|cancelled|none|not_valid|not_oracled>
  action_eligibility: <eligible|not_eligible>
  dispatch_count: <int>                  # 0 or 1 per case by invariant
  state_delta: <brief semantic description>
  escalation_eligibility: <eligible|not_eligible>
  allowed_claims: [...]                  # claims the agent may state
  forbidden_claims: [...]                # claims the agent must never state
```

### Trial kinds

- `independent_trial`: each turn (paraphrase) starts from the same fresh
  `initial_state`; no state leaks between paraphrases and repetitions are
  independent samples. Single-turn cases are trivially independent.
- `sequence`: state intentionally carries turn-to-turn, the case is one
  conversation and per-turn checkpoints under `expect` are asserted after
  individual turns.

### Oracle semantics

A **present** expected key asserts a value, including an explicit `null` that
means "expected absent" (`conversation_goal: null`, `handoff_cause: null`).
An **absent** key is reported `NOT ORACLED`, so a missing oracle is visible
and never looks like a pass.

`state_delta` is descriptive metadata. `allowed_claims` and
`forbidden_claims` are human-review evidence for the spoken-quality review,
not machine oracles: natural language is not matched with a fragile matcher.
Machine claim truth is enforced by the runtime guard (unbacked claims are
rejected) and reported as structured evidence.

`confirmation_state` describes the fate of the challenge that existed before
the case: `invalidated`/`cancelled`/`none` mean no active challenge remains
(a re-prompt may open a new one), and `authorized` means the dispatch guard
exists. `not_valid` oracles only the contractual effect (no usable challenge
remains) and accepts either internal conclusion, so the corpus never
overfits internal enum names; `not_oracled` means the case deliberately does
not oracle whether HITL started in that turn. The evaluator reports the
observed conclusion separately.

`route: UNSPECIFIED` marks a case whose exact route depends on a still-open
wire contract (for example the identity technical-failure result): the state
invariants are still compared in full and the route is reported as
`NOT ORACLED`, never as a failure.

Fields the evaluator cannot express are reported
`NOT REPRESENTABLE IN CURRENT CONTRACT` instead of faked. Event-only cases
and cases whose turn carries no caller speech are evaluated on state and
reported as `NOT ORACLED` for the route, because the XCALLY wire contract for
those events is still open.

## Families

| Family | Property probed |
|---|---|
| direct-supported-request | supported request flows to identity/confirmation |
| side-question-before-action | prior question answered, goal kept, no premature auth |
| side-question-during-plan | mid-plan question does not drop the goal |
| goal-switch | caller changes goal; plan and challenge update |
| goal-correction | caller corrects details; revision bumps, challenge invalidated |
| goal-cancellation | explicit cancel before dispatch cancels the action |
| multiple-supported-goals | more than one supported goal handled |
| ambiguous-request | ambiguity leads to clarification, no dispatch |
| unsupported-request | unsupported or out-of-scope request declines/redirects without handoff |
| caller-asks-human | handoff because the caller explicitly requested it; goal preserved unless explicitly cancelled |
| caller-does-not-ask-human | no handoff without a valid cause |
| identity-unvalidated | no dispatch authorization before identity |
| identity-validated | identity enables eligibility, not dispatch |
| identity-expired | 30-minute absolute TTL forces re-validation |
| identity-three-failures | third caller identity failure hands off |
| identity-technical-failure | technical failure consumes no caller attempts |
| confirmation-affirmative | explicit affirmative authorizes the concrete action |
| confirmation-negation | explicit negation never dispatches |
| confirmation-silence-timeout | silence/timeout invalidates and re-prompts |
| confirmation-ambiguous-asr | low-confidence capture invalidates and re-prompts |
| confirmation-stale-after-goal-revision | revised goal invalidates the challenge |
| pending-operation | active operation blocks a second dispatch |
| confirmed-success | confirmed result may be claimed |
| confirmed-failure | failure may be claimed; no success wording |
| unknown-dispatch-result | UNKNOWN is claimed as unknown |
| reset-confirmed-delivery-unconfirmed | reset and delivery are separate facts |
| duplicate-replay | duplicate/replayed events do not re-dispatch |
| late-result | late result reconciles; no new operation |
| multi-turn-continuity | goal survives turns without transcript persistence |
| asr-paraphrase-noise | paraphrases/localisms preserve semantics |
| long-conversation-memory | long intentional sequence: goal, side question, identity progress, correction, ambiguous answer, follow-ups |

## Provenance

The case `exp0005-prior-request` records the failure that originated
[Experiment 0005](../../docs/experiments/0005-xcally-voice-turn-diagnosis.md)
as a corpus case with paraphrases and opposite controls, not as a
privileged rule:

- property: answer the current conversational need without losing the
  supported goal and without starting authorization or dispatch;
- paraphrases: several wordings of "action + prior question";
- positive controls: direct action proceeds to identity;
- negative controls: isolated question alone does not create a goal.

## Usage

Real-model evaluator (manual, outside CI, requires ADC): replays each trial
against the real model and the deterministic runtime and writes sanitized
structured evidence (run, case/repetition and turn level) to
`evals/results/<run-id>.json` (Git-ignored):

```powershell
.\.venv\Scripts\python.exe evals\conversation_eval.py
.\.venv\Scripts\python.exe evals\conversation_eval.py --validate-only
.\.venv\Scripts\python.exe evals\conversation_eval.py --families caller-asks-human --scope focused --focused-reason "diagnosed INFRA rerun"
```

`--validate-only` checks the corpus schema statically (scenario kinds,
routes, confirmation states, eligibility values, per-turn checkpoints, event
kinds and results, control references) without ADC, model or network; it is
the deterministic corpus gate.

Pure paired comparator (no model): compares two run artifacts, refuses
incompatible identities unless the variable/confounder is declared, forces
REJECT on new executed critical violations and emits the manual
spoken-quality review template:

```powershell
.\.venv\Scripts\python.exe evals\conversation_compare.py `
  --baseline evals\results\<baseline-run>.json `
  --candidate evals\results\<candidate-run>.json `
  --variable effective_prompt_hash --target-family caller-asks-human
```

Boundary events are simulated domain events: the XCALLY/AD wire contract
remains open (ID-001, XC-001..XC-006), so the evaluator never invents or
calls a payload. A transient Vertex failure is reported as `INFRA` at
repetition level and excluded from the semantic comparison instead of being
counted as a semantic verdict; invalid structured model output is a model
failure, never INFRA.

Deterministic tests encode the same expectations against the runtime
without the model. See [testing standards](../../docs/engineering/testing.md).

## Experiment 0009 memory/procedure extension (synthetic lane only)

Experiment
[0009](../../docs/experiments/0009-conversational-memory-and-eight-callers.md)
extends this lab without replacing it. The no-memory baseline, the
procedure-only variant, the recent-conversation-memory variant, the window
size, byte caps, procedure fields and retained text are evaluation
variants with fingerprints, not Accepted requirements (historic short
codes for these variants appear only in preserved evidence).
Real-caller textual memory stays disabled; the trial runs synthetic,
non-sensitive utterances only. The corpus is 47 cases / 39 families.

New sequence families (all synthetic, PII-free):

| Family | Property probed |
|---|---|
| pronoun-reference | prior referent resolves; goal and guided step stay stable |
| procedure-lost-step | "which step?" returns the stored current step |
| side-question-return | lateral answer keeps goal/step; return lands on the step |
| temporary-goal-switch | one bounded suspended procedure; explicit return resumes it |
| goal-correction | detail correction rebinds the procedure without restarting it |
| retroactive-step-correction | "I did not finish that step" regresses only to a legal step |
| long-guided-procedure | early pair evicted under the cap; current step survives |
| forgetting-boundary | evicted incidental detail is not claimed as remembered |
| procedure-grounding | tempting-but-absent facts not invented; capability without execution promise |

`sensitive-input-never-memory`, `restart-continuity` and `same-session-race`
are covered by deterministic tests (`tests/session/test_memory_privacy.py`,
`tests/session/test_memory.py`, `tests/session/test_memory_race.py`) with
in-test canaries — never corpus fixtures. `8-session-burst` is prepared,
not executed, in `evals/conversation_burst.py`.

Per-turn checkpoints add three machine oracles: `procedure_current` and
`procedure_last_completed` (exact guided-step match, explicit `null`
asserts no step) and `window_pairs` (recent-pair count). Referent wording,
lateral-answer quality and the return transition stay in the manual
spoken-quality review, never in a wording matcher.

Runner lanes and arms:

```powershell
.\.venv\Scripts\python.exe evals\conversation_eval.py --lane repository --memory-variant no_recent_memory
.\.venv\Scripts\python.exe evals\conversation_eval.py --lane repository --memory-variant procedure_progress_only
.\.venv\Scripts\python.exe evals\conversation_eval.py --lane repository --memory-variant recent_conversation_memory
```

- `--lane direct` invokes model + runtime without persistence (historical).
- `--lane repository` replays through `TurnService` with save/reload per
  turn and a fresh service per turn (restart proof); the only supported
  lane for paired memory comparisons.
- `--memory-variant no_recent_memory|procedure_progress_only|recent_conversation_memory`
  selects the arm (`no_recent_memory` = no conversation memory,
  `procedure_progress_only` = procedure progress without recent history,
  `recent_conversation_memory` = recent conversation memory with the
  three-pair window); `--memory-n` stays 3 unless the experiment's escalation
  condition is met. `--prompt-strategy` selects the prompt policy
  (`default_prompt_policy`, `concise_prompt_policy`,
  `contrastive_examples_prompt_policy`, `precedence_prompt_policy`).
- Run artifacts additionally record per-turn `session_bytes`,
  `memory_encode/decode/render_ms`, session summaries and the
  `memory_variant`/`lane`/renderer/procedure-schema fingerprint. No
  transcript or model message is ever retained: projections carry step
  identifiers and counts only.

Paired comparison declares the variable explicitly:

```powershell
.\.venv\Scripts\python.exe evals\conversation_compare.py `
  --baseline evals\results\<no-recent-memory-run>.json `
  --candidate evals\results\<recent-conversation-memory-run>.json `
  --variable memory_variant --target-family pronoun-reference
```
