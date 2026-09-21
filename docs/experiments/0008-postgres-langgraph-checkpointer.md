# Experiment 0008: PostgreSQL + LangGraph AsyncPostgresSaver Checkpointer

- Status: Completed
- Lifecycle: Planned → Running → Completed | Failed | Inconclusive
- Authority: Experimental evidence only; not an architectural decision
- Execution owner: OpenCode under an explicit owner authorization covering this spike
- Decision outcome: **KEEP THIN FIRESTORE**. The checkpointer is technically viable
  and leak-free, but this spike did not demonstrate a conversational or operational
  property that the accepted thin repository cannot provide with less cost and
  complexity. No ADR or specification changes result from this record.

## Question and hypothesis

Can an `AsyncPostgresSaver` over a minimal Cloud SQL PostgreSQL instance provide
durable conversational memory for CU013 — bounded, PII-free, voice-path viable —
while the accepted runtime keeps owning legality, identity, confirmation,
dispatch and external truth, and while the operational cost stays controlled?

Hypothesis: a durable-only graph projection over the LangGraph PostgreSQL
checkpointer delivers verified continuity (restart, interrupt/resume, correction,
lateral question) without storing transcripts or PII, with a measurable latency
profile compatible with the provisional voice evidence, and with a bounded cost
for a single authorized window.

## Confirmed environment

```text
project: cu013-xcally-agentic
region: us-east1
instance: cu013-pg-checkpoint-spike-dev (POSTGRES_16, ENTERPRISE, db-f1-micro,
          ZONAL, 10 GiB PD_SSD, storageAutoResize off, backups off, PITR off,
          public IPv4, sslMode ENCRYPTED_ONLY, serverCaMode GOOGLE_MANAGED_INTERNAL_CA)
database/user: cu013_spike (limited role; database owner default cloudsqlsuperuser)
connectivity: Cloud Run built-in Cloud SQL proxy socket; local Auth Proxy v2.25.4
runtime identity: cu013-runtime-dev (cloudsql.client conditioned to the instance;
                  secretmanager.secretAccessor on the spike secret only)
secret: cu013-pg-spike-password-dev (automatic replication; version 1; destroyed)
Cloud Run: cu013-pg-spike-dev revision 00005-q9p (also 00001-qz4/00002-rvj/00003-nv6
           during iteration), us-east1, concurrency 1, max instances 1, min 0
image: us-east1-docker.pkg.dev/cu013-xcally-agentic/cu013-containers-dev/
       cu013-pg-spike-dev:spike-21896d1b (digest sha256:f426db891f958500fc70132694a70b9e3661d365ffd8ab7aab8d3755cd4d37b7)
harness worktree: cu013-pg-spike (detached at 21896d1), package spike/
```

## Version and security gate

- Python 3.12.2; experimental lock `spike/requirements-spike.lock` (75 pins).
- Baseline pins identical to `requirements.lock`: `langgraph==1.2.11`,
  `langgraph-checkpoint==4.2.0`, `google-cloud-firestore==2.30.0`,
  `pydantic==2.13.5`, `orjson==3.12.0`.
- Added and pinned: `langgraph-checkpoint-postgres==3.1.2`, `psycopg==3.3.5`,
  `psycopg-binary==3.3.5`, `psycopg-pool==3.3.1`, `tzdata==2026.4`.
- OSV querybatch over the five new pins, 2026-09-17: no advisories.
- The harness never uses `pickle_fallback`; the full stored shape was decoded
  with the saver's own serializer during the leak scan (0 undecodable values).

## Minimal experiment design

- `spike/harness/channels.py`: eleven JSON-safe durable channels
  (`conversation_id`, `turn_count`, `revision`, `goal`, `identity`,
  `confirmation`, `dispatch`, `external_operation`, `memory`, `created_at`,
  `updated_at`). Every value is a plain JSON type; nothing else is durable.
- `spike/harness/graph.py`: a two-node graph over the accepted deterministic
  runtime (`app.session.turns.advance_turn`, reused unchanged). The transcript,
  the boundary events and the model proposal travel in the LangGraph **runtime
  context** (`context_schema` / `Runtime[TurnContext]`), which is run
  configuration: it never enters a channel and never reaches a checkpoint.
