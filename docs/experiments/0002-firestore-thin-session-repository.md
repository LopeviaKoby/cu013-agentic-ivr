# Experiment 0002: Firestore Thin Session Repository

- Status: Completed
- Lifecycle: Planned → Running → Completed | Failed | Inconclusive
- Authority: Experimental evidence only; not an architectural decision
- Execution owner: OpenCode under a separate assignment
- Companion record: [Experiment 0001](0001-firestore-langgraph-checkpointer.md) (Option A)
- Decision outcome: viable and selected as input to ADR-0009

## Question and hypothesis

Can a thin Firestore session repository — a semantic `SessionRecord` loaded once
per request, a LangGraph turn executed fully in memory without a checkpointer,
and one consolidated save before returning — deliver the same conversational
continuity with one read and one write per turn instead of the per-super-step
checkpoint write amplification measured for Option A?

Hypothesis: **Option B — Thin Firestore Session Repository** is viable for CU013
with lower per-turn RPC counts and write amplification than Option A, an
inspectable document shape, no arbitrary-object serialization and comparable
behavior for continuity, interruption and same-conversation concurrency.

Option B was evaluated as a hypothesis. Firestore was already Accepted as the
durable store; the resulting architecture decision is recorded separately in
ADR-0009.

## Relationship to Experiment 0001

- Option A evidence: LangGraph-native checkpointer over Firestore measured
  2026-09-15 in the `spike/firestore-checkpointer` worktree (28 document writes
  and ~17.6 KB per trivial turn, `aput` p50 949 ms; see 0001 Results).
- This experiment reuses the **same deterministic graph, same synthetic
  scenarios (S0–S6 mapping), same instrumentation seam and the same locked
  versions** so results are comparable: differences must come from the
  persistence mechanism, not from a different workload.
- Neither experiment record adopts architecture by itself. The owner accepted
  Option B through ADR-0009 before any productive implementation.

## Confirmed environment

Same database and identity as Experiment 0001:

```text
project: cu013-xcally-agentic
database: (default)
edition: Standard
mode: Native
region: us-east1
identity: cu013-spike-firestore@cu013-xcally-agentic.iam.gserviceaccount.com
access: roles/datastore.user
local authentication: ADC impersonation
```

Use isolated spike collections in this database. Do not create another
database. `us-east1` is the current baseline, not evidence of the optimal
region.

## Version and security gate

At execution, record before measuring:

- exact Python version;
- exact `langgraph` version (spike lock matches Experiment 0001:
  `langgraph==1.2.11` under the security floor `langgraph>=1.0.10` from
  OSV review 2026-09-15);
- exact `google-cloud-firestore` version (spike lock: `2.29.0`);
- exact resolved lock and advisory review date.

Resolve the lock only in the `spike/firestore-thin-session-repository`
worktree. Do not change production dependencies on `dev` for the experiment.

STOP & REPORT if no compatible secure combination exists.

### Resolved at execution (2026-09-15)

- Python: 3.12.2.
- Experimental lock: `constraints-spike.txt` plus the full frozen environment in
  `requirements-spike.lock`.
- Key versions: `langgraph==1.2.11`, `langgraph-checkpoint==4.2.0`,
  `google-cloud-firestore==2.29.0`, `pydantic==2.13.5` — identical to
  Experiment 0001's locked versions, so both options ran on the same graph
  runtime.
- Identity: `cu013-spike-firestore` through ADC impersonation; no serializer is
  involved in Option B (semantic document persistence only), so the msgpack
  security floor applies only to the Option A side of the comparison.

## Session model (semantic, closed)

One Firestore document per conversation under an isolated spike collection.
The persisted shape is a fixed, whitelisted semantic record — not a graph
state and not SDK objects:

