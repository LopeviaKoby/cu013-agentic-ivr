# Experiment 0006: Semantic runtime evaluation against the conversation corpus

- Status: Completed (local candidate); DEV voice validation pending
- Lifecycle: Planned → Running → Completed (local) → DEV voice validation pending
- Authority: Experimental evidence only; not an architectural decision
- Date: 2026-09-17

## Question and hypothesis

Can ADR-0010 be materialized as a durable semantic runtime — plan,
identity authorization with TTL, confirmation challenge, dispatch guard and
external-operation truth, all separated — so that the accepted corpus
(`evals/conversation/cases.yaml`) behaves as specified against the real model
without regressions in authorization, HITL, PII, side-effect duplication,
false results or illegal handoff?

Hypothesis before implementing: the deterministic runtime can own every
legality invariant (no dispatch without valid identity plus a matching
challenge, one active operation, no invented results) while the model keeps
owning language; the residual risk is model instruction-following on the
general conversational properties, not runtime legality.

## Candidate under measurement

Working tree on top of `9cb93fe` (`dev` == `origin/dev`), committed at the end
of this session; no runtime artifact deployed.

```text
app/session/record.py     schema v2: goal / identity / confirmation / dispatch /
                          external operation, closed whitelist, fail-closed v1 migration
app/session/turns.py      semantic ModelTurnDecision proposals, event seam and the
                          deterministic legality guard (routes, claims, dispatch)
app/session/service.py    v2 consolidation, injectable clock, one load and one save
app/session/repository.py new records stamped with the injected turn clock
app/conversation/*        general prompt, semantic state projection, runtime outcome
evals/*                   corpus replay runner over the real model and the runtime
```

Migration behavior (deterministic tests, no bulk rewrite, DEV documents
untouched):

- v1 documents parse against the closed v1 whitelist and migrate in memory;
  v2 is written only on the next legitimate save;
- a legacy `identity_validated: true` never becomes a valid authorization
  (v1 has no `validated_at`, so the 30-minute TTL cannot be demonstrated);
- a legacy `requested_action` becomes at most a conversation goal;
- a legacy `pending_operation` preserves only the truth v1 recorded: no
  confirmation, dispatch, delivery or success is inferred;
- `conversation_id`, `turn_count`, `revision`, `created_at` and `updated_at`
  are preserved.

### Owner decisions resolved in this session

| Decision | Materialization |
|---|---|
| Unsupported request never implies handoff; known-but-unsupported and out-of-scope requests are declined or redirected | `system.md` plan invariant; `account-actions.md` handoff causes; `HandoffCause` no longer contains `UNSUPPORTED_OPERATION`; prompt scope rule; corpus paraphrases (VPN, VDI, weather, restaurant) |
| An explicit human request is enough on the first attempt and preserves the goal | prompt rules for explicit request and goal preservation; runtime never clears the goal on handoff; corpus `caller-asks-human` paraphrases plus `human-request-after-unsupported` and `caller-cancels-then-asks-human` controls |
| Technical identity failure has no normative route | corpus route `UNSPECIFIED` → reported `NOT ORACLED`; attempt/auth/dispatch/escalation invariants still compared; deterministic test asserts no attempt consumption and no auto escalation |
| A side question does not open or reopen a challenge by itself | HITL invariant in `system.md`; prompt rule; corpus `side-question-during-plan` paraphrases; deterministic test that no challenge opens without an explicit request |
| An invalidated challenge is never reused; a re-prompt creates a new challenge bound to action + current revision | `system.md`; deterministic test asserting `old_challenge_id != new_challenge_id` and the binding |
| Goal cancellation is a semantic oracle, not an internal label | corpus `not_valid` accepts any internal conclusion with no usable challenge; `not_oracled` covers cases that deliberately do not oracle HITL start |

## Deterministic gates

```text
python -m pytest                 193 passed
python -m ruff check .           All checks passed
python -m ruff format --check .  80 files already formatted
python -m mypy app               Success: no issues found in 18 source files (strict)
git diff --check                 clean
corpus --validate-only           34 cases / 0 problems (no ADC, no model)
```

No Dockerfile, dependency, lock or packaged-runtime change: no Docker gate.
Deterministic coverage includes migration, plan, identity TTL and failure
counts, confirmation lifecycle (including challenge replacement), dispatch
guards, external-operation truth, route/claim legality, closed handoff causes,
one load and one save, no persistent checkpointer and DTMF isolation.

## Real-model evaluation