- `spike/harness/memory.py`: bounded memory projection — procedure step code,
  bounded clarification code, bounded correction counter, turn counter. No
  conversational content, no PII.
- Two arms over the **same** graph, model, prompt and projection: the thin
  document arm (Firestore document = closed `SessionRecord` whitelist plus the
  `memory` map) and the checkpointer arm (same channels persisted by
  `AsyncPostgresSaver` over a two-connection pool).
- `spike/harness/scenarios.py` implements the mandated sequence (request →
  identity → lost confirmation → lateral question → return → correction that
  invalidates the challenge → fresh confirmation → single dispatch → failure
  result), a long variant with 12 lateral turns and 4 trailing corrections,
  same-thread concurrency, interrupt/resume across a process restart, failure
  before the durable update, and sentinel leak scanning.
- The experimental service (`spike/service.py`) serves the accepted HTTP
  boundary unchanged; the storage arm is selected per request through
  `X-CU013-Spike-Arm` so both arms share one warm instance, one revision and
  one configuration.

## Sentinels and leak scan

Four sentinel strings simulate exactly what must never become durable: a
document number, a date of birth, a password-like token and an e-mail. They
appear only in synthetic transcripts and one synthetic model message. The scan
covered, with **zero hits**:

- `checkpoints.checkpoint::text` and `metadata::text` (JSONB);
- `checkpoint_blobs.blob` and `checkpoint_writes.blob` raw bytes;
- every blob and every write decoded with the saver serializer and traversed
  recursively;
- every Firestore control document (41 documents, 41 decoded values);
- stored channel keys: only the nine durable keys plus LangGraph internal
  `branch:to:*` channels; metadata contains only `parents`, `source`, `step`.

Final canonical evidence: 387 checkpoints, 663 blobs and 2,130 writes scanned
(3,180 decoded values, 0 undecodable) with no sentinel and no transcript.
Post-cleanup verification: 0 stored rows and 0 control documents.

## Results — deterministic phase

Executed from the DEV host against real Cloud SQL (through the Auth Proxy) and
real Firestore, evidence `20260918T003001Z_deterministic.json`; local-only
iteration first against Docker `postgres:16`.

- Gates: `python -m pytest` 248 passed (193 accepted + 20 spike + 35 lab),
  Ruff check/format clean, MyPy strict clean over `app` (18 files), corpus
  `--validate-only` 35 cases / 0 problems.
- Every asserted durable property held in both arms: the mandated sequence, the
  long conversation (corrections bounded, goal revisions 3→6), lateral-turn
  clarification codes, challenge invalidation on correction, single dispatch
  and no re-dispatch after the failure result, load/restart continuity,
  same-thread concurrency (both turns completed, final state intact and
  last-writer), failure before persist (durable state unchanged, retry resumes)
  and interrupt/resume (static breakpoint after `run_model`; durable state
  untouched until resume; on resume the transient input is re-delivered through
  the runtime context because it was never persisted — a recorded property, not
  a defect).
- Storage operations per candidate turn over the canonical run: ~1.7
  `aget_tuple`, ~3.3 `aput` and ~2.5 `aput_writes` (host through the public
  Auth Proxy: p50 `aget_tuple` ~110-125 ms, `aput` ~125 ms, `aput_writes`
  ~344-360 ms). Control arm: 1 load and 1 save per turn.
- Checkpoint read model: the latest `aget_tuple` is the resume surface; no
  time-travel or global listing is used by the harness.

## Results — latency with the real model (Cloud Run, warm)

Canonical run `bench2`: 5 warmups per arm plus 30 measured turns per arm,
alternating arms on every request, one warm instance, revision `00005-q9p`,
service configuration identical for both arms.

| Metric (client wall, ms) | candidate | baseline |
|---|---:|---:|
| p50 | 937.5 | 1,046.5 |
| p95 | 1,094.0 | 1,297.0 |
| max | 14,282 | 1,375 |
| failures | 1 (HTTP 503) | 0 |

Server-side segmentation (same window, same revision, PII-safe log lines):