```text
schema_version      int      persistence schema marker (1)
conversation_id     str      synthetic opaque identifier
turn_count          int      completed turns
revision            int      incremented per successful save
identity_validated  bool     durable validation result (never raw inputs)
action              str|null RESET_PASSWORD | UNLOCK_ACCOUNT | synthetic literal
operation_status    str|null synthetic external status literal (NONE = queued)
attempts            int      request_action counter
outcome             str|null queued | escalated | synthetic literal
pending_operation   map|null {operation_id, action, status} status: NONE | CONFIRMED | FAILED
created_at          Timestamp  Firestore-native timestamp (TTL-suitable)
updated_at          Timestamp  Firestore-native timestamp (TTL-suitable)
```

Rules enforced by the harness and tests:

- The document contains exactly the whitelisted keys above; no channel
  values, no checkpoints, no binary blobs, no SDK objects, no arbitrary
  `GraphState` keys.
- Raw DTMF (document ID, date of birth) never reaches the graph state, the
  session record or the document; only the boolean `identity_validated`
  result persists.
- `created_at` / `updated_at` are persisted as datetime values so Firestore
  stores native Timestamps, assessable for a future TTL policy without
  conversion.
- No LangGraph checkpointer is constructed anywhere in the harness; the graph
  is compiled with no `checkpointer` argument and invoked once per turn.

## Minimal experiment design

1. Local harness first: functional tests run against a deterministic
   in-memory document store, no Firestore, emulator or credentials.
2. Turn execution contract (`execute_turn`), the logical load reused from
   Option A:

   ```text
   load session once (1 read; missing → fresh record, no write)
   → build graph input from durable session state + whitelisted turn input
   → LangGraph executes the full representative flow in memory
   → derive the consolidated SessionRecord (closed whitelist)
   → save before returning (1 write)
   ```

3. The graph reproduces Experiment 0001's flow exactly
   (`input → validate_identity → request_action → resolve_action → output`,
   plus identity-failure escalation). One node adaptation is required and is
   recorded here: `validate_identity` keeps the durable
   `identity_validated` value when the turn carries no fresh
   `identity_ok` input, because there is no checkpointer to reload the
   per-turn payload.
4. `identity_ok` is a per-turn transient input and is not durable; durable
   state across turns is `identity_validated`, `action`, `operation_status`,
   `attempts` and `outcome`.
5. Real-Firestore measurement runs the same scenario set with the same RPC
   instrumentation as Option A.
6. After results have been accepted, remove only the experimental documents
   created by the spike when cleanup is appropriate.

The harness, repository and temporary schema are experimental and must not be
presented as production interfaces.

## Synthetic fixtures

Same PII-safe rules as Experiment 0001: synthetic opaque identifiers, boolean
identity-validation results, synthetic action/status literals, deterministic
node results, simulated late external results. No real document numbers,
dates of birth, passwords, tokens, caller data or real XCALLY/AD/TIVIT/SendMail
calls.

## Measurements

For every repeatable run, capture the same event classes as Experiment 0001:

- lines and quantity of repository-specific code;
- Firestore reads, writes and total RPCs (instrumented at the async GAPIC
  callable seam, not estimated);
- approximate session document sizes;
- p50/p95 persistence latency and total run duration;
- behavior with the simulated tool and the full representative flow;
- recovery after an interrupted save (session unchanged; next turn resumes
  from the last persisted session);
- multi-turn continuity with the same `conversation_id`;
- two concurrent requests for the same `conversation_id`;
- stored shape compatibility with TTL/retention (native Timestamp fields);
- PII/secret exposure;
- coupling to LangGraph internals (expected: none — no saver, no checkpoint
  contract).

Do not invent p50/p95 thresholds. Deliver measurements for deliberation and
compare them against the Option A evidence in Experiment 0001.

## Stop conditions

### Persistence model

STOP if viability requires:

- persisting SDK objects, LangGraph checkpoints or arbitrary `GraphState`;
- binary/opaque serialization of the session;
- per-node or per-super-step writes in the repository path;
- a persistence model that cannot be inspected as plain semantic fields.