```text
provider vertex_ai  project cu013-xcally-agentic  location us-east1
model gemini-2.5-flash-lite  api_version v1  thinking_budget 0
timeout_ms 15000  attempts 1  streaming/tools off
corpus 34 cases / 30 families  repetitions 3  one process, no caching
runner evals/conversation_baseline_eval.py (manual, outside CI, ADC)
events simulated domain events; XCALLY/AD wire contract still open
```

Method: every case replays through the real `GeminiTurnModel` and the real
`advance_turn`/`consolidate` path; comparisons are semantic (route, goal and
revision, confirmation conclusion, eligibility, dispatch count, guard
violations), never wording. Paraphrase sets are checked per turn. Latency is
segmented into model, runtime semantic processing and turn total, and tokens
are split into prompt and completion per call, with accumulated tokens for
multi-turn and paraphrase cases.

### Canonical run (final prompt/corpus/runtime)

```text
families 21/30 PASS   cases: 22 PASS / 9 FAIL / 1 INFRA / 2 NOT ORACLED
141 runtime turns, 135 model calls, 1 transient Vertex failure
```

Per-family result (canonical run plus focused INFRA re-runs):

| Family | Result | Note |
|---|---|---|
| ambiguous-request, caller-does-not-ask-human, confirmation-ambiguous-asr, confirmation-silence-timeout, confirmation-stale-after-goal-revision, confirmed-success, duplicate-replay, goal-correction, goal-switch, identity-expired, identity-three-failures, identity-unvalidated, identity-validated, pending-operation, reset-confirmed-delivery-unconfirmed, side-question-during-plan, unknown-dispatch-result | PASS | includes the owner-decision families above |
| unsupported-request | PASS | goal null, no dispatch, no handoff, truthful scope message (focused probe 4/4) |
| identity-technical-failure | NOT ORACLED | invariants hold: no attempt consumed, no auth, no dispatch, no auto escalation |
| goal-cancellation | NOT ORACLED | goal cleared, challenge unusable, no dispatch; route not oracled |
| direct-supported-request | FAIL (1 of 2 cases in the canonical run) | `reset-direct-request` routed `CONTINUE` in one repetition; focused re-run 2/2 PASS and two earlier runs 2/2 PASS |
| asr-paraphrase-noise | FAIL (1 of 3 turns) | turn 1 routed `CONTINUE`; focused probe PASS 3/3 |
| caller-asks-human | FAIL (1 of 3 cases) | route `ESCALATE` correct in every repetition; in some repetitions the model proposes goal `CANCEL`, clearing the goal against the owner decision |
| confirmation-affirmative | FAIL / mixed | in 1 of 3 repetitions the affirmation authorized the dispatch correctly; in others the model re-asked or classified it as a plan change |
| confirmation-negation | FAIL | the model sometimes treats "no, no hagas nada" as abandoning the goal instead of `NEGATIVE`; no dispatch in any repetition |
| confirmed-failure, late-result | FAIL | follow-up questions sometimes bump the goal revision (`CORRECT`), which the runner reports as eligibility change; runtime stays safe |
| multiple-supported-goals | FAIL (1 repetition) | the goal switch did not happen in one repetition; challenge opening not oracled |
| multi-turn-continuity | FAIL | final turn routed `CONTINUE` instead of `COLLECT_IDENTITY` in every run |
| side-question-before-action | FAIL (exp0005 case) | the model still routes `COLLECT_IDENTITY` before answering the prepended question in some turns |

### Critical-regression check

- no dispatch without a valid identity or a matching challenge: observed in
  every run (no dispatch-binding violation was ever recorded);
- no side-effect duplication and one active operation: observed;
- invented success, delivery, authorization and identity claims were rejected
  deterministically (`unbacked claim ...` guard violations) while the legal
  messages passed untouched;
- no PII or DTMF in durable state, logs or fixtures;
- no illegal handoff: the only escalation observed carried a permitted cause
  (caller request or forced third identity failure);
- no case reported `NOT REPRESENTABLE`; the harness owns the full corpus
  vocabulary.

## Latency and tokens before vs after this iteration

Both measurements use the same runner, model, budget and DEV host; the corpus
grew from 32 to 34 cases (7 paraphrase turns added), so counts differ.

