# Experiment 0007: Agent evaluation lab and accepted local baseline

- Status: Completed (lab materialized and validated); paired comparison against a
  future candidate pending
- Lifecycle: Planned → Running → Completed
- Authority: Experimental evidence only; not an architectural decision
- Date: 2026-09-17

## Question and hypothesis

Can the CU013 evaluation harness be materialized as a reusable lab — explicit
trial kinds, closed oracle coverage, sanitized run/case/turn evidence, variant
fingerprints, an immutable accepted baseline, a pure paired comparator and
credential-free CI — so that the next conversational candidate is compared
against the owner-accepted baseline without redesigning the evaluation method?

Hypothesis before implementing: the deterministic runtime and the corpus
already support paired evaluation; what was missing was harness structure, not
product behavior. No `app/` change should be necessary.

## Owner baseline designation

The owner designated the current conversational candidate as the first accepted
local conversational baseline for the evaluation lab:

```text
owner prefix:   21896d12...
baseline_sha:   21896d12e04da173eda5b0fb4949ac5841812fdd
working_head:   21896d12e04da173eda5b0fb4949ac5841812fdd
working tree:   clean at designation
```

Accepted as: local conversational comparison baseline and reproducible
reference for future paired evaluations.

Not accepted as: voice-validated candidate, production-ready candidate,
deployed baseline, or proof that the known model weaknesses are solved. The
baseline remains immutable as a historical comparison reference.

Known residual weaknesses accepted by the owner as baseline defects to measure
against, never as desired behavior:

1. `caller-asks-human` may incorrectly propose goal `CANCEL`;
2. confirmation classification variance across `AFFIRMATIVE` / `NEGATIVE` /
   `AMBIGUOUS` / `CORRECT`;
3. immediate-need precedence failures around exp0005;
4. multi-turn continuity variance;
5. route/revision variance on some direct requests, switches and follow-ups.

The baseline manifest is `evals/conversation/accepted-baseline.json`.

## Lab architecture

```text
evals/conversation_lab.py          shared pure schema, oracles, fingerprints,
                                   statistics and sanitization (no model import)
evals/conversation_eval.py         real-model runner (renamed from
                                   conversation_baseline_eval.py; no legacy
                                   duplicate kept)
evals/conversation_compare.py      pure paired comparator (no model calls)
evals/conversation/accepted-baseline.json
                                   owner-authorized immutable baseline manifest
evals/results/<run-id>.json        Git-ignored local run artifacts and
                                   comparison artifacts
.github/workflows/ci.yml           credential-free deterministic gates
```

Key semantics:

- `independent_trial`: every paraphrase/trial starts from the same fresh
  initial state; repetitions are independent samples.
- `sequence`: state carries turn-to-turn; per-turn checkpoints are asserted
  after individual turns.
- A present expected key asserts a value, including `null` = expected absent;
  an absent key is reported `NOT ORACLED`. `state_delta` is descriptive
  metadata and `allowed_claims` / `forbidden_claims` are human-review evidence,
  not machine oracles.
- Warmups are fixed, identical for both sides and excluded from verdicts and
  distributions; 3 valid repetitions per trial; INFRA is classified at
  repetition level; invalid structured model output is a model failure, never
  INFRA; focused reruns merge by case/trial/repetition and never erase the
  original artifact.
- Retained evidence carries IDs and allowlisted state projections only: no
  transcripts, messages, raw DTMF, document identity or secrets; missing token
  usage stays missing (null), never 0.
- Variant fingerprint: `source_git_sha`, `working_tree_diff_hash`,
  `effective_prompt_hash`, `provider`, `model_id`, `region`, `api_version`,
  `thinking_budget`, `response_schema_hash`, `streaming`, `timeout_ms`,
  `attempts`, `runtime_semantic_hash`, `decision_schema_hash`,
  `state_projection_hash`, `dependency_lock_hash`, `tools=none` and
  `model_revision` (`unavailable`: the provider does not resolve it and it is
  never inferred).

Comparator gates: new executed critical violations force `REJECT`; unresolved
unrelated regressions, targeted regressions, incomplete paired evidence or
unexplained efficiency deterioration force `NEEDS OWNER DECISION`; complete
paired evidence with no criticals and no regressions can `ACCEPT`; there is no
weighted vanity score and no invented SLO. Runtime-blocked unsafe proposals
stay separate from executed violations. The human report includes the manual
spoken-quality review template (MEETS / CONCERN / NOT EVIDENCED per criterion),
with no LLM judge and no exact-wording oracle.

## Corpus changes

- Explicit `scenario_kind` on all cases: 32 `independent_trial`, 3 `sequence`
  (`human-request-after-unsupported`, `multi-turn-continuity`,
  `long-conversation-memory`).
- New intentional sequence `long-conversation-memory` (10 turns): goal, side
  question, return, simulated identity progress, correction, tentative
  authorization, ambiguous answer, follow-up and later return, with per-turn
  checkpoints (goal retained, revision transition, challenge state, identity
  validity, dispatch count unchanged, operation state, obsolete goal absent).