### Write amplification and contention

Do not assume a universal one-write-per-second document limit.

STOP on relevant `ABORTED`, `RESOURCE_EXHAUSTED`/429, persistent internal
retries or material persistence latency for voice.

### Concurrency semantics

Two concurrent turns on one `conversation_id` execute in memory and race on
the single save. The spike records last-writer-wins whole-document behavior
and validates completion and intactness, not serializability. A future
transaction/version scheme is a production design question, not part of this
harness. STOP if the measured behavior corrupts or mixes turns instead of
resolving to one intact writer.

### Security

STOP on any raw PII/secret exposure or need for permissions beyond the
explicitly authorized experiment scope.

## TTL limitation

Same as Experiment 0001: `roles/datastore.user` does not authorize TTL policy
administration. The harness records native Timestamp fields so a future TTL
policy can target `updated_at`; end-to-end TTL enforcement stays a recorded
limitation.

## Results

Completed. Real-Firestore benchmarks were executed on 2026-09-15.

### Local harness evidence (2026-09-15)

Harness implemented in this worktree (experimental, not a production interface):

- package `cu013_spike_session` under `src/`, separate from the future runtime namespace;
- semantic `SessionRecord` and closed Firestore document mapping (`src/cu013_spike_session/session.py`);
- turn contract: load once → in-memory LangGraph turn (no checkpointer) → consolidate → save before returning (`turns.py`, `repository.py`);
- graph identical to Experiment 0001's, with the one documented `validate_identity` adaptation (`graph.py`);
- narrow async document seam and deterministic in-memory double (`store.py`, `memory_store.py`), mirroring Option A's surface;
- measurement harness with the same RPC instrumentation and scenario structure (`src/cu013_spike_session/measure.py`), not executed against Firestore;
- functional tests: 33 passing (`python -m pytest`), covering round-trip, multi-turn continuity, interruption before save, same-`conversation_id` concurrency, simulated pending operation and PII isolation; Ruff check, Ruff format check and MyPy strict clean (`mypy src`);
- the stored shape is a flat whitelisted semantic document with native Timestamp fields; no bytes, no SDK objects, no graph state.

### Real-Firestore measurement (2026-09-15)

Executed from the host that runs OpenCode against the authorized database:

```text
project: cu013-xcally-agentic
database: (default)
region: us-east1
identity: cu013-spike-firestore@cu013-xcally-agentic.iam.gserviceaccount.com
local authentication: ADC impersonation
canonical full-run prefix: cu013spike_meas_20260915T234347ZB
superseded prefixes: cu013spike_meas_smokeB1, cu013spike_meas_smokeB2,
  cu013spike_meas_smokeB3, cu013spike_meas_20260915T234054ZB,
  cu013spike_meas_20260915T234202ZB (pre-fix and pre-S5 iterations)
```

Instrumentation: the same seam as Experiment 0001 — one event per logical RPC
at the async GAPIC transport callable surface (`_wrapped_methods`), document
reads counted from streamed `BatchGetDocuments` responses, document writes from
`Commit` write counts, document sizes from stored payloads, retries from
`google-api-core` DEBUG retry records. Raw JSON evidence was written outside
the repository; the Firestore documents remain under the recorded prefixes.

#### Harness defects found during the first execution

Both defects were real harness defects that invalidated the affected
measurements; they were fixed before the canonical run and only the affected
measurements were repeated.

1. **Invalid document path scheme.** The repository initially built
   `cu013spike_meas_x/sessions/{conversation_id}`: an odd number of Firestore
   path elements, rejected by the real backend with
   `ValueError: A document must have an even number of path elements`. The
   in-memory double never caught it because paths are plain dict keys.
   Cause: path scheme designed against the in-memory double. Impact: every
   session-path operation failed in the first smoke run (S1 0/2).
   Fix: the prefix becomes one top-level collection
   (`{prefix}_sessions`), so a reference is `collection/document`; a
   regression test asserts the even element count.