| Segment (ms) | n | p50 | p95 |
|---|---:|---:|---:|
| model (shared) | 70 | 724.9 | 948.2 |
| handler (shared) | 70 | 790.5 | 1,096.9 |
| `saver_aget_tuple` (candidate) | 70 | 3.1 | 4.8 |
| `saver_aput` (candidate) | 138 | 13.1 | 23.4 |
| `saver_aput_writes` (candidate) | 104 | 16.0 | 31.9 |
| `session_load` (baseline) | 35 | 19.8 | 50.3 |
| `session_save` (baseline) | 35 | 32.1 | 64.1 |

Reading: in-region storage time is small for both engines. The checkpointer
does ~6.9 storage calls per turn (~120 ms of DB time) against ~2 calls (~52 ms)
for the thin repository; both remain far below the model segment. End-to-end
arm differences at n=30 are within provider variance; the single 503 was a
14.05 s model call (`provider`), recorded as INFRA, not as a checkpointer
defect. Prompt tokens 100,733 over 70 calls (~1,439/call).

## Results — conversational evaluation (real model, paired)

Procedure: `conversation-evaluation` skill. Deterministic gates green first.
The spike worktree's evaluator was extended with an experimental
`--memory-aware` path (the accepted `SYSTEM_INSTRUCTIONS` are byte-identical;
the only difference is two extra state lines, `paso_activo` and
`aclaracion_pendiente`). Both arms ran the same evaluator, corpus, model and
runtime; declared variables: `memory_state_block`, `memory_renderer_hash`;
declared confounder: `working_tree_diff_hash` (untracked run artifacts).

- Families (affected plus controls): long-conversation-memory,
  multi-turn-continuity, side-question-before-action, side-question-during-plan,
  goal-switch, goal-correction, goal-cancellation,
  confirmation-stale-after-goal-revision, direct-supported-request,
  identity-unvalidated. Three repetitions per trial, one warmup.
- Artifacts: baseline `conversation-eval-20260918T004357-86c1ec50.json`,
  candidate `conversation-eval-20260918T004545-d8cc8238.json`, baseline
  focused INFRA rerun `conversation-eval-20260918T004813-8de24c11.json`,
  comparison
  `conversation-eval-20260918T004357-86c1ec50__conversation-eval-20260918T004545-d8cc8238.comparison.json`.
- Paired evidence after the focused reruns: 48 valid pairs, 0 incomplete,
  0 INFRA pairs.
- **Critical gate: no new executed critical violation in either arm**
  (`critical_gate.new = []`, `reject = false`): no unauthorized dispatch,
  duplicate side effect, false result, PII/DTMF leak, invalid identity
  authorization, stale challenge reuse or illegal handoff.
- Verdict: **NEEDS OWNER DECISION** — 6 unrelated regressions, 4 targeted
  regressions (all bidirectional PASS↔FAIL flips consistent with sampling
  variance), and efficiency deltas: prompt tokens p50 +20 per call
  (1,448 → 1,468, explained by the two extra state lines), model latency p50
  +31 ms / p95 +109 ms (provider variance confounder).
- No systematic memory benefit was demonstrated at the conversational level;
  the bounded code-only memory adds tokens without a measurable property gain
  in this sample. Spoken-quality review was not executed: the sanitized
  artifacts deliberately exclude message text, so it requires the owner over
  unsanitized output. It remains open and is a reason the semantic verdict
  cannot be ACCEPT.

## Cost

Single authorized window: instance alive ~58 minutes, stopped and deleted.
Incremental estimate with published `us-east1` rates (db-f1-micro compute
0.0105 USD/h, SSD 0.000232877 USD/GiB·h, IPv4 0.01 USD/h while it exists):
**≈0.022 USD** for Cloud SQL; Cloud Run and Vertex calls add a small amount
well below the 3 USD limit. Billing-invoice verification remains with the owner
(no billing API was enabled or queried). Stopping alone did not satisfy the
budget only if the instance is retained with a public IP; deletion at window
close does.

## Deviations and defects found

- `gcloud sql users set-password --prompt-for-password` does not read a piped
  stdin without a TTY and blocked the first provisioning attempt. The same
  operation was executed through the Cloud SQL Admin API `users.update` with
  the owner access token and generated passwords held in process memory only:
  no secret on any command line, file, log or artifact. The block was reported
  and the plan-compliant equivalent path documented.
- The HEAD `pyproject.toml` lacks the `"evals/*.py" = ["E402"]` ignore that the
  current main worktree carries; the spike worktree adds it locally.
