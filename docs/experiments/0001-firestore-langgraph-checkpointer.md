# Experiment 0001: Firestore/LangGraph Checkpointer

- Status: Planned
- Lifecycle: Planned → Running → Completed | Failed | Inconclusive
- Authority: Experimental evidence only; not an architectural decision
- Execution owner: OpenCode under a separate assignment

## Question and hypothesis

Can a custom async Firestore checkpointer implement the public, version-matched LangGraph checkpoint contract with acceptable complexity, inspectable data, safe serialization and measured behavior for CU013?

Hypothesis: **Option A — LangGraph-native persistence over Firestore** is viable without arbitrary-object serialization, excessive write amplification, material voice-path latency or a storage model dominated by history features CU013 does not use.

Option A remains a hypothesis. Firestore is already Accepted as the durable store; this document cannot adopt the integration mechanism.

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

Pending execution.

## Limitations

Pending execution. Initial known limitation: TTL enforcement is not authorized by the spike SA.

## Conclusion

Pending execution.

- If Option A meets the criteria: create a new Accepted ADR before productive implementation.
- If Option A fails: preserve evidence here and run a separate Option B experiment.
- If Option B succeeds: create an Accepted ADR for Thin Session Repository.
- If both fail: STOP & REPORT before proposing another database.

## Adopted ADR

None. Pending evidence and deliberation.

## Official references consulted for planning

- [LangGraph checkpoint API](https://reference.langchain.com/python/langgraph/checkpoint): current public saver/serializer surface; the exact effective version must be locked and rechecked at execution.
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence): checkpoint, thread, recovery and pending-write semantics.
- [Firestore best practices](https://docs.cloud.google.com/firestore/native/docs/best-practices): workload-dependent contention and write behavior.
- [Firestore TTL](https://docs.cloud.google.com/firestore/native/docs/ttl): retention behavior and permissions, consulted 15-09-2026.