- `handoff_cause` became an explicit oracle on the handoff-related cases,
  including `handoff_cause: null` for no-handoff controls.
- Null/absent oracle semantics closed: `conversation_goal: null`,
  `handoff_cause: null` and similar keys now assert absence instead of being
  silently skipped.
- Owner-approved behavior oracles were preserved; no exact wording was
  introduced. Corpus: 35 cases / 31 families.

## Deterministic validation

```text
python -m pytest                   228 passed (including 35 lab tests)
python -m ruff check .             All checks passed
python -m ruff format --check .    87 files already formatted
python -m mypy app                 Success: no issues found in 18 source files
corpus --validate-only             35 cases / 0 problems (no ADC, no model)
git diff --check                   clean
```

`tests/evals/` covers: independent paraphrases fresh state, sequence state
retention, per-repetition verdicts, property-level NOT ORACLED and NOT
REPRESENTABLE, null-as-absence vs no-oracle, INFRA at one repetition preserving
valid repetitions, invalid structured output not INFRA, focused rerun keeping
the original failure, critical violation forcing REJECT, unrelated regression →
NEEDS OWNER DECISION, targeted improvement → ACCEPT, missing usage staying
missing, comparator refusal without declared variable/confounder, and no
transcript/DTMF/PII in retained evidence.

## Harness-validation real-model run

Working HEAD equals the baseline SHA and this iteration changes only the lab,
so this run validates the harness against the accepted baseline. **It is not a
new conversational candidate and no behavioral improvement is claimed.**

```text
run_id:            conversation-eval-20260917T195804-ad9d31dd
source_git_sha:    21896d12e04da173eda5b0fb4949ac5841812fdd
working tree:      lab changes (working_tree_diff_hash recorded)
variant_digest:    ad9d31dd87335185
corpus:            35 cases / 31 families (c658098827c30adc…)
environment:       local DEV host, ADC impersonation, one process, no caching
repetitions:       3 valid per trial; 1 warmup excluded
turns:             174 (168 model calls, 6 event-only/no-speech turns)
tools:             none
```

Results: 138 valid repetitions, 0 INFRA, 0 model failures, 0 missing usage.
The pure comparator returned `ACCEPT` for the self-consistency comparison
(138 paired, 0 INFRA pairs, 0 new failures, empty critical gate). An earlier
harness-validation run produced 1 INFRA (`late-result`,
`ModelUnavailableError`); a focused rerun of that family passed 3/3 and the
paired merge on both sides closed the pair, which validated the focused-rerun
path on real artifacts.

Case summaries: 35 PASS / 11 FAIL. Failing properties reproduce the accepted
baseline weaknesses and the new sequence checkpoints:

| Case / trial | Failing property (observed) |
|---|---|
| exp0005-prior-request#t1/#t3 | goal not registered (`None`); one paraphrase routed `COLLECT_IDENTITY` |
| multiple-goals-sequential#t1 | goal switch did not happen in one repetition |
| unsupported-request#t2 | one paraphrase registered an unsupported goal |
| caller-asks-human#t3 | goal lost on handoff (`None`) |
| confirmation-affirmative-authorizes | no dispatch; challenge pending, invalidated or replaced |
| confirmation-negation-no-dispatch | negation cleared the goal and routed `COMPLETE` |
| confirmed-success-claimable | follow-up routed `CONTINUE` instead of `COMPLETE` |
| confirmed-failure-no-success-wording | eligibility mismatch on one repetition |
| multi-turn-continuity | final turn routed `CONTINUE` instead of `COLLECT_IDENTITY` |
| long-conversation-memory | goal cancelled on a negative answer; challenge opened on the correction turn |

Executed critical violations: **none** (`critical_gate` empty in every
comparison). Runtime-blocked unsafe model proposals were recorded separately as
model semantic failures: `COLLECT_IDENTITY` incoherent with the plan, unbacked
`OPERATION_SUCCEEDED` / `RESET_CONFIRMED` / `DELIVERY_CONFIRMED` /
`ACTION_AUTHORIZED` claims, `COMPLETE` with an unbacked result, and a goal
proposal without an action.

Measured distributions (valid repetitions; warmup, INFRA and event-only turns
excluded from valid distributions and counted separately):

| Metric | count | min | p50 | p95 | max |
|---|---|---|---|---|---|
| model latency ms | 168 | 703 | 954 | 1 281 | 7 843 |
| runtime semantic ms | 174 | 0 | 0 | 0 | 0 |
| total turn ms | 174 | 0 | 953 | 1 281 | 7 843 |
| prompt tokens/call | 168 | 1 436 | 1 449 | 1 463 | 1 468 |
| completion tokens/call | 168 | 66 | 97 | 114 | 133 |