2. **Read-RPC undercount in the instrumentation seam.**
   `AsyncDocumentReference.get` returns after the first streamed item of
   `batch_get_documents` and abandons the stream before StopAsyncIteration,
   so the stream-completion hook used for RPC event emission never fired and
   load RPCs went unrecorded (pre-fix S1/S2/S4 reported 1 RPC per turn instead
   of 2; loads happened — store events prove it — but were invisible to the
   RPC layer). Cause: the harness reused Option A's stream-completion emission
   without covering the abandoned single-item stream pattern that
   `document().get()` introduces. Impact: reads/turn, read latency and
   total RPCs per turn were undercounted in all session-path scenarios.
   Fix: `FirestoreDocumentStore.get` routes the read through the fully
   drained `get_many` path (same single document read billed); measurement
   repeated.

Additionally, scenario S5 (`s5_pending_operation_resolution`) was added to
cover the mandated pending-operation measurement, and the continuity scenario
now records per-turn states in the report. These are harness completeness
changes, not defects.

#### Representative flow - 30 fresh conversations (S1)

Flow: load once → `validate_identity` → `request_action` (simulated tool) →
`resolve_action` → consolidate → save before returning.

30 of 30 turns succeeded. Per turn: **2 logical RPCs (1 `BatchGetDocuments`
read, 1 `Commit` write), 1 document read, 1 document write and 630 committed
bytes on average**. Session document sizes p95 ~470 bytes.

| Metric (Option B) | p50 | p95 |
|---|---|---|
| Full turn (load + graph + save) | 485.5 ms | 941.6 ms |
| Load (`BatchGetDocuments`) | 231.8 ms | 703.8 ms |
| Save (`Commit`) | 240.1 ms | 321.3 ms |

Total across the 30 runs: 30 document writes and ~18.9 KB committed.

#### Continuity - two turns on one conversation

Both turns succeeded. Turn 2 loaded the persisted session (turn count 1 → 2,
`attempts` carried over, the queued operation identity preserved across the
turn boundary) and saved one consolidated document. Per turn: 2 RPCs, 1 read,
1 write, ~623 bytes; run p50 448.4 ms / p95 485.3 ms. After both turns the
conversation holds exactly **one session document** (2 revisions, latest kept).

#### Interruption before save and recovery

The injected save failure produced the intended `SessionPersistenceError`
(the in-memory turn result was discarded) and the persisted document remained
byte-identical to the last successful save (`persisted_unchanged: true`). The
recovery turn resumed from the last persisted session and completed
(turn count 2) keeping the same queued operation identity. Per successful
turn: 2 RPCs, 1 read, 1 write, ~415 bytes.

#### Same-`conversation_id` concurrency

Two concurrent turns on one conversation both completed (~500 ms total):
4 RPCs, 2 reads, 2 writes, 1,246 committed bytes. The final document is intact
and matches exactly one of the two writers (last-writer-wins at whole-document
granularity, `document_whitelist_ok: true`). No `ABORTED`, no 429, no retries.
This validates completion and intactness, not serializability.

#### Pending operation (simulated late result)

Queue turn created the operation (`NONE`); the next turn applied the simulated
`CONFIRMED` result and persisted it with the same operation identity
(`pending_operation.status: CONFIRMED`, `operation_status: CONFIRMED`).
Per turn: 2 RPCs, 1 read, 1 write, ~627 bytes; run p50 480.5 ms / p95 494.8 ms.

#### Stored shape and TTL compatibility

The sampled session document contains exactly the whitelisted keys, with
`created_at` and `updated_at` stored as native Firestore Timestamps, ~488
bytes, zero binary values and `pending_operation` as a flat map. A future TTL
policy can target `updated_at` directly. TTL administration itself is not
authorized for the spike identity and was not configured.

#### Errors, retries, contention

