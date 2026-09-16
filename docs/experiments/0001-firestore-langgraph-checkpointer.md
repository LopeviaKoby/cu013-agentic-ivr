# Experiment 0001: Firestore/LangGraph Checkpointer

- Status: Completed
- Lifecycle: Planned → Running → Completed | Failed | Inconclusive
- Authority: Experimental evidence only; not an architectural decision
- Execution owner: OpenCode under a separate assignment
- Decision outcome: technically viable; not selected for the CU013 production voice path

## Question and hypothesis

Can a custom async Firestore checkpointer implement the public, version-matched LangGraph checkpoint contract with acceptable complexity, inspectable data, safe serialization and measured behavior for CU013?

Hypothesis: **Option A — LangGraph-native persistence over Firestore** is viable without arbitrary-object serialization, excessive write amplification, material voice-path latency or a storage model dominated by history features CU013 does not use.

Option A was evaluated as a hypothesis. Firestore was already Accepted as the durable store; the resulting architecture decision is recorded separately in ADR-0009.

## Confirmed environment

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

Use isolated spike collections in this database. Do not create another database. `us-east1` is the current baseline, not evidence of the optimal region.

## Version and security gate

At execution, record before writing the saver:

- exact Python version;
- exact `langgraph` and `langgraph-checkpoint` versions;
- exact `google-cloud-firestore` version;
- exact resolved lock and advisory review date;
- exact public `BaseCheckpointSaver` async contract for those versions;
- applicable safe-deserialization mechanism.

Resolve a patched, compatible lock only in the `spike/firestore-checkpointer` worktree. Do not change production dependencies on `dev` for the experiment.

STOP & REPORT if no compatible secure combination exists.

### Resolved at execution (2026-09-15)

- Python: 3.12.2.
- Experimental lock: `constraints-spike.txt` plus the full frozen environment in `requirements-spike.lock`.
- Key versions: `langgraph==1.2.11`, `langgraph-checkpoint==4.2.0`, `google-cloud-firestore==2.29.0`, `langchain-core==1.6.3`, `ormsgpack==1.12.2`.
- Advisory review date: 2026-09-15 against the OSV API. The resolved pins report zero known advisories.
- Public async contract implemented: `BaseCheckpointSaver.aget_tuple`, `alist`, `aput` and `aput_writes` for `langgraph-checkpoint` 4.2.0.
- Safe deserialization: `JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=None)`. The saver defaults to this strict serializer; `LANGGRAPH_STRICT_MSGPACK` is the version-equivalent environment switch.

The baseline installed on `dev` before the spike (`langgraph==0.6.11`, `langgraph-checkpoint==3.0.1`) is **not** a patched combination:

- `GHSA-g48c-2wqr-h844` (langgraph, unsafe msgpack deserialization): fixed in `1.0.10`.
- `GHSA-fjqc-hq36-qh5p` (langgraph-checkpoint, unsafe JSON deserialization): fixed in `4.1.1`.
- `GHSA-mhr3-j7m5-c7c9` (langgraph-checkpoint, `BaseCache` pickle-fallback RCE): fixed in `4.0.0`.

The former `dev` specifier `langgraph>=0.2.0,<1.0.0` could not be satisfied by a patched release. The reconciliation that accepted ADR-0009 raised the production floors to `langgraph>=1.0.10` / `langgraph-checkpoint>=4.1.1`; the exact production lock remains deferred to the first minimal implementation.

## Minimal experiment design

1. Prefer local harness/emulator for fast functional iteration when useful.
2. Implement only the custom async saver surface required by the locked public contract.
3. Run a deterministic representative flow:

   ```text
   input
   → node
   → simulated tool
   → state update
   → additional node/decision
   → output
   ```

4. Repeat measurements against real Firestore `us-east1` using only the spike SA and a unique isolated collection prefix.
5. Exercise interruption/recovery, same-thread continuity and two concurrent requests for the same thread.
6. Exercise the applicable async equivalents of `get_tuple`, `list`, `put`, `put_writes` and pending writes.
7. Record actual RPCs and document reads/writes rather than estimating from graph steps.
8. After results have been accepted, remove only the experimental Firestore records/documents created by the spike when cleanup is appropriate.

The harness, saver and temporary schema are experimental and must not be presented as production interfaces.

This Markdown experiment record remains versioned as historical evidence. It evolves through `Planned` → `Running` → `Completed` | `Failed` | `Inconclusive` and must not be deleted when Firestore test data is cleaned up.

## Synthetic fixtures

Use only synthetic opaque identifiers and non-sensitive state. Fixtures may represent:

- a synthetic thread and run;
- a boolean identity-validation result, never raw identity inputs;
- either account action;
- a simulated external status such as an observed literal;
- deterministic node/tool results;
- an interruption point and resume input.

