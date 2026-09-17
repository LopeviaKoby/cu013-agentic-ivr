# CU013 conversation evaluation corpus

Versioned, synthetic, PII-free conversation cases for eval-driven
development of the CU013 conversational backend.

## What this is

- The shared semantic corpus for real-model evals (manual, outside CI) and
  for the deterministic runtime tests that encode accepted properties.
- Organized by family; every case states observable expectations, never
  exact wording.

## What this is NOT

- No phrase matching, no keyword/regex rules, no ASR string matching.
  Cases exercise semantic properties; the runner compares decisions and
  state, not sentences.
- No PII, no raw DTMF, no real transcripts. Every utterance is synthetic
  and safe to commit.

## Case schema

Each case in `cases.yaml` has:

```yaml
case_id: kebab-case identifier
family: one of the families below
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
turn_semantics: sequence|paraphrases    # optional; "paraphrases" probes one property per turn
turns:
  - transcript: synthetic caller utterance (may be a paraphrase set)
external_events:                         # simulated domain events, only when relevant
  - event: <identity_validation|confirmation_timeout|dispatch_timeout|result|late_result|delivery|goal_revision>
    result: <caller_failure|technical_failure|confirmed|failed|pending|...>  # structured outcome
    detail: synthetic payload description
expected:
  route: <CONTINUE|COLLECT_IDENTITY|COMPLETE|ESCALATE|UNSPECIFIED>
  conversation_goal: <goal|null|unchanged>
  confirmation_state: <pending|authorized|invalidated|cancelled|none|not_valid|not_oracled>
  action_eligibility: <eligible|not_eligible>
  dispatch_count: <int>                  # 0 or 1 per case by invariant
  state_delta: <brief semantic description>
  escalation_eligibility: <eligible|not_eligible>
  allowed_claims: [...]                  # claims the agent may state
  forbidden_claims: [...]                # claims the agent must never state
```

`confirmation_state` describes the fate of the challenge that existed before
the case: `invalidated`/`cancelled`/`none` mean no active challenge remains
(a re-prompt may open a new one), and `authorized` means the dispatch guard
exists. `not_valid` oracles only the contractual effect (no usable challenge
remains) and accepts either internal conclusion, so the corpus never
overfits internal enum names; `not_oracled` means the case deliberately does
not oracle whether HITL started in that turn. The runner reports the observed
conclusion separately.

`route: UNSPECIFIED` marks a case whose exact route depends on a still-open
wire contract (for example the identity technical-failure result): the state
invariants are still compared in full and the route is reported as
`NOT ORACLED`, never as a failure.

A runner that cannot express a field reports
`NOT REPRESENTABLE IN CURRENT CONTRACT` instead of faking support. Event-only
cases and cases whose turn carries no caller speech (silence/timeout) are
evaluated on state and reported as `NOT EVALUATED` for the route, because the
XCALLY wire contract for those events is still open.

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

Runtime semantic runner (manual, outside CI, requires ADC): it replays each
case against the real model and the deterministic runtime, then reports per
case (PASS / FAIL / NOT ORACLED / NOT REPRESENTABLE / INFRA), per family, plus
latency (model, runtime semantic processing and turn total: count, min, p50,
p95, max), prompt/completion tokens per call and accumulated tokens for
multi-turn and paraphrase cases:

```powershell
.\.venv\Scripts\python.exe evals\conversation_baseline_eval.py
.\.venv\Scripts\python.exe evals\conversation_baseline_eval.py --validate-only
```

`--validate-only` checks the corpus schema statically (routes, confirmation
states, eligibility values, event kinds and results, control references)
without ADC, model or network; it is the deterministic corpus gate.

Boundary events are simulated domain events: the XCALLY/AD wire contract
remains open (ID-001, XC-001..XC-006), so the runner never invents or calls a
payload. A transient Vertex failure is reported as `INFRA` and excluded from
the comparison instead of being counted as a semantic verdict.

Deterministic tests encode the same expectations against the runtime
without the model. See [testing standards](../../docs/engineering/testing.md).