Missing token usage: 0 in this run. Route distribution: `CONTINUE` 105,
`COLLECT_IDENTITY` 39, `ESCALATE` 18, `COMPLETE` 6.

Sequence accumulation (mean per valid repetition, cumulative by turn):
`multi-turn-continuity` 3 turns → 4 346 prompt + 257 completion tokens and
2 995 ms of model latency; `long-conversation-memory` 10 turns → 14 481
prompt + 969 completion tokens and 10 365 ms of model latency, with prompt
tokens per call essentially flat (1 438–1 460) because the system prompt is
paid per turn; the cumulative growth is linear in the number of turns.

## Latency and token comparison with Experiment 0006

Both runs use the same model, budget and DEV host class; the corpus grew from
34 to 35 cases (7 paraphrase turns removed from accumulating replays plus a
10-turn sequence added), so counts differ.

| Metric (canonical 0006 → lab run) | 0006 | 0007 |
|---|---|---|
| model p50 / p95 ms | 968 / 1 688 | 954 / 1 281 |
| runtime semantic p95 / max ms | 0 / 16 | 0 / 0 |
| turn total p50 / p95 ms | 953 / 1 437 | 953 / 1 281 |
| prompt tokens p50 / p95 | 1 450 / 1 463 | 1 449 / 1 463 |
| completion tokens p50 / p95 | 97 / 114 | 97 / 114 |

Interpretation: no material regression observed in this sample; prompt and
completion tokens are unchanged, runtime semantic processing remains
negligible, and the model latencies are lower in this sample while provider
variance remains a confounder. No SLO and no Cloud Run or voice E2E inference
is claimed.

## Manual spoken-quality review

The comparator emits the manual review section by case/turn for changed or
failing families and their controls with the rating vocabulary MEETS / CONCERN
/ NOT EVIDENCED. For the self-consistency run there is no changed family and no
candidate to review, so the section is intentionally empty: the procedure is
materialized for the next candidate and remains secondary to runtime legality
and structured business truth.

## Harness defects found and fixed during validation

The real-model validation surfaced evaluator defects that the synthetic tests
now cover permanently:

1. case-level confirmation vocabulary mismatch (`absent` vs `none`);
2. a pre-existing authorized dispatch was not recognized as `authorized`;
3. a replaced challenge lost the conclusion of the previous one;
4. a turn with no caller speech was compared on route instead of `NOT ORACLED`;
5. a revision bump on the same action was classified as a goal change instead
   of `retained` + revision `incremented`;
6. a projection crash when an operation exists without delivery status.

One pre-existing corpus oracle tension was **not** changed (owner oracles were
preserved): `confirmation-affirmative-authorizes` expects
`action_eligibility: eligible` together with `dispatch_count: 1`, but after a
legal dispatch the runtime correctly reports `not_eligible` because a dispatch
already exists. It is flagged for owner reconciliation.

## Limitations

- One model (`gemini-2.5-flash-lite`, `thinking_budget=0`) and a synthetic
  corpus; this is not a quality verdict, a voice validation or a production
  acceptance.
- Boundary events are simulated domain events; the XCALLY/AD wire contract
  remains open (ID-001, XC-001..XC-006).
- Model variance across runs is visible (this run: 11 failing case summaries;
  Experiment 0006 canonical: 9; earlier harness runs of the same baseline
  ranged from 13 to 19) and some cases flip between runs; the lab measures
  and reports that variance instead of hiding it.
- The accepted baseline manifest records the new fingerprint dimensions as
  `unavailable_historical` where Experiment 0006 predates them; reconstructed
  values are marked as such.
- The lab validation run used a dirty working tree (lab changes uncommitted);
  its `working_tree_diff_hash` is recorded so the evidence is attributable.

## Decision

The lab is materialized and validated: deterministic gates green, corpus closed
at 35 cases / 31 families with explicit trial kinds and null oracles, sanitized
run/case/turn evidence, deterministic variant identity, the immutable accepted
baseline manifest, the pure paired comparator with hard/semantic/efficiency
gates, credential-free CI and the manual spoken-quality review procedure.

No product behavior changed, no deploy and no cloud mutation occurred, and no
behavioral improvement is claimed. The lab is **ready for the next real
conversational candidate**, which will be compared against
`21896d12e04da173eda5b0fb4949ac5841812fdd` through the
`conversation-evaluation` pre-voice gate and, after an authorized deploy and a
real call, analyzed with `xcally-call-evidence-analysis`.

## References

- [Accepted baseline manifest](../../evals/conversation/accepted-baseline.json)
- [Conversation corpus](../../evals/conversation/README.md)
- [Experiment 0006: semantic runtime evaluation](0006-semantic-runtime-evaluation.md)
- [Testing standards](../engineering/testing.md)
- [ADR-0010: durable semantic plan](../decisions/0010-durable-semantic-plan-separate-from-authorization.md)
- [Implementation gaps](../gaps.md)