Prohibited fixture content:

- real DNI/document numbers;
- real dates of birth;
- passwords or temporary passwords;
- API keys or tokens;
- real caller email/phone data;
- real AD/TIVIT, XCALLY or SendMail calls.

## Measurements

For every repeatable run, capture:

- lines and quantity of saver-specific code;
- Firestore reads, writes and total RPCs;
- approximate checkpoint and pending-write sizes;
- p50/p95 persistence latency and total run duration;
- behavior with a tool and multiple nodes;
- recovery after interruption;
- continuity with the same thread ID;
- two concurrent requests for the same thread;
- `list`, `get_tuple` and pending writes behavior;
- compatibility of the stored shape with TTL/retention;
- PII/secret exposure;
- coupling to LangGraph internals.

Do not invent p50/p95 thresholds. Deliver measurements for deliberation.

## Stop conditions

### Serialization

Use the version-effective `JsonPlusSerializer` behavior. Enable `LANGGRAPH_STRICT_MSGPACK` or the version-equivalent allowlist mechanism when applicable.

STOP if viability requires:

- `pickle_fallback=True`;
- arbitrary Python-object serialization;
- significant custom serialization;
- opaque binary/schema choices that obstruct inspection, TTL or security;
- approaching Firestore document limits materially;
- more serializer design than useful CU persistence.

### Write amplification and contention

Do not assume a universal one-write-per-second document limit.

STOP on relevant `ABORTED`, `RESOURCE_EXHAUSTED`/429, persistent internal retries, disproportionate amplification, material persistence latency for voice or artificial domain fragmentation required only by the saver.

### History and pending writes

STOP if correct support of the version-effective saver contract requires extensive composite indexes, complex subcollections, costly unused queries or a broad time-travel/history implementation that dominates the design.

### Security

STOP on any raw PII/secret exposure or need for permissions beyond the explicitly authorized experiment scope.

## TTL limitation

Assess whether checkpoint documents can carry an inspectable timestamp suitable for a future TTL policy. Do not configure TTL during this spike without separate IAM authorization: `roles/datastore.user` does not by itself authorize TTL policy administration.

Lack of an end-to-end TTL policy test does not block the core saver experiment, but must remain a recorded limitation.

## Results

### Local harness evidence (2026-09-15)

Harness implemented in this worktree (experimental, not a production interface):

- package `cu013_spike_firestore` under `src/`, separate from the future runtime namespace;
- deterministic `StateGraph` with synthetic, PII-free state (`src/cu013_spike_firestore/graph.py`, 77 lines);
- minimal async saver (`src/cu013_spike_firestore/checkpointer.py`, 327 lines including docstrings and schema notes, 15 definitions);
- narrow async document seam (`store.py`, 103 lines) with a Firestore implementation and a deterministic in-memory double (`memory_store.py`, 59 lines);
- measurement harness (`src/cu013_spike_firestore/measure.py`, 1271 lines, scaffolding only);
- functional tests: 33 passing (`python -m pytest`); Ruff check, Ruff format check and MyPy strict clean (`mypy src`).

Observed properties from the local harness (no Firestore involved):

- Async saver surface exercised: `aput`, `aget_tuple`, `alist`, `aput_writes` and pending-write reads.
- Flow exercised: input → `validate_identity` → simulated `request_action` → `resolve_action` → output, plus identity-failure escalation.
- Interruption before `request_action` and resume through the same thread config.
- Same-thread continuity across two invocations.
- Two concurrent `aput` calls for the same thread with distinct checkpoint IDs, read back without loss.
- Stored shape: one checkpoint document, one document per new channel version and one document per pending write. Writes are nested under the checkpoint document.
- Checkpoint metadata is stored as a native map; the checkpoint payload is stored as a typed `(type, bytes)` pair and channel values as separate typed documents, so unchanged channels are not rewritten.
- Arbitrary Python objects are rejected by the strict serializer; no `pickle` fallback is enabled.

### Real-Firestore measurement (2026-09-15)

Executed from the host that runs OpenCode against the authorized database:

```text
project: cu013-xcally-agentic
database: (default)
region: us-east1
identity: cu013-spike-firestore@cu013-xcally-agentic.iam.gserviceaccount.com
local authentication: ADC impersonation
full-run prefix: cu013spike_meas_20260915T222508Z
smoke prefixes: cu013spike_meas_smoke*_* (superseded iterations)
```

Security gate re-confirmed inside the measurement process: `LANGGRAPH_STRICT_MSGPACK=true`, `STRICT_MSGPACK_ENABLED=True`, saver `JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=None)`, arbitrary-object serialization rejected, `pickle` payload refused, 49 safe msgpack types and `os.system`/`subprocess.Popen` outside the allowlist.