| Metric | Before | After (canonical) |
|---|---|---|
| model latency ms: count / min / p50 / p95 / max | 105 / 828 / 1172 / 7657 / 8688 | 135 / 765 / 968 / 1688 / 7969 |
| runtime semantic ms: count / min / p50 / p95 / max | 111 / 0 / 0 / 0 / 15 | 141 / 0 / 0 / 0 / 16 |
| turn total ms: count / min / p50 / p95 / max | 111 / 0 / 1156 / 7657 / 8688 | 141 / 0 / 953 / 1437 / 7969 |
| prompt tokens per call: count / min / p50 / p95 / max | 105 / 1147 / 1163 / 1170 / 1174 | 135 / 1436 / 1450 / 1463 / 1468 |
| completion tokens per call: count / min / p50 / p95 / max | 105 / 67 / 97 / 118 / 142 | 135 / 74 / 97 / 114 / 129 |
| accumulated tokens, 3-turn paraphrase case (mean total) | 3738–3815 | 4614–4670 |
| accumulated tokens, 4-turn paraphrase case (mean total) | — | 6105 |

Interpretation: the runtime semantic processing is negligible (p95 ≈ 0 ms,
max 16 ms) and does not add a measurable latency component. The prompt grew
by ≈ 287 tokens per call (+25 %), stable across calls, with completion tokens
unchanged; multi-turn cases accumulate ≈ +24 % tokens because the system
prompt is paid per turn. Model p50/p95 in this sample are lower than the
before run, but both runs include multi-second outliers (8.7 s before, 8.0 s
after) and per-turn load varies, so no latency improvement is claimed. No new
threshold was fixed; these remain DEV host observations, not Cloud Run and not
an SLO. No material regression was observed.

## Remaining model weaknesses (not runtime)

1. `caller-asks-human`: the model sometimes emits a goal `CANCEL` together
   with the handoff, clearing the goal. The runtime cannot distinguish an
   explicit cancellation from a wrong one; only the model reads the caller's
   wording. Requires DEV voice evidence and possibly a model comparison.
2. Confirmation classification (`AFFIRMATIVE` / `NEGATIVE` / `AMBIGUOUS` /
   `CORRECT`): acceptance is sometimes re-asked or classified as a plan
   change; negation is sometimes treated as goal cancellation; a doubtful
   answer is sometimes kept pending. The dispatch guard stayed safe in every
   failing repetition (no dispatch without an affirmative).
3. Immediate-need precedence (`exp0005`): the model sometimes starts
   `COLLECT_IDENTITY` before answering the prepended question.
4. `multi-turn-continuity`: the final turn routes `CONTINUE` instead of
   `COLLECT_IDENTITY`.
5. Route variance on direct requests, goal switch and result follow-ups
   (occasional `CONTINUE`, `COMPLETE` or revision bump).
6. Out-of-scope/known-but-unsupported handling improved from an escalation to
   a correct decline after the general scope rule; no regression observed.

## Limitations

- One model (`gemini-2.5-flash-lite`, `thinking_budget=0`) and a synthetic
  corpus; this is not a quality verdict and does not replace DEV voice
  validation.
- Paraphrase cases replay their turns as one accumulating conversation, so
  later paraphrases start from the state the earlier ones left; route
  stability across repetitions is reported but the set is not independent.
- The claims guard verifies structured claims the model declares; it does not
  verify all natural language (by design, per ADR-0010 and the testing
  standard).
- Server-side route correlation and the XCALLY wire contract for identity,
  confirmation and result events remain open (ID-001, XC-001..XC-006); the
  runner simulates domain events and never invents a payload.
- A transient Vertex failure is reported as `INFRA` and excluded from the
  semantic comparison; focused re-runs were used to resolve the affected
  families.

## Conclusion

**Candidate accepted for local commit: the deterministic runtime materializes
ADR-0010 with zero critical regressions, all deterministic gates green, and
the owner decisions representable and verified at the runtime level.** The
real-model evaluation shows the remaining gaps are model
instruction-following and classification weaknesses, not runtime legality:
every safety invariant held in every repetition, including the failing ones,
and the dispatch guard authorized only legal, challenge-bound affirmations.
CNV-001 closes at the runtime level; conversational quality and the residual
model weaknesses above move to DEV voice validation, which remains the next
gate and is not executed by this experiment.

## References

- [ADR-0010: durable semantic plan](../decisions/0010-durable-semantic-plan-separate-from-authorization.md)
- [System specification](../specs/system.md)
- [Account actions specification](../specs/account-actions.md)
- [Conversation corpus](../../evals/conversation/README.md)
- [Experiment 0005: XCALLY voice turn diagnosis](0005-xcally-voice-turn-diagnosis.md)
- [Implementation gaps](../gaps.md)