- `spike/tests/__init__.py` collided with the root `tests` package under
  pytest's prepend import mode and was removed.
- psycopg async needs a selector event loop on Windows; the CLI sets
  `WindowsSelectorEventLoopPolicy` on win32 only.
- `psycopg_pool.AsyncConnectionPool.wait()` raises after `close()`; the harness
  closes and does not wait.
- The interrupt scenario initially invoked a graph built before the breakpoint
  was configured; the harness now rebuilds the graph for the breakpoint and
  again for the resume.
- `sqladmin.googleapis.com` was enabled for this spike and was left enabled at
  cleanup: it is a project-level service setting, not an enumerated spike
  resource, and disabling it was not part of the authorized plan.
- The experimental image tags were deleted after the service was removed.

## Limitations

- `db-f1-micro` has no SLA; the pool is bounded to two connections and the
  service to `max_instances=1`, `concurrency=1`.
- The measured latency is per-turn in-region storage and model time; the
  complete voice budget (XCALLY/ASR/TTS) is still not distributed (FS-002).
- The semantic comparison has 3 repetitions per trial; provider variance
  (including two provider INFRA failures in the baseline arm and one 503 in the
  candidate arm) dominates small deltas.
- The memory projection is intentionally content-free; it is not a
  conversational memory contract and cannot demonstrate semantic memory value.
- No production change was made: `app/`, specs, ADRs and `requirements.lock`
  are untouched; the harness lives only in the experimental worktree.

## Conclusion

The PostgreSQL checkpointer is **technically viable** for the tested
projection and passed every deterministic, security and recovery gate with
zero sentinel leaks across all four checkpoint tables and the control
documents. In-region storage latency per turn is small in absolute terms.

However, the spike did **not** demonstrate a property the accepted thin
Firestore repository cannot provide: the same durable content over Firestore
behaved identically, the checkpointer multiplied storage operations per turn
(~6.9 vs 2), the real-model paired evaluation showed no systematic memory
benefit with +20 prompt tokens per call and bidirectional variance
(NEEDS OWNER DECISION, no new critical violations), and the semantic target
("long-conversation memory, lateral question and correction") is a function of
richer conversational content, not of the storage engine.

Per the plan's decision vocabulary the outcome is **KEEP THIN FIRESTORE**.
ADRs 0002, 0009 and 0010 remain valid; adopting PostgreSQL later would first
require a richer model-owned memory contract, a new paired evaluation that
demonstrates it, and an explicit owner decision reconciling those authorities.

## Cleanup record

- 41 synthetic Firestore control documents deleted one by one by exact id; 387
  stored checkpoints deleted for 42 threads by exact id (no wildcards, no
  collection-group deletes); post-cleanup scans: 0 documents, 0 rows.
- `cu013-pg-spike-dev` service deleted; both spike image digests deleted from
  the existing Artifact Registry repository.
- IAM restored: conditional `cloudsql.client` binding and the spike secret
  accessor removed; runtime service account lists only `aiplatform.user` and
  `datastore.user` again.
- Secret version 1 destroyed and the secret deleted; no service account
  created; no VPC, pooler, HA, replica, backup or PITR configured.
- Cloud SQL instance stopped (verified `STOPPED`/`NEVER`) and deleted; local
  Auth Proxy process stopped; local Docker PostgreSQL container removed.

## Official references consulted for planning

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [AsyncPostgresSaver implementation](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/checkpoint/postgres/aio.py)
- [Postgres saver migrations](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/checkpoint/postgres/base.py)
- [Cloud SQL instance settings](https://docs.cloud.google.com/sql/docs/postgres/instance-settings)
- [Cloud Run Cloud SQL connections](https://docs.cloud.google.com/sql/docs/postgres/connect-run)
- [Cloud SQL IAM conditions](https://docs.cloud.google.com/sql/docs/postgres/iam-conditions)
- [Cloud SQL pricing](https://cloud.google.com/sql/pricing)
- [Psycopg async pool](https://www.psycopg.org/psycopg3/docs/api/pool.html)
- [users.update (Admin API)](https://docs.cloud.google.com/sql/docs/postgres/admin-api/rest/v1beta4/users/update)
- [databases.insert (Admin API)](https://docs.cloud.google.com/sql/docs/postgres/admin-api/rest/v1beta4/databases/insert)