Instrumentation (experimental harness only): one event per logical RPC at the async GAPIC callable seam (`_wrapped_methods`); document reads counted from `BatchGetDocuments` and `RunQuery` streamed responses; document writes from `Commit` write counts; document sizes from stored payloads; retries from `google-api-core` DEBUG retry records. Caveats: a query that returns no documents may still bill a minimum of one read, and retries hidden inside the SDK are only visible through those log records. Raw JSON evidence was written outside the repository; the Firestore documents remain under the recorded prefixes.

#### Representative flow - 30 fresh threads

Flow: `input -> validate_identity -> request_action (simulated tool) -> resolve_action -> output`.

| Metric | p50 | p95 |
|---|---|---|
| Graph run, fresh thread | 4,738 ms | 4,805 ms |
| Saver `aput` | 949 ms | 1,202 ms |
| Saver `aput_writes` | 687 ms | 746 ms |
| Saver `aget_tuple` | 235 ms | 249 ms |
| `Commit` RPC | 238 ms | 249 ms |
| `RunQuery` RPC | 234 ms | 248 ms |

30 of 30 runs succeeded. Per run: 29 logical RPCs (28 `Commit`, 1 `RunQuery`), 28 document writes, 0 document reads, 10 saver calls (5 `aput`, 4 `aput_writes`, 1 `aget_tuple`) and 17,624 committed bytes (serialized `Commit` requests). Total across the 30 runs: 840 document writes and 528,736 committed bytes.

Document writes per run by shape: 5 checkpoints, 14 channel-value documents and 9 pending-write documents. Approximate stored sizes across the 30 runs: checkpoint documents p50 1,067 bytes (p95 1,497, max 1,507); channel-value documents p50 101 bytes; pending-write documents p50 134 bytes.

#### Continuity - two turns on one thread

Both turns succeeded and the second turn loaded the stored state (`attempts` carried over). Per run: 28 RPCs, 5.5 document reads, 26 writes and 17,745 committed bytes; run p50 4,779 ms. The second turn loaded the latest checkpoint plus 10 channel-value documents through one `BatchGetDocuments`. The thread accumulated 52 documents: 10 checkpoints, 26 channel-value documents and 16 pending writes, none of which is deleted by the saver.

#### Interruption and recovery

Pausing before `request_action` returned the state without `operation_status` and with 0 pending writes; resuming through the same config completed the flow with `operation_status = NONE`, `attempts = 1` and `outcome = queued`. Pause and resume averaged 16 RPCs, 3.5 reads, 14 writes and 9,162 committed bytes; p50 2,596 ms and p95 2,942 ms.

#### Same-thread concurrency

Two concurrent graph invocations on one thread both completed (4,815 ms total): 58 RPCs, 56 document writes and 33,754 committed bytes, with no `ABORTED`, no 429 and no retries. Two concurrent `aput` calls with distinct checkpoint IDs were also retained and readable, and the latest checkpoint resolved to the expected ID. This validates completion and last-writer visibility, not full serializability.

#### Read surface

Latest `aget_tuple` and `aget_tuple` by ID took p50 701 ms (they load channel values and pending writes); `alist(limit=2)` took 1,202 ms and returned the two newest checkpoint IDs in descending order. Completed successful runs left 0 pending writes. Query, batch-get and commit RPCs never failed.

#### TTL compatibility

Checkpoint documents carry `ts` as an ISO-8601 string, not a Firestore Timestamp. A future TTL policy would need a timestamp-typed field; TTL administration is not authorized for the spike identity and was not configured.

#### PII, secrets and coupling

Fixtures are synthetic and PII-free; stored checkpoint metadata contains only `parents`, `source` and `step`, and pending-write documents contain channel names, task IDs and serialized values only. No identity input, password, token or caller data exists in any document or report. The saver imports only the public `langgraph.checkpoint.base` surface, `SerializerProtocol` and `JsonPlusSerializer`; private google-cloud-firestore seams are used by the measurement harness only.

#### Defects found and fixed during measurement

1. Namespace token `__root__`: Firestore rejects resource IDs that begin with `__` (`Resource id "__root__" is invalid because it is reserved`). Fixed in the experimental saver by encoding namespaces as `root` for the empty namespace and `ns_<percent-encoded>` with a digest fallback otherwise; regression test added.
2. `get_many` order: `BatchGetDocuments` did not return documents in reference order and the local double had masked it; positional zipping corrupted channel values and surfaced as a `TypeError` on the second turn. Fixed by keying results on the document reference path; three regression tests added.
3. Latest-checkpoint query: `orderBy __name__ DESC` requires an explicit index in this database (`FAILED_PRECONDITION: The query requires an index`). The saver now orders by the native `checkpoint_id` field descending, served by the automatic single-field index; descending queries on `checkpoint_id`, `ts` and `step` were verified. No index or other infrastructure was created.
4. Harness-only: proto-plus messages expose `SerializeToString` through the underlying protobuf; byte accounting was corrected.

