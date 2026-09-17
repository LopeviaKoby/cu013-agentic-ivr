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
  confirmation: <pending|none|challenge-id|null>
  pending_operation: <pending|unknown|confirmed|failed|null>
turns:
  - transcript: synthetic caller utterance (may be a paraphrase set)
external_events:                         # simulated, only when relevant
  - event: <dispatch|result|late_result|delivery|...>
    detail: synthetic payload description
expected:
  route: <CONTINUE|COLLECT_IDENTITY|COMPLETE|ESCALATE>
  conversation_goal: <goal|null|unchanged>
  confirmation_state: <pending|authorized|invalidated|cancelled|none>
  action_eligibility: <eligible|not_eligible>
  dispatch_count: <int>                  # 0 or 1 per case by invariant
  state_delta: <brief semantic description>
  escalation_eligibility: <eligible|not_eligible>
  allowed_claims: [...]                  # claims the agent may state
  forbidden_claims: [...]                # claims the agent must never state
```

A runner that cannot express a field yet reports
`NOT REPRESENTABLE IN CURRENT CONTRACT` instead of faking support.
`initial_state` may carry additional synthetic fields when a case needs them
(e.g. `identity_failure_count`, `identity_validated_at_expired`); runners that
cannot represent them treat the case as `PARTIAL`.

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
| unsupported-request | unsupported request declines without handoff unless required |
| caller-asks-human | handoff because the caller requested it |
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

Real-model baseline runner (manual, outside CI, requires ADC):

```powershell
.\.venv\Scripts\python.exe evals\conversation_baseline_eval.py
```

The runner records route, the semantic proposal fields available today
(`action_requested`), latency and route stability per family. Token usage is
not exposed by the current `TurnModel` seam and is therefore not reported
rather than approximated. Checks the current model contract cannot express
(conversation goal, confirmation state, dispatch eligibility, external truth)
are reported as `NOT REPRESENTABLE IN CURRENT CONTRACT`.

Deterministic tests encode the same expectations against the runtime
without the model. See [testing standards](../../docs/engineering/testing.md).