Across all scenarios: zero RPC failures, zero internal SDK retries, no
`ABORTED`, no `RESOURCE_EXHAUSTED`/429, and no stop condition triggered. The
only observed failures were the two designed injected save failures in S3.

#### PII, secrets and coupling

No raw identity values, secrets, binary values or SDK objects in any stored
document; the persisted shape is the closed semantic whitelist. The harness
has zero coupling to LangGraph internals: no checkpointer, no saver contract,
no serializer, no checkpoint IDs or namespaces; the graph is compiled without
a checkpointer and the persisted state is the semantic record only.

#### Direct comparison against Option A (Experiment 0001, same day, same
lock)

| Metric (per trivial turn) | Option A (checkpointer) | Option B (thin repository) |
|---|---|---|
| Logical RPCs | 29 (28 Commit + 1 RunQuery) | 2 (1 BatchGet + 1 Commit) |
| Document writes | 28 | 1 |
| Document reads | 0 (fresh) / 5.5 (turn 2+) | 1 |
| Committed bytes | 17,624 | 630 |
| Run p50 / p95 | 4,738 / 4,805 ms | 485.5 / 941.6 ms |
| Persistence (aput+aput_writes p50) | ~949 ms + ~687 ms | ~240 ms (Commit) |
| Read (aget_tuple p50) | 235 ms | ~232 ms (BatchGet) |
| Documents after 2 turns | 52, none deleted | 1 |
| Crash recovery | resume mid-graph exactly | turn restarts from last save |
| Concurrency model | per-checkpoint races | whole-document last-writer-wins |
| LangGraph coupling | version-locked saver + serializer | none |
| TTL field | ISO-8601 string (not TTL-suitable) | native Firestore Timestamp |

Caveats: Option A's turn was measured cold (every run re-created checkpoints);
Option B's read cost is one document get, billed the same for found or
missing documents. Percentiles come from the same instrumentation seam and
the same synthetic flow, but the two mechanisms execute different write
patterns by design; treat the comparison as mechanism-level, not absolute.

## Limitations

- Same-thread concurrency is last-writer-wins at document granularity; no
  transaction/optimistic-version scheme is implemented in the spike.
- A crash mid-turn is not resumable mid-flow (no checkpointer); the next
  request restarts the turn from the last persisted session. This is the
  core behavioral trade compared against Option A.
- The graph restarts every turn from the durable state; any future
  per-turn context the LLM needs must be part of the semantic record.
- The turn-flow continuity shown here covers the deterministic synthetic
  flow; real LLM-driven turns will add model latency on top of these numbers.
- TTL enforcement is not authorized by the spike identity.
- SendMail stays Deferred; no XCALLY, AD/TIVIT or SendMail integration is
  exercised by this harness.

## Conclusion

Option B (Thin Firestore Session Repository) is **viable** at the experimental
level: it met all measured criteria with no stop conditions, no PII/secret
exposure and no LangGraph coupling, with 28× fewer document writes and ~28×
fewer committed bytes per trivial turn than Option A, and roughly a 10× lower
turn latency profile in the same flow. The accepted trade is turn-level crash
restart (no mid-graph resume) and last-writer-wins concurrency at
whole-document granularity.

ADR-0009 selected this option for the CU013 production voice path. The clean
implementation will derive its contract from the ADR and specs; the spike
package, benchmark instrumentation, doubles, fixtures and exact experimental
lock are not production interfaces.

## Adopted ADR

[ADR-0009 — Usar un repositorio delgado de sesiones en Firestore](../decisions/0009-use-thin-firestore-session-repository.md).

## Official references consulted for planning

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence): checkpointer-free in-memory execution semantics.
- [Firestore best practices](https://docs.cloud.google.com/firestore/native/docs/best-practices): workload-dependent contention and write behavior.
- [Firestore TTL](https://docs.cloud.google.com/firestore/native/docs/ttl): retention behavior and permissions, consulted 15-09-2026.