Each defect blocked a measurement attempt; the harness stopped the run, the fix was applied, local gates were re-run and the full measurement restarted from a fresh prefix. Failed attempts are not part of the final numbers.

#### Stop-condition audit

- Serialization: strict allowlist active, no pickle, no arbitrary objects, no opaque schema; the largest stored document observed was 1,507 bytes against the 1,048,576-byte limit.
- Write amplification and contention: no `ABORTED`, no `RESOURCE_EXHAUSTED`/429, no surfaced internal errors and no retry log records. The measured 28 document writes and ~17.6 KB committed per trivial 3-node turn are reported for deliberation, not normalized.
- History and pending writes: the version-effective contract required no composite index, no collection-group query and no time-travel implementation; the `__name__` ordering issue was resolved with an already-automatic single-field index.
- Security: no raw PII/secret exposure and no permissions beyond `roles/datastore.user`; TTL administration was not attempted.

Deliberation items (no threshold is defined by this record): wall-clock cost of a trivial turn dominated by 9 sequential write-persistence calls, document write volume per turn, and unbounded retention of checkpoints, channel values and pending writes until a TTL/cleanup policy exists.

## Limitations

- TTL enforcement is not authorized by the spike service account and was not tested; `ts` is currently an ISO-8601 string, so a TTL policy would also need a timestamp-typed field.
- The saver never deletes consumed checkpoints, channel values or pending writes; per-thread storage grows with conversation length until a cleanup/TTL policy exists.
- `alist(None)` (global, cross-thread listing) and `adelete_thread` are intentionally out of scope for this minimal saver; the tests assert they are not implemented. Thread deletion would need namespace discovery or a collection-group index, which this spike avoids.
- Same-thread concurrency was exercised with two concurrent graph invocations and two concurrent `aput` calls; it validated completion and last-writer visibility, not full serializability.
- Measurements come from one host, one region and one database; p50/p95 are environment-specific and contain no LLM, network or voice latency.
- Instrumentation is client-side: logical RPCs, document counts and SDK retry logs. Server-side billing attribution and retry attempts hidden inside the SDK are not directly observed.
- The secure floor requires LangGraph 1.x; the exact reproducible production lock remains gap `FS-001`.
- Raw spike documents remain in Firestore under the recorded prefixes pending acceptance and must be cleaned by the owner when appropriate; the Markdown record itself is not deleted.

## Conclusion

The measurement phase completed with no stop condition triggered. All 30 representative runs, continuity, interruption/recovery, read surface and both concurrency exercises succeeded against real Firestore `us-east1` without `ABORTED`, `RESOURCE_EXHAUSTED`/429, internal retries or security exposure, with the strict serializer active.

Three implementation defects were found and fixed during measurement (namespace token, unordered batch reads, `__name__` ordering); the corrected implementation is the one measured.

Option A is functionally viable against the authorized database, but it is **not selected for CU013 production**. Its measured 4.7-4.8 s wall clock per trivial turn, 28 document writes per run, deep non-semantic Firestore shape, LangGraph contract/version coupling and unbounded retention add latency and persistence complexity incompatible with the current voice-path priority.

The experimental saver, schema, package, instrumentation and lock are not production interfaces. This record remains as historical evidence for the rejected production option.

## Adopted ADR

[ADR-0009 — Usar un repositorio delgado de sesiones en Firestore](../decisions/0009-use-thin-firestore-session-repository.md) selects Option B and rejects persistent checkpointing for the production voice path.

## Official references consulted for planning

- [LangGraph checkpoint API](https://reference.langchain.com/python/langgraph/checkpoint): current public saver/serializer surface; the exact effective version must be locked and rechecked at execution.
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence): checkpoint, thread, recovery and pending-write semantics.
- [Firestore best practices](https://docs.cloud.google.com/firestore/native/docs/best-practices): workload-dependent contention and write behavior.
- [Firestore TTL](https://docs.cloud.google.com/firestore/native/docs/ttl): retention behavior and permissions, consulted 15-09-2026.
- [OSV.dev advisory API](https://api.osv.dev/v1/query): advisory review of the resolved lock, consulted 15-09-2026.
- [LangGraph security note](https://github.com/langchain-ai/langgraph/security/advisories/GHSA-g48c-2wqr-h844): checkpoint deserialization advisory fixed in `langgraph` 1.0.10.
