# Experiment 0009: conversational memory and eight coincident callers

- Status: Local/synthetic phase executed 2026-09-18; cloud benchmark, voice test, N=5/C2 follow-ups and every product decision remain pending owner authorization.
- Date: 2026-09-17. Authority: experimental plan only, subordinate to the IOPs, current specifications and Accepted ADRs.
- Scope: one attributable memory comparison, a separate capacity test, then separate Q8–Q12 decisions. Incremental DEV spending for this round: at most US$3/month.
- Owner handoff: implement and evaluate only an identifiable experimental candidate; product acceptance follows the evidence. Temporary DEV cloud mutations require separate authorization. This record does not authorize a commit, push, merge, production deploy, permanent infrastructure, destructive cleanup, or real XCALLY/AD/TIVIT/SendMail side effect.

## 1. Verified starting point and evidence limits

**Observed.** `dev` is at `21896d12e04da173eda5b0fb4949ac5841812fdd`, the SHA in `evals/conversation/accepted-baseline.json`; local `origin/dev` is `9cb93fe7e624daac83903735274f8d7a3250fbdb`, two commits behind (`4b910685`, `21896d1`). Remotes are `origin` and `tivit`; relevant tag is `audit-baseline-2026-09-11`. The worktree was already dirty: tracked documentation, lab, skill and configuration edits, two deletions, and untracked experiment 0007/0008 and lab artifacts. There is no observed `app/` diff. These are local refs and local files, not a fresh remote fetch. Preserve all existing changes. CodeGraph reported 55 indexed files/1,015 nodes; an index refresh hit an in-use database (`EPERM`), so structural findings below were checked against files.

**Observed runtime.** The path is `POST /api/v1/conversations/{conversation_id}/turns` → `TurnService.handle_turn` → Firestore load → ephemeral `GraphState` → compiled LangGraph `ainvoke` → deterministic consolidation → Firestore save → HTTP response. See `app/api/app.py:38-70`, `app/session/service.py:80-113`, `app/session/turns.py:627-644`, `app/session/repository.py:33-46`. The 200 wire remains `{message, route, turn_id}` with `CONTINUE|COLLECT_IDENTITY|COMPLETE|ESCALATE` (`app/api/contracts.py`). A transcript causes one awaited Vertex call; no transcript causes none (`app/session/turns.py:248-264`). The graph has no persistent checkpointer. `SessionRecord` v2 stores goal/revision, identity, confirmation, dispatch, external operation and counters, without procedure progress or recent utterances (`app/session/record.py:135-171,243-300`). The Gemini prompt sees that semantic projection and **only the current transcript** (`app/conversation/gemini.py:71-105,141-162`); it cannot resolve a previous pronoun, side question or guided step when absent from the current utterance. Goal state alone cannot restore the wording or referent of an earlier exchange. Accepted ADRs [0002](../decisions/0002-use-firestore-for-durable-sessions.md), [0004](../decisions/0004-use-langgraph-for-turn-orchestration.md), [0009](../decisions/0009-use-thin-firestore-session-repository.md) and [0010](../decisions/0010-durable-semantic-plan-separate-from-authorization.md) set the current durable/orchestration and semantic-versus-authorization boundaries.

**Observed baseline and limits.** Gemini is `gemini-2.5-flash-lite`, Vertex AI, `thinking_budget=0`, one attempt; the adapter's configured timeout is 15 s (`app/conversation/gemini.py:181-192`). Experiment [0004](0004-cloud-run-latency.md) measured 30 **sequential warm** requests at 1 vCPU/512 MiB, concurrency=1/max_instances=1: runtime outside model p50/p95 3.7/4.6 ms, model 595.3/794.7 ms, load p95 36.2 ms, save p95 101.5 ms, handler 656.6/919.6 ms; one model outlier was 1,461.7 ms. This does not establish eight caller capacity. [0005](0005-xcally-voice-turn-diagnosis.md) contains one real XCALLY voice observation, not ASR/TTS end-to-end latency. [0006](0006-semantic-runtime-evaluation.md) and the current [0007](0007-agent-evaluation-lab.md) expose semantic failures and a 35-case/31-family lab, not a successful memory candidate. The available `evals/results/conversation-eval-20260917T195804-ad9d31dd.json` has 138 valid repetitions, zero INFRA, 11 failing case summaries and model p50/p95 954/1,281 ms; its self-comparison checks harness consistency only, not product PASS. The current corpus validates as 35 cases/zero schema problems. [0008](0008-postgres-langgraph-checkpointer.md) found no unique memory property from PostgreSQL checkpointing and retained Thin Firestore; it is experimental evidence, not a substitute for current code inspection.

**Observed external evidence.** `docs/iop/README.md` identifies the owner-supplied IOPs. The RESET guided steps in `docs/specs/account-actions.md:79-111` are grounded in IOP-MDA-013: Microsoft security-info portal, password composition guidance, and TIVIT access portal subject to corporate network/VPN; UNLOCK has no guided self-service. IOP-MDA-012 governs identity/unlock/escalation, subject to the current specification's XCALLY execution mechanism. The local `C:\Users\Pedro Lopevia\Downloads\DOC_API_RD.pdf` (SHA-256 `3e2b4620e11a4682ed0b165f5fea5414d85856dd6ea22321a81a292b65112b7d`) and `C:\Users\Pedro Lopevia\Downloads\TIVIT_RD_LATAM.xml` (SHA-256 `0db02b47948f151e32321ddc7dc62c3fc33a155f5967978c762371228d979afb`) were read without mutation. The PDF corroborates `GET /resetunlock/validauser/{CLIENTE}/{DOCUMENTO}`, `POST /resetunlock/call/{CALLERID(Name)}`, `GET /resetunlock/consutcall/{CALLERID(Name)}` and request fields; the XML corroborates call/poll commands and statuses, but does **not** show `validauser` or the effective Cally Square action/result wire. CCLH_RD is not used as action authority. `docs/specs/xcally-boundary.md:103-115` currently says transcripts are not persisted; any real caller memory persistence requires an explicit accepted specification/privacy change.

**Availability limit.** A read-only `gcloud run services describe` failed during credential refresh with TLS certificate verification; effective live Cloud Run revision, traffic, environment and billing state remain unverified. `config.yaml` and [0004](0004-cloud-run-latency.md) describe configured/historical values only. Cloud preflight is mandatory before a temporary benchmark.

**Normative boundary.** B0/P/C1, N=3, byte caps, procedure-progress fields and any retained text are **experiment variants**, not Accepted requirements. Keep their definitions and results in this record and identify each code/eval artifact by fingerprint. The experimental path must be opt-in for synthetic sessions and isolated from real XCALLY callers; the default current behavior remains governed by the existing specifications. No *new* owner-accepted behavior was found that requires a pre-experiment SPEC edit. Firestore-only durability, LangGraph, Thin Session Repository, the current XCALLY wire and separation of semantic intent from authorization are already Accepted and documented in the cited specs/ADRs; they constrain the trial rather than result from it. Only an independently evidenced correction to an already Accepted invariant would warrant a separate pre-experiment SPEC fix. The owner decides after results whether to accept any new memory/procedure behavior; only then update the affected SPEC/ADR and current-state documentation.

## 2. What “intelligent” means here

The evaluation will observe whether, in a natural telephone exchange, the agent (a) resolves a prior referent, (b) retains the authorized goal through a lateral question, (c) answers that question and resumes the right IOP step, (d) handles a temporary switch versus an actual correction, (e) recovers a lost step without inventing one, and (f) speaks concise, comprehensible guidance. State and per-turn oracles prove the first five; a blinded spoken review of locally rendered, synthetic utterances judges the sixth. Every caller transcript targets one model call; technical polling targets zero. No keyword matcher, spoken FSM, additional model call, or synthetic PASS can stand in for these observations.

The voice boundary stays `Caller → XCALLY/Cally Square → ASR → CU013 → text → TTS → Caller` (`docs/specs/xcally-boundary.md`). Streaming, barge-in, full duplex, WebSocket and speech-to-speech are outside this plan until XCALLY Motion V3 3.55.0 evidence supports them.

## 3. Q7: bounded memory inside Thin Firestore

**Experimental candidate hypothesis / proposed shape.** Extend the same closed `SessionRecord`, not the storage platform: existing semantic and authorization planes; a small guided-procedure plane (`procedure_id`, branch, current step, last completed step, paused/awaiting-caller marker, bound `goal_revision`); at most one explicitly suspended procedure for a *temporary* switch; and a recent caller/assistant **completed-turn pair** window. These are proposed trial fields, not an Accepted schema. The current caller transcript is added only to the ephemeral model input. A canceled/corrected goal invalidates related procedure/confirmation state and cannot be restored from old text. The runtime validates any model-proposed step against accepted IOP steps; the model owns phrasing and intent recognition, while the runtime owns progress legality. UNLOCK does not gain invented self-service steps. Procedure identifiers and allowed transitions must be derived from `docs/specs/account-actions.md` and the IOP, with the smallest vertical-slice contract that supports the cases.

**First comparison.** Start with **N=3 completed turn pairs**, not a token-matrix sweep. Three pairs cover a question, its answer and return while bounding reads/writes. Proposed independent caps to validate in the experiment: 1 KiB per pair, 3 KiB total window, 8 KiB entire serialized session; record actual bytes and tokens. These are experiment guards, not accepted product limits. Count both caller text and the runtime-final assistant `message` intended for the 200 response in each pair, with role, sequence and goal revision; do not persist an unspoken model draft, model JSON, tool payload, failed/timeout turn, technical poll, TTS retry or external secret/result. Construct the final response before the paired save, append only after runtime validation, save, then return 200; a save failure must suppress the 200. The backend cannot know whether XCALLY/TTS played a successfully returned message, so a later “I missed that step” must recover from procedure state. Trim oldest **whole** pairs in one bounded pass; on oversize input use an approved safe projection or omit the pair with an explicit omission marker, never silently cut a word or repeatedly copy an expanding list. Retain procedure progress independently when a long procedure evicts early dialogue. Explicit forgetting means evicted free text is unavailable for later reference; durable goal/procedure remains only until completion, cancellation, expiry or policy deletion. Corrected facts supersede earlier text; do not revive invalid challenges from memory. A new process with the same `conversation_id` must load the same bounded state.

**Privacy decision pending, without blocking synthetic B0/P/C1.** (1) Raw DTMF, document, date of birth, passwords, credentials and temporary passwords are always prohibited in LLM input, logs, fixtures and conversation memory. (2) Ordinary speech can still contain incidental PII. In fact, the current adapter concatenates the caller transcript directly into model contents (`app/conversation/gemini.py:153-160`); DTMF isolation alone does not make a proposed window PII-free. (3) No authoritative incidental-PII retention, sanitization or TTL policy was found. Run memory trials only with synthetic, non-sensitive utterances; the trial may retain their exact text to measure conversational value. For real callers, whether to retain raw normal speech, an approved projection, or no text—and its sanitization, ingress/egress guards, logical expiry and TTL/deletion rules—requires an owner privacy/product decision. A simple redactor is not evidence of safety. Re-run affected cases if an approved projection changes wording. Firestore TTL is not instantaneous ([Firestore TTL](https://firebase.google.com/docs/firestore/ttl)). The absent policy blocks real-caller persistence, **not** the isolated synthetic experiment.

**Attribution.** Re-run the current Thin Firestore baseline **B0** under the enlarged, fingerprinted lab. **P** adds only guided progress with the same model, prompt policy and no window; **C1** adds the N=3 window to P. Thus P–B0 tests procedural state, C1–P tests recent dialogue. Use the same `gemini-2.5-flash-lite`, zero thinking, runtime legality, corpus, runner and repetition rules; record exact prompt diffs and token changes. If C1 fails only because required dialogue is evicted, test N=5 as a **single conditional follow-up** with identical shape. If C1 meets continuity but misses measured latency/size bounds, only then propose **C2**: the same semantic/procedure planes, a brief structured/condensed memory and shorter window. C2 needs a separate paired run and a deterministic or offline condensation method; a second model call in the hot path requires new evidence and owner decision. No checkpointer or second database is implied by any arm.

## 4. Q7 lab extension and acceptance

Use the existing `evals/conversation/cases.yaml`, `evals/conversation_lab.py`, `evals/conversation_eval.py`, `evals/conversation_compare.py` and `evals/conversation/accepted-baseline.json`; **do not build another evaluator**. The accepted SHA matches HEAD, but current corpus/runner are dirty and have changed since the manifest. Extend the existing variant fingerprint with memory shape/limits, procedure schema and renderer hash; rerun B0 in the **same** enlarged corpus and runner before pairing. `evals/conversation_eval.py:387-532` currently invokes model and runtime directly and bypasses `TurnService`/Firestore, so add a repository-backed replay lane for save/reload/restart while retaining existing oracle, sanitizer, comparator and INFRA-versus-FAIL semantics. `StateProjection` and per-turn oracle allowlists (`evals/conversation_lab.py:424-443,488-531,748-767`) need only PII-safe procedure, referent and memory-presence facts; artifacts must not contain transcripts or model messages. Use the `conversation-evaluation` skill gate: one warmup plus **three valid repetitions per trial**, same seeds/order where supported, invalid infrastructure runs separated, no new critical violation, paired semantic improvement without unexplained token/latency regression, and manual spoken review before ACCEPT. Do not accept a single model run.

| Synthetic family | Required per-turn oracle / failure witness |
|---|---|
| `pronoun-reference` | A pronoun resolves to the previously discussed Microsoft/TIVIT portal; correct `procedure_id`, no invented referent. |
| `procedure-lost-step` | Repeated “which step was I on?” returns the stored current/last completed step, not a reset or fabricated step. |
| `side-question-return` | Lateral answer is judged by spoken review; goal/step stay stable and the next utterance returns to that step. |
| `temporary-goal-switch` | One paused procedure remains bounded; explicit return resumes it, while any old confirmation is invalid. |
| `goal-correction` | Goal and revision change; canceled goal and its challenge/dispatch eligibility do not return. |
| `retroactive-step-correction` | “I did not finish that step” moves progress back only to a legal IOP point; prior completed claim is superseded. |
| `long-guided-procedure` | Earlier pair is evicted, record cap holds, current step survives and no step is invented. |
| `forgetting-boundary` | Referent kept inside window resolves; evicted incidental item is explicitly not claimed as remembered. |
| `sensitive-input-never-memory` | A synthetic opaque canary generated **outside fixture files** enters the protected DTMF event lane and must be absent from model arguments, logs and documents. A separate local fake-model ASR injection shows whether the current direct transcript path exposes a spoken canary; this is a blocking safety finding, never a live Vertex trial. No real identifier or secret is used. |
| `restart-continuity` | Destroy/recreate service process over the same synthetic Firestore session; goal, step and bounded window survive. |
| `8-session-burst` | Capacity benchmark below, eight **different** IDs released together; not a sequential YAML trial. |
| `same-session-race` | Separate deterministic overlap test below; two requests for **one** ID, not a substitute for the burst. |

Paraphrase and repeat the conversational families. For each turn record expected goal/revision, procedure ID/current/last completed step, resolved referent, answered side question, return, correction, retained/forgotten items and route, plus existing identity/authorization/dispatch/duplicate/claim/handoff oracles. Critical gate: no sensitive or canary leak; no unauthorized or duplicate dispatch; no stale challenge/identity reuse; no invented external result or illegal handoff. A spoken quality judgement is recorded by reviewer and case ID, without adding caller text to shared artifacts. `NOT_REPRESENTABLE` is not PASS. Measure prompt/completion tokens, serialized session bytes, Firestore load/save, memory encode/decode/render, non-model runtime, model, handler and wall time per turn; capture deltas by family and long-dialogue position. The winner must improve memory families with zero new critical violations and no unexplained efficiency deterioration. The ≤1.5 s backend p95 is this round's owner target, not an invented universal SLO.

## 5. Eight caller capacity: separate benchmark, not a memory quality oracle

**Preflight.** Verify effective Cloud Run service/revision/traffic, region, autoscaling mode, image digest, vCPU, memory, concurrency, service- and revision-level max/min instances, environment and billing; the read-only gcloud query above failed. Capture the full pre-state `spec.traffic` and effective traffic: each percentage, tag and whether its target is `latestRevision: true` or a pinned `revisionName`; record service/revision scaling, image digest and the absence of concurrent deployments. Verify available DEV budget from current pricing and project spend. Estimate `Cloud Run active/idle vCPU-s + GiB-s + requests + Vertex input/output tokens + Firestore reads/writes/storage` at the planned burst counts using current [Cloud Run](https://cloud.google.com/run/pricing), [Vertex](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing) and [Firestore](https://cloud.google.com/firestore/pricing) rates; stop at US$2.50 incremental spend to leave buffer within US$3/month. Keep synthetic sessions isolated with a manifest for later authorized cleanup. Specify and verify the exact traffic-semantic restore procedure **before** a cloud mutation.

**Temporary mutation boundary.** Build one benchmark image per code arm, then create temporary **0%-traffic tagged DEV revisions** via `gcloud run deploy SERVICE --image IMAGE --no-traffic --tag TAG --cpu 1 --memory 512Mi --concurrency 8 --max-instances 1 --min-instances 0` (change the revision concurrency/max only for conditional configurations). Official `gcloud run deploy` defines `--max-instances`/`--min-instances` as **revision-level** and `--max`/`--min` as **service-level** ([CLI reference](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy), last updated 2026-06-30). Keep service-level scaling unchanged and inspect it read-only; a tagged revision counts against the service-level maximum **only when it belongs to a traffic split**, so a service-level max <2/<4 is not by itself a STOP for a tagged 0%-traffic test ([maximum instances](https://docs.cloud.google.com/run/docs/configuring/max-instances), updated 2026-09-16). Verify actual revision instance count. `--no-traffic` pins traffic previously assigned to LATEST to its current revision and changes future LATEST routing; unchanged percentages are **not** a complete rollback ([CLI reference](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy)). A tagged revision with revision-level min >0 stays billable: prefer min=0 plus observed warm priming. Only if warm evidence is unstable, seek explicit authorization for a new temporary revision with revision-level min=1 for the one-instance arm, and remove its tag/revision promptly after use ([minimum instances](https://docs.cloud.google.com/run/docs/configuring/min-instances), updated 2026-09-16).

**Isolation choice.** A tagged revision on the existing DEV service reuses its verified IAM, networking, secrets and Firestore access, avoiding a second service and its configuration drift; its cost is the benchmark revision plus requests, but `--no-traffic` requires an exact LATEST-semantic restore. A temporary isolated DEV service leaves the original service's traffic/LATEST untouched and may be easier to delete, but requires cloning and validating IAM/network/environment, a separate URL and resource cleanup; equal cost/effort is **not yet established**. Prefer the tagged revision only if pre-state, future-routing semantics and a no-concurrent-deploy window can be captured and restored safely. If that fails, compare measured setup/rollback risk and cost, then request owner authorization for the isolated service rather than creating it prophylactically. Do not STOP solely because the current service-level max is lower than 2 or 4.

**Phase A: backend isolation.** Use actual Cloud Run, Thin Firestore, B0 then P/C1 as needed, 1 vCPU/512 MiB, **concurrency=8, max_instances=1** for a warm worst-share test. A deterministic **async** model seam must still perform the same prompt/memory render and decision validation, then await a fixed representative delay (initially 600 ms, declared in artifact) and return a fixed safe result; it must not call Vertex or AD. Eight distinct preseeded `conversation_id`s at the window cap are released by one client barrier as close together as possible; record release/arrival skew. Prime the tagged revision, verify warm instance count/startup evidence using a per-process ephemeral ID in PII-safe logs plus Monitoring, exclude warmups, then run **at least 30 bursts per arm over at least three 60-second metric windows** (240 requests/arm), alternating arm order to reduce time drift. Separate any burst that starts a new instance from warm statistics. This count is for Cloud Monitoring sampling and tail estimates, not a claim of statistical power. Stop early on critical failure or budget. Report p50/p95/max wall and handler, load/save, memory encode/decode/render, non-model runtime, errors/timeouts, CPU, memory, actual concurrent requests, instance count, pending latency and startup latency separately. If this one-instance configuration fails from CPU/contention/latency, test **concurrency=4/max_instances=2** with capacity eight; only if necessary test **concurrency=2/max_instances=4**. Prime and verify the required two/four instances for a warm comparison, or report that warm distribution could not be established. Cloud Run may briefly exceed a configured max under spikes, so observed instance count governs the one-instance claim ([max instance limits](https://docs.cloud.google.com/run/docs/configuring/max-instances-limits)). Do not try 2 vCPU, workers, threads, uvloop or dependencies without a measured cause. Stop at the first configuration satisfying the candidate's backend target and resource/error guard; no full matrix.

**Phase B: provider included.** Only for the promising Phase A configuration(s), use real in-region `gemini-2.5-flash-lite`, `thinking_budget=0`, B0 versus the same C1 memory candidate, same synthetic utterance mix and eight distinct simultaneous IDs. Use one warmup and **at least 20 valid bursts per arm** (160 calls/arm), alternating order and spanning enough time for Monitoring; three valid lab repetitions remain separate. Report p50/p95/max, failures, provider/model latency, prompt/completion tokens and the same backend segments. Preserve one model call per new transcript and no default retry. Stop if provider quota, spend or error rate makes the comparison uninterpretable. Do not extrapolate synthetic quality to real calls.

**Phase C: cold burst.** Use the chosen revision with `min_instances=0`; verify scale-to-zero before each of **at least five** eight-ID bursts. Record startup, pending, end-to-end wall and errors separately. Do not mix cold values into warm p95. Cloud Run's autoscaling uses CPU and concurrency; Adaptive Concurrency Tuning may reduce effective concurrency under saturation ([concurrency](https://docs.cloud.google.com/run/docs/about-concurrency), [autoscaling](https://docs.cloud.google.com/run/docs/about-instance-autoscaling)). Monitoring metrics are sampled over 60 s and may appear later; use `run.googleapis.com/container/{cpu,memory}/utilizations`, `container/max_request_concurrencies`, `container/instance_count`, `container/startup_latencies`, `request_latency/pending`, `request_latency/e2e_latencies`, `request_latencies`, and `request_count`, with tagged revision and time-window labels ([metric reference](https://docs.cloud.google.com/monitoring/api/metrics_gcp_p_z)). Client monotonic timestamps give wall/arrival skew; request-scoped PII-safe app metrics give handler, load/save, render and model. Correlate by generated `turn_id`/synthetic run ID, never transcript. Compare Cloud Monitoring utilization only after its delayed samples arrive. Configured concurrency is a cap, not proof that eight requests shared an instance.

| Measurement | Exact source to retain in sanitized run artifact |
|---|---|
| Prompt/completion tokens | Vertex `usage_metadata` per model call; synthetic Phase A marks these unavailable rather than inventing tokens. |
| Session bytes, encode/decode/render | UTF-8 serialized Firestore document size and request-local monotonic spans around schema conversion, trimming and model-content render. |
| Firestore load/save, model, non-model runtime, handler | Request-local monotonic spans in `TurnService`/adapter/API; calculate non-model from **the same request** and state whether network wait is included. |
| Client wall, release skew, errors/timeouts | Barrier client's monotonic clock and HTTP status for every request. |
| CPU, memory, concurrency, instances, pending, startup | Cloud Monitoring metric names above, filtered by revision and UTC interval; note sampling delay and missing samples. |

## 6. Hot-path audit to complete before scaling changes

| Component | File/symbol | Async/sync | Observed risk/evidence | Proposed action |
|---|---|---|---|---|
| Vertex | `app/conversation/gemini.py:153-179`, `app/main.py:29-61` | awaited `client.aio.models.generate_content`; shared client | Installed `google-genai==2.23.0` async method is coroutine; network behavior still needs burst measurement. | Instrument call/usage; verify no hidden blocking with loop-lag sample; do not recreate client or add retry. |
| Firestore | `app/session/repository.py:33-46`, `app/main.py:29-61` | `AsyncClient`, awaited `get`/`set`; shared client | Full-document `set` has no precondition; observed current 2 RPCs/turn. | Measure decode/encode and contention; only change write semantics if race test requires it. |
| Prompt/JSON | `app/conversation/gemini.py:71-105,153-162`, `app/session/record.py:243-300` | synchronous string/Pydantic work inside async turn | Current render is small; N-window copies, parsing and serialization can grow. | Measure render/encode/decode/bytes; bounded one-pass trim, no O(N²) accumulation. |
| API serialization | `app/api/app.py:38-70`, `app/api/errors.py:76` | async endpoint, synchronous response model dump | CPU cost unknown; wire fixed. | Include in handler/non-model segment, profile only if material. |
| Logging/metrics | `app/session/metrics.py:53-73` | synchronous stderr logger | Request spans are coarse; recording-list test metrics are shared mutable state. | Request-local measurements, fixed PII-safe fields; do not share mutable per-call recorder in benchmark. |
| Globals/locks | `app/main.py:29-61`, `app/session/turns.py:627-644` | shared clients/compiled graph; no observed per-session lock | Eight IDs can overlap; same-ID writes may race. | Test both patterns separately; add no global lock as a precaution. |
| Uvicorn | `Dockerfile:19`, `config.yaml` | one process unless effective env overrides | No explicit workers or `THREADS`; effective Cloud Run env unverified. | Verify actual command/env; leave workers/threads unchanged until data points to event-loop/CPU pressure. |

FastAPI's `async def` can serve other requests while awaiting I/O; an ordinary blocking call made inside it still occupies the loop ([FastAPI async](https://fastapi.tiangolo.com/async/)). Inspect installed library behavior and measure loop lag/CPU before attributing latency to LangGraph or prescribing `THREADS=8`. There is no current unbounded message list to optimize; the candidate creates that risk if implemented poorly. Uvicorn's worker default can follow `WEB_CONCURRENCY`, so verify effective environment rather than inferring solely from Dockerfile ([Uvicorn settings](https://www.uvicorn.org/settings/)).

## 7. Same-session race is a different question

`SessionRepository.save` fully overwrites a document after separate `get` and `set`; `revision` increments during consolidation without a compare-and-swap (`app/session/repository.py:33-46`, `app/session/service.py:80-87`, `app/session/record.py:142-143`). **Inference:** two overlapping requests for one `conversation_id` can both read revision *r* and each write *r+1*, losing one goal/progress/window update. **Run the deterministic synthetic race first**, with a barrier after both reads and before either save; assert both returned turn IDs, final revision, both intended updates, and no duplicate dispatch. If real XCALLY/Cally Square proves per-conversation serialization and the overlap cannot occur, keep accepted last-writer-wins (`docs/specs/account-actions.md:227-245`). Only if the race demonstrates a material loss and overlap is possible, evaluate an update-time precondition with safe conflict handling or bounded deterministic rebase **without replaying model or side effect**. The official `AsyncDocumentReference` 2.29.0 page shows `option` in `update()` but its `set()` prose mentions `option` while the displayed signature does not; this is an API/version uncertainty ([official class reference](https://docs.cloud.google.com/python/docs/reference/firestore/latest/google.cloud.firestore_v1.async_document.AsyncDocumentReference), updated 2026-08-25). Read-only inspection of installed `google-cloud-firestore==2.30.0` signatures currently shows `option` on `update()` and none on `set()`, but behavior against the effective backend is unverified. Before choosing a write path, verify the installed version, signature and synthetic precondition behavior, including create-versus-existing-document cases; select only a supported path if optimistic concurrency is actually needed ([Precondition](https://docs.cloud.google.com/python/docs/reference/firestore/latest/google.cloud.firestore_v1.types.Precondition)). Do not switch to `update()` or add a transaction in anticipation. A transaction is a last resort for a demonstrated property; Firestore transactions can retry under contention, and **external side effects must never run inside a retryable transaction** ([contention](https://firebase.google.com/docs/firestore/transaction-data-contention)).

## 8. Reconciliation of Q8–Q12

| Question | Proposed decision and evidence | Open point / separate closure experiment |
|---|---|---|
| Q8 timeout/fallback | Keep the current 15 s adapter setting and HTTP error behavior during the primary memory comparison (`app/conversation/gemini.py:181-192`, `app/api/app.py:73-97`). The reported 1.1 s cutoff conflicts with [0004](0004-cloud-run-latency.md)'s 1,461.7 ms model outlier, and no memory+8 burst exists. No default retry. | After Phase B, derive a deadline from **per-request** in-region latency distribution, with measured load/save/render/ingress headroom inside the owner backend p95 ≤1.5 s target; do not add marginal p95s or invent an SLO. A separate fallback trial should return a concise deterministic spoken retry/status message with a route valid for the **current state**, zero dispatch and zero semantic business mutation from the failed turn, and PII-safe metrics. `CONTINUE` is not universal; existing forced escalation/terminal state may require another legal route. The primary memory wire stays unchanged. Accept actual 200 fallback only after XCALLY evidence of HTTP timeout/route handling, TTS playback, retry and handoff behavior. |
| Q9 action/result | Keep the current 200 `{message,route,turn_id}` and mediated boundary (`docs/specs/account-actions.md:125-181`). PDF/XML support endpoint/field/status inventory above; integration is not implemented and semantics must not be guessed. | The harness can simulate capability, operation ID, authorization guard, `NONE`/pending poll and terminal result without sensitive arguments to the model. Now close only the documented inventory/internal invariant tests. Real Cally Square XML/runtime evidence must settle correlation, idempotency, route/action mapping, polling cadence/deadline, and actual status-to-result interpretation. `validauser` is PDF-only in observed XML. SendMail and unspecified external behavior remain Deferred (`docs/gaps.md`). Do not block Q7/capacity on Q9. |
| Q10 checkpointer | Keep LangGraph orchestration and **no persistent checkpointer** in voice path (`app/session/turns.py:627-644`, ADR [0009](../decisions/0009-use-thin-firestore-session-repository.md), [0008](0008-postgres-langgraph-checkpointer.md)). InMemorySaver per request cannot bridge requests; checkpointing alone does not encode useful dialogue. | Reopen only if a concrete indispensable mid-graph resume property fails the Thin Session Repository test. Demonstrate it with a crash/restart case and cost/latency before any architectural decision. |
| Q11 model loops | One model call for a new caller transcript and zero for no new speech are current graph properties (`app/session/turns.py:248-264`). Polling `PENDING/NONE` and deterministic status checks should use zero; a terminal result calls the model only when natural formulation is necessary. | Add explicit counters/oracles for transcript, polling and terminal-result paths once Q9 seam exists. Reject model → poll → model loops and TTS-driven extra calls. A proposed second call needs evidence of otherwise impossible behavior plus measured incremental latency/tokens/cost and owner decision; more than two sequential calls triggers STOP & REPORT. |
| Q12 few-shot/model | Primary Q7 uses zero-shot `gemini-2.5-flash-lite`, zero thinking and the same runtime/prompt policy. The baseline manifest SHA equals current HEAD, but expanded lab requires new paired B0 observations. | Only after repeated paraphrase failures, try 1–2 contrastive few-shot examples as a **separate** paired arm with token/latency measurement. Compare another model later with identical accepted memory, runtime, corpus and evaluation settings; assess spoken quality, continuity, structured output/capability selection, latency and tokens. Never change model to hide a memory defect. |

## 9. Executable handoff, evidence and stop rules

1. **Freeze evidence without cleaning the tree.** Record `git remote -v`, `git branch --show-current`, `git rev-parse HEAD origin/dev`, `git status --short`, relevant tags, `git diff` and accepted baseline manifest; fingerprint the dirty lab and implementation. Confirm local IOP/PDF/XML hashes. Cloud preflight is read-only and records full `spec.traffic` (including `latestRevision` versus pinned revision), effective traffic, scaling, image digest and billing before any separately authorized mutation.
2. **Implement the synthetic candidate, not a new accepted SPEC.** Put B0/P/C1 definitions and experimental limits in this record and identifiable code/eval fingerprints. Implement the opt-in synthetic path in `app/session/record.py`, `repository.py`, `service.py`, `turns.py` and the existing `app/conversation/gemini.py`/`prompts.py` seam; instrument `app/session/metrics.py` and API only as needed for PII-safe request correlation. Preserve default real-caller behavior, current FastAPI wire, model and Cloud Run runtime in the primary comparison. Do not edit `docs/specs/system.md`, `docs/specs/account-actions.md`, `docs/specs/xcally-boundary.md` or an ADR to pre-accept trial memory, procedure fields, byte limits or text retention. Do not introduce a new store, graph checkpointer, tool for internal memory, or dependency.
3. **Extend the existing lab.** Modify `evals/conversation/cases.yaml`, `evals/conversation_lab.py`, `evals/conversation_eval.py`, `evals/conversation_compare.py`, `evals/conversation/README.md` and relevant `tests/evals/`; add only the bounded cases and a repository-backed replay lane. Add deterministic session/migration/trim/expiry/race tests under existing `tests/session/` and `tests/api/` as appropriate. Do not overwrite the accepted baseline manifest: make new B0 and candidate artifacts with source fingerprints. If an existing lab skill's procedure changes, update `.agents/skills/conversation-evaluation/SKILL.md` in the same implementation iteration. No new skill.
4. **Run local gates and paired eval.** Expected commands, adjusted to actual CLI flags: `python -m pytest`, `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy app`, `python -B evals/conversation_eval.py --validate-only`, then the lab's B0/P/C1 replay and `evals/conversation_compare.py` paired comparison. Save sanitized per-turn oracle, critical/INFRA, model-count, bytes/tokens/latency and manual spoken-review evidence. Reject a variant on any new critical violation, privacy breach, unrepresentable required oracle, inconclusive run, or unexplained efficiency regression. Conditional N=5/C2 gets a new fingerprint and separate run.
5. **Prepare temporary benchmark artifacts before cloud authorization.** Add one focused eight-ID barrier client/runner and a short update to `docs/runbooks/cloud-run-dev-benchmark.md` covering deterministic async seam, tagged revision isolation, Monitoring queries, cost estimate, full pre-state `spec.traffic`, future LATEST routing and exact rollback. Existing deploy automation assumes clean tree/HEAD==origin/dev and cannot be invoked blindly on this tree. No benchmark script may call real action endpoints. Request explicit owner authorization for temporary Cloud Run revisions/tags or a justified isolated service, scaling changes, test Firestore writes/deletion and Vertex spend. Record image digest and each tagged URL; keep 0% live traffic and synthetic namespace only.
6. **Execute only after that cloud authorization.** Phase A, then only promising Phase B, then Phase C; run the same-session race separately. Return sanitized run artifacts, revision/config snapshots, Monitoring query/export with time labels, spend calculation, per-arm distributions, exact failure/timeout counts, release skew, loop-lag/CPU analysis and a PASS/FAIL/INCONCLUSIVE conclusion for each hypothesis. Report whether eight callers fit one 1-vCPU instance or require horizontalization; do not extrapolate from concurrency=1 or eight callers/hour.
7. **Restore cloud state and report evidence.** Stop test traffic, compare current service state with the captured pre-state, and STOP rather than overwrite another deployment if it drifted. Remove only listed temporary tags with `gcloud run services update-traffic SERVICE --remove-tags TAG`; delete only listed 0%-traffic benchmark revisions or a separately authorized isolated service/image. Restore the **original traffic target semantics as well as percentages and tags**: if pre-state used `latestRevision: true`, first ensure the original serving revision is again the effective latest, then restore that symbolic target; if it used pinned `revisionName` entries or a mixed split, restore the exact captured entries. Never run `--to-latest` while an experimental revision could become the serving latest. Verify `spec.traffic` and effective traffic against the capture, original service min/max (including `min_instances=0` if pre-state), original serving image, and no billable tagged warm revision. Remove only synthetic Firestore documents from the manifest under cleanup authorization. Provide before/after describe and instance/billing evidence. Never use `git clean`, reset or broad deletion.
8. **Owner decision, then normative closeout.** Complete this experiment record with observed outcomes and limits. The owner decides whether any procedure/memory behavior, retention rule or architecture change is Accepted. **Only after that decision** reconcile `docs/specs/system.md`, `docs/specs/account-actions.md`, `docs/specs/xcally-boundary.md`, any necessary new/superseding ADR, `docs/gaps.md`, affected existing skill/runbook, `[Unreleased]` CHANGELOG and `CONTEXT.md` last under the repository lifecycle. An experimental REJECT/INCONCLUSIVE does not become a SPEC requirement. Commit/push/merge/production deployment each require their own explicit authorization.

**STOP & REPORT:** attempting real-caller text persistence without privacy/retention authority (the synthetic non-sensitive trial may proceed); a prohibited value reaching model/log/store/fixture; unknown IOP step or Cally Square contract required for a proposed behavior; conflict with Accepted ADR; same-session lost update affecting side-effect legality; new critical eval violation; model-call loop over two sequential calls; no attributable paired run; Cloud Run configuration, pre-state traffic semantics or costs unverifiable; forecast beyond US$3/month; or a need for PostgreSQL, Redis, RAG, second database, multi-agent architecture, broad FSM or permanent infrastructure. This plan is ready to decide **which experiment to authorize**, not evidence that memory, eight-caller capacity, fallback or Q9 integration already works.

**STOP & REPORT:** attempting real-caller text persistence without privacy/retention authority (the synthetic non-sensitive trial may proceed); a prohibited value reaching model/log/store/fixture; unknown IOP step or Cally Square contract required for a proposed behavior; conflict with Accepted ADR; same-session lost update affecting side-effect legality; new critical eval violation; model-call loop over two sequential calls; no attributable paired run; Cloud Run configuration, pre-state traffic semantics or costs unverifiable; forecast beyond US$3/month; or a need for PostgreSQL, Redis, RAG, second database, multi-agent architecture, broad FSM or permanent infrastructure. This plan is ready to decide **which experiment to authorize**, not evidence that memory, eight-caller capacity, fallback or Q9 integration already works.

## 10. Local/synthetic phase results (executed 2026-09-18, implementer)

Scope executed: B0/P/C1 implementation with the opt-in synthetic lane, lab
extension, deterministic tests, paired real-model evaluation
(`gemini-2.5-flash-lite`, `thinking_budget=0`, same corpus/runner/repetitions)
and cloud-benchmark preparation. NOT executed: any Cloud Run mutation,
image build/push/deploy, Phase A/B/C, real XCALLY/AD/TIVIT/SendMail side
effects, N=5, C2, commit/push/deploy. No commit was made; pre-existing
worktree changes were preserved untouched (HEAD stayed
`21896d12e04da173eda5b0fb4949ac5841812fdd` throughout).

### 10.1 Implementation fingerprint (all uncommitted, same tree)

- `app/session/memory.py` (new): experimental plane — N=3 default
  (max 5), 1 KiB/pair, 3 KiB window, 8 KiB session guard, guided
  `RESET_PASSWORD_GUIDED` slice (`microsoft_portal`, `tivit_portal`,
  `service_desk` from account-actions SPEC), one bounded suspended slot,
  whole-pair trim, omission markers, render, timings, variant identity.
- `app/session/actions.py` (new): `Action` moved verbatim to break the
  record↔memory import cycle; `record.py` re-exports it, all existing
  imports keep working.
- `app/session/record.py`: three optional experimental planes on
  `SessionRecord` (default `None`/empty); `to_document` adds the
  experimental keys only when active, so B0 documents keep the exact v2
  shape; old documents load through defaults; v1 migration unchanged.
- `app/session/turns.py`: `ModelTurnDecision.procedure_observation`
  (default `NONE`, proposal cue only — runtime still owns legality);
  `TurnModel.decide` accepts optional `memory_context` (default `None`);
  `GraphState`/`TurnDelta` carry the experimental planes plus ephemeral
  memory timings; `run_model` renders the block only under opt-in;
  `advance_turn` evolves procedure/window only under opt-in and appends
  only completed turns (transcript + runtime-final outcome present).
- `app/session/service.py`: `handle_turn(..., experimental=None)`; B0 path
  (default) is byte/behavior-identical; experimental turns return PII-safe
  `ExperimentalTurnMetrics` (session bytes, pair/byte/omission counts,
  encode/decode/render ms — scalars only).
- `app/conversation/gemini.py`: concatenates the rendered block between
  the semantic projection and the transcript only when `memory_context`
  is present; B0 model input is byte-identical. `SYSTEM_INSTRUCTIONS`
  untouched.
- Lab: `conversation_lab.py` (3 turn oracles, scalar-only projection
  facts, `caller_text`/`assistant_text`/`memory_context` sanitization
  keys), `conversation_eval.py` (`--lane direct|repository`,
  `--memory-variant b0|p|c1`, `--memory-n`, repository replay through
  `TurnService` with save/reload per turn and a fresh service per turn,
  session/memory summaries, memory fingerprint),
  `conversation_compare.py` (`memory_variant`/`memory_n`/renderer hashes
  prompt-explaining when declared), 8 new sequence families in
  `cases.yaml` (43 cases, `validate-only` green), README + skill note.
- Burst prep (not executed): `evals/conversation_burst.py` (barrier
  client, deterministic 600 ms seam, estimator, manifest writer, printed
  plan; live URLs refused without a separate flag),
  `ops/gcp/collect-burst-prestate.ps1` (read-only), runbook section.
- Corpus SHA across all three arms: `b4ba2ca84502`; renderer hash
  `7e50e091adf2`; procedure-schema hash `011116b1b364` (truncated).

### 10.2 Methodology incident (found, fixed, re-run)

The first repository-lane replay seeded the fixture record under the bare
`case_id` but ran paraphrase trials under `<case>#t<N>`, so every
independent trial started from a blank record instead of the fixture
state. The first B0/P/C1 dataset (04:02–04:21 UTC) is discarded and was
not compared. The lane now seeds under the trial conversation id; a
deterministic test pins fixture-state start
(`test_repository_lane_matches_direct_lane_without_memory`); a probe
(`unknown-dispatch-result`, both lanes) confirmed the fix. All evidence
below comes from the clean re-runs (04:25–04:35 UTC). Lesson recorded:
repository-lane results are only attributable with the seed-id test green.

### 10.3 Gates (final tree)

- `python -m pytest`: 282 passed (228 pre-existing + 54 new).
- `python -m ruff check .` / `ruff format --check .`: clean (96 files).
- `python -m mypy app`: strict clean (20 files).
- `python -B evals/conversation_eval.py --validate-only`: 43 cases, 0 problems.
- Sanitization: run artifacts carry step identifiers/counts only; the
  sanitizer now also rejects `caller_text`/`assistant_text`/`memory_context`.

### 10.4 Paired real-model results (repository lane, 3 valid reps, 1 warmup)

| Arm | Run artifact (`evals/results/`) | Valid/INFRA | Turns / model calls | Case PASS/FAIL | Rep PASS/FAIL |
|---|---|---|---|---|---|
| B0 | `conversation-eval-20260918T042534-a12595ff.infra-filled.json` | 162/0 | 252/246 | 43/11 | 141/21 |
| P | `conversation-eval-20260918T043040-e4b39a3b.json` | 162/0 | 252/246 | 41/13 | 138/24 |
| C1 | `conversation-eval-20260918T043508-405fb4d6.json` | 162/0 | 252/246 | 43/11 | 143/19 |

Variant digests: B0 `a12595ffcab97cb4`, P `e4b39a3b0b121eda`,
C1 `405fb4d6d8900e8b`; differing dimension between arms is exactly
`memory_variant`. B0's 11 failing cases match the accepted baseline's 11,
confirming the enlarged runner did not move the baseline. Transient
`ModelUnavailableError` reps (B0:1, first P run:4, first C1 run:4) were
filled exclusively from focused reruns without replacing any valid rep.

Paired comparisons (`--variable memory_variant`, 162/162 pairs, 0 INFRA):

| Pair | Targeted improvements | Targeted regressions | Unrelated regressions | New criticals | Efficiency deltas | Verdict |
|---|---|---|---|---|---|---|
| B0→P | 21 (procedure_current across all 7 procedure families) | 4 (single-rep route/revision wobbles) | 18 (single-rep, known-weak families) | 0 | prompt p50 +128 (explained), model p50 −46 ms / p95 −16 ms | NEEDS OWNER DECISION |
| P→C1 | 24 (window_pairs everywhere; ADVANCE adopted in 2/3 retroactive reps) | 5 (incl. 2 non-adoptions of REGRESS, 1 over-advance) | 11 | 0 | prompt p50 +4, model p50 −16 ms / p95 −140 ms | NEEDS OWNER DECISION |
| B0→C1 | 24 | 4 | 12 | 0 | prompt p50 +132, model p50 −62 ms / p95 −156 ms | NEEDS OWNER DECISION |

Tokens/latency/session bytes (valid turns):

| Arm | Prompt p50/p95 | Completion p50 | Model p50/p95 | Session bytes p50/p95/max | Over guard | Memory ops |
|---|---|---|---|---|---|---|
| B0 | 1479/1490 | 95 | 937/1234 ms | 358/635/828 | 0 | n/a |
| P | 1607/1634 | 97 | 891/1218 ms | 578/847/1099 | 0 | 0.0 ms |
| C1 | 1611/1728 | 97 | 875/1078 ms | 873/1237/1331 | 0 | 0.0 ms |

One model call per transcript turn in every arm (246 calls / 246
transcript turns); event-only turns call none. Runtime-semantic p95 is
0 ms in all arms. No backend p95 exceeds the 1.5 s owner target in this
local sample (turn-total p95: B0 1250 ms, P 1234 ms, C1 1078 ms), but this
is DEV-host evidence, not a voice SLO claim.

Behavioral findings:

- P–B0 isolates procedural state: every procedure family gains
  `procedure_current` stability; the model never invents steps outside the
  accepted slice in any rep.
- C1–P isolates recent dialogue: the window fills 1-2-3 and trims oldest
  whole pairs; `long-guided-procedure` turn 5 answers from procedure
  state after the early pair was evicted (spoken review: MEETS).
- ADVANCE is adopted inconsistently (2/6 reps across P/C1 retroactive
  turns); REGRESS was adopted in 0/6 — turn-3 corrections arrive as goal
  CORRECT with procedure rebind instead. One C1 rep over-advanced on a
  bare continuation cue ("sigamos" → `tivit_portal` without completion
  evidence).
- All remaining flips are single-rep route/goal/confirmation variance
  inside already-known residual weaknesses (exp0005 precedence,
  affirmation classification, handoff CANCEL — the latter fires 3/3 on B0
  itself for `caller-asks-human#t3`, so it is not a P/C1 regression).
- Manual spoken review (C1, ephemeral, ratings only): MEETS for
  pronoun-reference, side-question answers, switch/return, correction
  ack, advance ack and post-eviction step report; CONCERN for
  procedure-lost-step (states the step without reporting it),
  side-question t2 (no step named), switch t2 ("desbloquearé" future
  promise), retroactive t3 (vague, no step named) and
  forgetting-boundary t5 (does not claim the evicted detail — correct —
  but invents office hours instead).
- N=5 condition (C1 fails only through eviction of required dialogue) not
  met: no C1 failure traces to eviction. C2 condition (continuity met but
  measured bounds missed) not met: all byte/latency guards hold with
  headroom (session p95 1237 vs 8192 guard). Neither follow-up runs.

### 10.5 Same-session race (deterministic, pinned — mechanism unchanged)

Two overlapping `TurnService` turns over one shared in-memory store, both
reading revision 1 behind a closed write gate: both wrote revision 2, one
goal update lost, zero dispatch produced by either. Verdict: accepted
last-writer-wins confirmed; no lost side effect (no dispatch without a
valid challenge exists on either path). Installed
`google-cloud-firestore==2.30.0`: `update()` exposes `option`
(precondition support), `set()` — the repository's write path — does not.
No transaction, no `update()` switch, no side effect inside retries was
introduced, per plan. Revisit only on evidence of real same-conversation
overlap affecting side-effect legality (XCALLY currently processes one
conversation sequentially).

### 10.6 Privacy (synthetic canaries, in-test only)

- DTMF lane: a generated canary through `IDENTITY_DATA` → 503, engine
  never invoked, store untouched (0 reads/0 writes), absent from
  response/headers/logs/model args. Critical gate holds.
- Spoken lane (fake model only, never Vertex): the same-shaped canary in a
  normal transcript DOES reach the model verbatim and the C1 window would
  retain it — this pins why textual memory stays disabled for real
  callers until an accepted retention/sanitization policy exists. No
  redactor was built.
- Persisted semantic state in this phase: goals/revisions, identity
  outcome + TTL data + counters, challenge/dispatch/operation truth,
  procedure steps + bound revisions + timestamps, window pair counts/bytes
  (texts only inside synthetic session docs, never in run artifacts,
  logs, fixtures or model-error paths).
- `evals/results/` artifacts verified free of transcripts/messages/canaries
  by the extended sanitizer.

### 10.7 Cloud readiness (prepared, nothing executed)

- Barrier client + deterministic 600 ms seam: `--self-check` PASS (8/8,
  0 errors, local in-memory).
- Estimate (`--estimate-only`, rates retrieved 2026-09-18): Phase A
  ≈ US$0.03, Phase B ≈ US$0.08, Phase C ≈ US$0.01, cleanup ≈ US$0.00;
  **total ≈ US$0.12 — within the US$2.50 stop-line** (US$3/month budget).
- Proposed config sequence: concurrency=8/max=1 → 4/2 → 2/4, 1 vCPU /
  512 MiB, tagged 0%-traffic revisions; cold burst separate; Monitoring
  metric list + revision/window labels in the runbook.
- Mutations needing the next authorization: benchmark image builds,
  tagged revisions/tags, any scaling change, test Firestore writes +
  manifest cleanup, Vertex spend for Phases B/C.
- Rollback/cleanup: remove only listed tags (`update-traffic
  --remove-tags`), delete only listed 0%-traffic revisions, restore exact
  `spec.traffic` semantics (`latestRevision` vs `revisionName`),
  `min_instances=0`, original serving image; delete synthetic docs
  document-by-document from the manifest. Pre-state capture:
  `ops/gcp/collect-burst-prestate.ps1` (read-only).

### 10.8 Deviations from the plan

1. Same-action detail correction rebinds (keeps) procedure steps instead
   of clearing them; challenges still invalidate through the existing
   path and are never restored from text. Rationale: a detail fix is not
   a procedure restart; recorded for owner review.
2. Repository-lane seeding incident (10.2): first dataset discarded,
   lane fixed, regression test added, all arms re-run cleanly.
3. Prompt tokens run ~25–30 above the historical baseline even on B0
   (1479 vs 1450): the extended `ModelTurnDecision` response schema
   (new optional cue) travels with every request. Same-schema pairing
   keeps B0/P/C1 attribution intact; noted as a confounder versus the
   accepted-baseline manifest, which is not overwritten.
4. `proposed_procedure_observation` is not a separate artifact field;
   ADVANCE/REGRESS adoption is inferred from state deltas (only the
   observation path can move steps). Follow-up if the owner wants
   per-turn cue visibility without re-running the arms.

### 10.9 Implementer verdict

REQUIRES_CORRECTION before any product acceptance: P/C1 demonstrate the
intended procedural/dialogue continuity with zero new critical
violations and all guards holding, but (a) REGRESS is unadopted and
ADVANCE inconsistent, (b) one over-advance and one confabulation-under-
forgetting were observed in speech, and (c) single-rep flips in
known-weak families need owner eyes per the comparator verdicts. No
N=5/C2 trigger, no cloud execution, no SPEC/ADR change proposed in this
phase. Recommended next owner decisions: accept/reject the rebind
deviation (10.8.1), rule on real-caller text retention (still blocked),
and authorize the cloud burst window separately if capacity evidence is
wanted.

## 11. Focused C1 correction round (executed 2026-09-18, implementer)

Scope: correct only the four observed C1 defects (REGRESS 0/6,
over-advance, silent lost-step, invented-hours/premature-promise) with no
architecture change. Frozen per handoff: Thin Firestore, N=3, byte caps,
`gemini-2.5-flash-lite`, thinking 0, one model call, XCALLY wire, no new
infra, PII policy, race semantics, Q8/Q9/Q12. No commit/push/deploy; prior
artifacts (§10) preserved untouched in `evals/results/`.

### 11.1 Root causes (reproduced per turn from preserved artifacts)

- REGRESS: the `REGRESS` enum exists and the runtime transition is proven
  correct by deterministic tests, but the model never emits it (0/6):
  turn-3 corrections arrive as goal CORRECT/REQUEST with `NONE`. Layer:
  instruction/schema-description (the REGRESS-vs-CORRECT distinction was
  unstated), not runtime or schema shape. No new enum/field was needed.
- Over-advance: the runtime accepted a *legal* step on a semantically
  insufficient cue ("sigamos"); it cannot judge completion semantics, so
  the layer is instruction clarity. KEEP behavior on negatives was already
  correct.
- Silent lost-step: the render carried only the opaque step id, so the
  model could not verbalize the actionable instruction. Layer: render
  content.
- Grounding/tense: no grounding rule and no tense/state-consistency rule
  existed anywhere in the model input. Structured claims cannot represent
  tense, and no text parser was added (out of scope by design).

### 11.2 Minimal-layer changes (all fingerprinted, B0 untouched)

- `app/session/memory.py`: SPEC-derived one-clause descriptions per
  accepted guided step (`GUIDED_STEP_DESCRIPTIONS`, traced to
  account-actions SPEC bullets); render now prints current step + action;
  one general-criteria paragraph (ADVANCE-only-on-explicit-completion,
  REGRESS-vs-CORRECT, lost-step verbalization, grounding-only-from-
  context, tense-per-state); procedure-schema identity covers
  descriptions. B0 prompt bytes unchanged (prompt p50 still 1479).
- `app/session/turns.py`: concise `description` on the existing
  `procedure_observation` field (no new field/enum).
- Corpus 43→47: `retroactive-step-correction-clarify` (second
  paraphrase), `procedure-repeat-keeps-step` (KEEP negative),
  `grounding-tempting-fact` + `promise-capability-distinction` (new
  `procedure-grounding` family). Two self-found
  case-design flaws fixed before the full run (ambiguous second action in
  grounding-t2 → "todo esto"; capability goal/eligibility left
  un-oracled as genuinely ambiguous). README family table updated.
- Deterministic: 7 new tests (render clauses, description coverage,
  schema description, REGRESS-never-revives-challenge incl. service
  level). Gates: 290 passed, ruff check/format clean, mypy strict clean,
  corpus 47/0. Burst `--self-check` still PASS (untouched artifacts
  remain compatible).

### 11.3 Focused eval (affected families + controls, C1′)

Machine: KEEP negatives hold 6/6 (repeat/lost-step/side-question turns
keep step and revision); grounding machine oracles pass after the t2
fix; promise case passes after oracle correction. REGRESS still 0/2 on
the new paraphrase; ADVANCE fired spuriously on a future-tense opener in
one rep ("ya voy a empezar" → tivit_portal) while missing an explicit
completion in another — the cue is unstable in both directions
zero-shot. One transient INFRA filled from a focused rerun.

### 11.4 Full paired eval B0 vs C1′ (final corpus, repository lane, 3 reps)

| Arm | Artifact | Valid/INFRA | Cases P/F | Reps P/F | Prompt p50 | Model p50/p95 | Session p50/p95/max |
|---|---|---|---|---|---|---|---|
| B0 | `...052559-5a842369.infra-filled.json` | 174/0 | 46/12 | 153/21 | 1479 | 906/1156 ms | 367/633/642 |
| C1′ | `...053229-5f39ce75.infra-filled.json` | 174/0 | 44/14 | 152/22 | 1839 (+360 explained) | 937/1141 ms | 885/1308/1487, 0 over-guard |

Digests: renderer `7380ca2ef6d4`, procedure-schema `518a38abf688`,
decision-schema `ebc3955378a4`, corpus `d5c394d54ecb` (identical across
arms; differing dimension exactly `memory_variant`). 270/270 model calls
(one per transcript) in both arms; runtime-semantic p95 0 ms.
Comparison: 174/174 pairs, 0 INFRA, **0 new criticals**,
36 targeted improvements (procedure + window across all 9 target
families), 5 targeted regressions, 17 unrelated — verdict NEEDS OWNER
DECISION per comparator rules.

Spoken review (C1′, ephemeral, ratings only): lost-step now MEETS
(names + SPEC-derived instruction, no advance/restart/invention);
switch-t2 tense fixed ("puedo… ¿confirmamos identidad?");
promise-capability MEETS; retro-t2 MEETS when ADVANCE fires, retro-t3
coherent in words but DIVERGED from state (no REGRESS emitted);
grounding still CONCERN — invented hours and durations persist despite
the general rule.

Material finding: explicit-handoff compliance degrades on C1′ —
`caller-asks-human#t2` 2/3 and `#t3` 1/3 answered CONTINUE (B0 6/6
ESCALATE), plus `reset-direct-request` 2/3 CONTINUE (B0 3/3
COLLECT_IDENTITY), coinciding with the +360-token block. No
handoff-cause error and no dispatch anomaly (critical gate empty), but
missed explicit handoffs are safety-relevant. Hypothesis: instruction
overload/attention dilution; not proven at n=3.

### 11.5 Defect states and promotion

- Retroactive REGRESS: UNRESOLVED (0/12 reps across both C1
  generations; runtime correct; zero-shot cue unadopted).
- Over-advance: IMPROVED_BUT_UNSTABLE (KEEP 6/6; positive ADVANCE 0/6
  this round with one hyper-advance).
- Lost-step verbalization: RESOLVED (state + speech, SPEC-derived).
- Grounding fact invention: UNRESOLVED (rule insufficient).
- Premature promise: RESOLVED in observed samples (no success wording;
  capability + identity-first).
- Promotion: NOT_READY_FOR_CLOUD_BENCHMARK — REGRESS unadopted,
  fabrication persists, and the handoff/routing regression needs owner
  review. N=5/C2 still not triggered. Recommended next decision (not
  activated): Q12 few-shot/model comparison as a separate paired arm,
  since zero-shot instruction is exhausted on REGRESS/grounding; plus an
  instruction-diet variant if the dilution hypothesis is pursued.

## 12. Q12 controlled comparison 2.5 vs 3.1 Flash-Lite (executed 2026-09-18)

Scope: 2 models × 3 strategies focused grid on C1′, then at most two
full finalists, then a latency microbenchmark only if two viable
finalists emerged. No architecture/memory/wire/race/Q8/Q9 change, no
cloud execution, no commit. Prior artifacts preserved.

### 12.1 Verified source facts (checked 2026-09-18, reconfirm at cloud time)

- 3.1 Flash-Lite: model ID `gemini-3.1-flash-lite`, GA (released
  2026-05-07, retirement 2027-05-07 or later), regions `global`/`us`/`eu`
  (no `us-east1`), structured output Supported, system instructions
  Supported, thinking MINIMAL/LOW/MEDIUM/HIGH, context 1M / 65K output.
- Thinking: Gemini 3 takes `thinking_level` only; pre-3 takes
  `thinking_budget` only; combining both (or a level on pre-3) errors.
  MINIMAL is closest to zero thinking but not guaranteed zero; thought
  signatures matter for multi-turn-with-history (our calls are stateless
  single requests — no issue observed). Thoughts billed at output rate.
- Pricing (non-global applies to `us` since 2026-07-01): 3.1
  $0.275/M in / $1.65/M out (global $0.25/$1.50); 2.5 $0.10/$0.40.
- 2.5 Flash-Lite: GA, `us-east1` + `global` supported — and **retirement
  2026-10-20**, four weeks out; any 2.5 decision must weigh that date.
- Few-shot guidance followed: ≤2 synthetic contrastive examples,
  INPUT/OUTPUT-labeled, teaching boundaries not literals; token delta
  measured, not optimized per failing utterance.
- SDK: installed `google-genai==2.23.0` already exposes `ThinkingLevel`
  (MINIMAL..HIGH) and `thoughts_token_count`; no dependency change.

### 12.2 Adapter compatibility (3.1)

- `GeminiBaseline` gains optional `thinking_level` (env
  `CU013_VERTEX_THINKING_LEVEL`); `_config()` selects level-xor-budget
  and fails closed on unknown levels; no wire/schema/retry/tool change.
- Smoke (1 synthetic call, `us`, MINIMAL, same system prompt + response
  schema): parsed route+goal correctly, usage present (prompt/completion/
  total, no thought tokens reported), no second call, no sensitive
  content. PASS with no adapter redesign.
- Usage now records `reasoning_tokens` (counts only, never memory).
  Temperature/top-p/top-k unset on both arms (identical SDK effective
  defaults).

### 12.3 Grid design (6 arms, identical text per strategy)

- S0 = C1′ wording byte-identical (pinned by test); S1 = diet (same
  properties condensed, decision line last); S2 = S1 + 2 synthetic
  contrastive examples (REGRESS-vs-CORRECT + ADVANCE-vs-KEEP + absent-data).
- Focused set (12 families, 21 trials × 3 reps = 63/arm): retroactive,
  lost-step, side-return, goal-correction, handoff, direct-request,
  grounding, confirmation-affirmative, pending, unknown, confirmed±.
- 2.5 ran in `us-east1`/budget-0; 3.1 in `us`/MINIMAL. Location
  confounds latency only (never claimed apples-to-apples).
- Cost guard: measured Q12 Vertex ≈ US$0.64; cumulative 0009 ≈ US$1.24
  of the US$3 round — holds with headroom. No cloud spend.

### 12.4 Focused matrix (63/63 valid each, 0 criticals everywhere)

| Arm | Reps P/F | REGRESS /6 | ADVANCE+ /6 | hyper | KEEP /18 | handoff /15 | direct /6 | grounding /6 | prompt p50 | reasoning |
|---|---|---|---|---|---|---|---|---|---|---|
| 25S0 | 51/12 | 0 | 0 | 0 | 18 | 12 | 3 | 6 | 1836 | ~0 |
| 31S0 | 53/10 | **3** | **4** | 0 | 18 | **15** | **6** | 5 | 2205 | 0 |
| 25S1 | 56/7 | 0 | 0 | 0 | 18 | 15 | 3 | 6 | 1711 | ~0 |
| 31S1 | 52/11 | 0 | 0 | 0 | 18 | 15 | 6 | 4 | 2080 | 0 |
| 25S2 | 52/11 | 0 | 2 | 0 | 18 | 10 | 5 | 6 | 1874 | ~0 |
| 31S2 | 53/10 | 0 | 1 | 0 | 18 | 15 | 6 | 6 | 2243 | 0 |

Causal reading: MODEL_EFFECT (31S0 alone adopts REGRESS/ADVANCE and
repairs handoff/direct under the unchanged S0 text); PROMPT_DILUTION
(25S1 beats 25S0 with −125 tokens); NO few-shot effect (25S2 handoff
drops to 10/15; 31S2 loses the 31S0 REGRESS). 3.1 counts ≈+370 prompt
tokens on identical text (tokenizer-side, consistent across strategies);
3.1/MINIMAL reported zero thought tokens on all 279 focused calls.
Promotion: single finalist 31S0 (only arm moving the central cue
properties; partial 3/6 REGRESS disclosed); no 2.5 arm qualifies (S1
tidies housekeeping but moves no central property).

### 12.5 Full paired eval (finalists only)

| Arm | Artifact | Valid/INFRA | Cases P/F | Reps P/F | Prompt p50 | Model p50/p95 | Session p50/max |
|---|---|---|---|---|---|---|---|
| B0 2.5 | `...064544-h7342586.infra-filled.json` | 174/0 | 46/12 | 153/21 | 1479 | 906/1156 ms | 367/642 |
| 31S0 | `...065145-h458dfcc.infra-filled.json` | 174/0 | 50/8 | 156/18 | 2208 (+729 explained) | 1109/1687 ms* | 978/1895, 0 over-guard |

\*: location-confounded (`us` vs `us-east1`); not a model-latency claim.
270/270 model calls each (one per transcript). Comparison (174 pairs,
declared `memory_variant,model_id,region,thinking_level`): 0 new
criticals, 36 targeted improvements, 9 targeted + 12 unrelated
regressions → NEEDS OWNER DECISION per comparator rules.

Material negative finding: 31S0 is HITL-eager — it opens challenges on
pure side questions (5 `side-question-during-plan` reps, against the
Accepted invariant) and authorized twice on continuations
("continuemos") after a side question plus once on a completion claim.
Every authorization was runtime-legal (eligible challenge + affirmative
reading), so the critical gate stays empty, but the *policy* (“a side
question never opens a challenge by itself”) is violated at model level.
B0 never does this. This alone blocks cloud promotion.

Spoken review (31S0, ephemeral, ratings only): lost-step MEETS;
side-return MEETS (same gratuity caveat as 2.5); grounding-t1 MEETS
(explicitly declines invented hours — fixed vs 2.5); grounding-t2 mild
CONCERN (hedged "generalmente inmediato"); promise MEETS; retro-t2 tense
CONCERN ("procedo a restablecer" pre-confirmation); retro-t3 CONCERN
(directs to the un-regressed step — follows state, misses caller need).

Latency microbenchmark: NOT executed — its trigger (two viable
finalists) was not met with only one partial finalist; Cloud Run Phase B
remains the venue for in-region measurement.

### 12.6 Deviations and harness fixes this round

1. `variant_digest` now `h`+15 hex: a bare all-digit digest suffix
   false-positived the PII sentinel and refused one full-run artifact
   (no leak; flake rate ≈2%). Regression test pins sanitizer-clean IDs.
   Old artifacts keep old digests (opaque, never parsed).
2. `_record_usage` uses defensive `getattr` for `thoughts_token_count`
   (older SDK doubles lack it; caught by test, not production).
3. One 31S0 rep needed five INFRA-fill attempts (provider blip cluster
   on one trial); merged missing-keys-only; all 174 valid, disclosed.

### 12.7 Implementer verdict

NO_CANDIDATE for the cloud benchmark yet. 31S0 is the leading
configuration (model effect real: REGRESS/ADVANCE/handoff/direct gains +
grounding-t1 fix, zero criticals, guards holding) but (a) REGRESS is
3/6 not consistent, (b) grounding-t2 still hedges invention, and (c) the
HITL-eagerness pattern (challenge on side questions → premature
authorization) violates an Accepted invariant at model level and must be
corrected first. 2.5 retires 2026-10-20 — the model decision is now
time-boxed independently of this experiment. Recommended next: a
targeted anti-eagerness correction round on 31S0 (side-question HITL
discipline + tense), then re-gate; Q12 proper is closed (no further
model/strategy arms without new evidence).

## 13. Focused 31S0 correction round S3 (executed 2026-09-18, implementer)

Scope: fix only 31S0 HITL eagerness and REGRESS instability with a
minimal policy-ordering delta. No new schema field (contract already
expresses side-question via NONE + no confirmation_request), no second
call, no few-shot, no global diet, no corpus change, no cloud. Q12 arms
are not re-run; 2.5 is untouched.

### 13.1 Grounding-hedge judgment (no over-correction)

"Puede variar, pero generalmente es inmediato" implies an unsupported
duration fact → stays a spoken-quality CONCERN, not a semantic FAIL
(oracles unaffected). The S0 grounding rule plus 3.1's explicit
hours-refusal show the mechanism works; the residue is hedge wording,
not a missing rule. No grounding rule was added.

### 13.2 The S3 delta

`_s3_precedence()` prepended to the verbatim S0 criteria (pinned by
test: shared lines identical, S0 substring intact, prefix <900 chars):
lateral question → answer + keep + no challenge/identity/authorize;
explicit execution → HITL per state; explicit human → handoff;
same-goal unfinished → REGRESS+NONE, completed → ADVANCE,
question/doubt/repeat → KEEP. Strategy `s3`, fingerprinted
(`prompt_strategy_hash`); S0/S1/S2 texts untouched. Runtime, schema,
corpus, caps, N=3 unchanged.

### 13.3 Verification discipline

A first-pass reading misattributed one rep (31S0's non-regress as S3's);
re-running the exact probe exposed it. Corrected strict tally below
counts only genuine REGRESS (advanced turn2 → microsoft/null turn3 with
goal untouched); the comparator's turn oracle cannot separate
never-advanced from regressed, which is disclosed wherever it matters.

### 13.4 Focused re-gate 31S0 vs 31S3 (9 families, 69/69 valid, 0 criticals)

- Eagerness FIXED: side-question-during-plan confirmation 5/5,
  side-question-return challenge+dispatch 3/3, goal-correction challenge
  2/2; zero unrelated regressions.
- KEEP 18/18 both; handoff and direct-request intact (no new failures);
  no systematic CORRECT-confusion in any S3 turn3 (all NONE, rev stable).
- Strict genuine REGRESS: S0 2, S3 1 (conditional on advance: 2/3 vs
  1/1); S3 ADVANCE recall lower (1 vs 3 turn2s) with zero hyper in both.
  The focused S3 REGRESS signal did not exceed S0 — reported, not hidden.
- 1 single-rep route flip (reset-direct, goal kept) — variance grade.

### 13.5 Full 31S0 vs 31S3 (174/174 valid, 0 INFRA, 0 model failures)

| Arm | Artifact | Cases P/F | Reps P/F | Prompt p50 | Model p50/p95 | Session p50/max |
|---|---|---|---|---|---|---|
| 31S0F | `...140349-h0a75b5c.infra-filled.json` | 48/10 | 151/23 | 2208 | 1203/2094 ms | 1004/1900 |
| 31S3F | `...141204-ha6a4aca.infra-filled.json` | 50/8 | 159/15 | 2364 (+156) | 1250/7781* ms | 958/1753, 0 over-guard |

Strategy hashes: S0 `7067925b0636`, S3 `3f1735379627`
(`prompt_strategy` is the only differing prompt dimension).
270/270 model calls each; reasoning tokens 0 both; completion flat.
\*p95 tail from provider outliers on both arms (max 10.9s/12.2s); p50
flat (+47 ms). Comparison: 0 new criticals, eagerness fixes hold at
scale, handoff 15/15 and direct 6/6 both arms, 6 unrelated single-rep
wobbles (classifications unchanged except 2 isolated reps) →
NEEDS OWNER DECISION per comparator rules.

REGRESS at scale: S0 3 genuine /12, S3 0 /12 (S3 turn2s advanced only
3/12 vs S0 5/12). The S3 conservative bias ("ante duda NONE") cut both
false advances AND true ones. Lesson recorded: the minimal delta fixed
the safety defect but did not make REGRESS adoptable — cue adoption is
model-limited, and instruction stacking shows diminishing/negative
returns (S1/S2/Q12 evidence concurs).

Spoken review (S3, ephemeral, ratings only): lost-step MEETS; retro-t2
MEETS; retro-t3 verbally correct (names Microsoft) despite un-regressed
state; grounding t1/t2 CONCERN (24h + immediacy invented — persists);
switch MEETS; side-return MEETS (cost answer + DTMF-channel-correct
identity routing); promise MEETS.

### 13.6 Token accounting (within-3.1 only, per §7)

Rendered block on a fixed synthetic 3-pair window: S0 1949 chars /
1988 B → S3 2582 chars / 2644 B (+633 chars measured, no sensitive
content persisted). Observed promptTokenCount p50 +156, completion
flat. No 3.1-vs-2.5 token inference is drawn (documented
tokenizer/counting differences).

### 13.7 Spend and verdict

This round ≈ US$0.41 Vertex (3.1 only); cumulative 0009 ≈ US$1.65 of
US$3 — guard holds. Per §5/§10 STOP rules REGRESS stayed inconsistent
after the minimal delta, so autonomous promotion stops here despite the
eagerness fix and the 159/15 verdict lead. **NOT_READY_FOR_CLOUD_BENCHMARK**:
S3 removes the safety blocker and dominates overall, but REGRESS is
0/12 genuine at scale and ADVANCE recall dropped 5→3 — the owner must
decide whether (a) to cloud-benchmark 31S3 for capacity anyway
(capacity does not need REGRESS; all capacity guards green), (b) to
accept the limitation as the Q12 closeout, or (c) to order new evidence.
No further instruction stacking is recommended. The cloud runbook stays
prepared; 31S3's fingerprint for any authorized run: model
`gemini-3.1-flash-lite`, `us`, `thinking_level=MINIMAL`, strategy S3
(`3f1735379627`), renderer `d94ebd412bb1`, memory caps/N=3 unchanged.

## 14. S4 structured-classification gate (executed 2026-09-18, implementer)

Scope: test whether forcing `procedure_observation` as an explicit,
early classification fixes REGRESS adoption. No new field/enum/call,
no runtime/memory/wire/cloud change, no 2.5/S1/S2 re-runs.

### 14.1 Inspection (no assumptions made)

Effective sent contract (Pydantic + SDK `process_schema` source-read):
`procedure_observation` OPTIONAL with visible default NONE, generated
6th of 8 — after goal (3rd) and both confirmation fields; SDK
auto-emits `propertyOrdering` in definition order. Prompt order differs:
goal is specified in the system head while the cue lives only in the
renderer tail. Both halves of the hypothesis premise verified material;
early-stop did not trigger (field is neither required, nor emitted
every turn, nor before goal fields).

Emission baseline (8 raw probes, S3, 3.1, temp script, synthetic):
field emitted 4/8 — 3/3 REGRESS on isolated retractions, 1 ADVANCE on
explicit completion; correctly omitted (→NONE) on side/direct/handoff
turns. So the model already emits explicitly when it judges relevance;
omission equals correct NONE, not laziness. S4 therefore tests the
sharpened hypothesis (explicit-FIRST classification), not a strawman.

### 14.2 Minimal S4 delta (schema-send only)

`response_schema_for(baseline)`: default arm sends the shared contract
byte-identical; strict arm (`CU013_VERTEX_STRICT_PROC_OBS=1`) sends a
transformed copy — same 8 fields (parity-tested), `procedure_observation`
required with no default, ordered before goal, explicit
`propertyOrdering`. Parsing stays lenient (NONE default fills), so an
omission is measured as defaulted, never a new turn-failure mode.
Adapter records key-presence counters (keys only, PII-safe); lab gains
`proposed_procedure_observation` + `procedure_observation_emitted` per
turn. Fingerprints: `strict_procedure_observation` + effective
`response_schema_hash`. Smoke (strict, 1 call): accepted, REGRESS parsed.
Deterministic: 310 passed, ruff/mypy clean, corpus 47/0.

### 14.3 Focused gate 31S3 vs 31S4 (69/69 valid, 0 INFRA, 0 criticals)

- Emission: 6/99 → **99/99**; values NONE 93→87, ADVANCE 4→**6**,
  REGRESS 2→**6**; hyper-advance 0 both; KEEP-side NONE now explicit
  rather than defaulted.
- Genuine REGRESS (advanced turn2 → untouched-goal microsoft/null
  turn3): 2 → **6/6**; no CORRECT-confusion in any S4 turn3.
- Comparator: 6 targeted improvements (all retroactive procedure),
  3 targeted regressions, 0 unrelated, efficiency flat (+5 prompt /
  +12 completion — the emitted cue).
- Regressions inspected: 1 early-but-legal dispatch on a completion
  turn (eligible challenge, no critical), and **2 challenge-opens on
  pure side questions** — partial HITL-eagerness return (no dispatch
  followed). Handoff 15/15 and direct 6/6 intact both arms.
- Gate: REGRESS materially fixed ✓; KEEP ✓; ADVANCE no hyper ✓;
  eagerness criterion failed (2 reps) → no full eval per §6; no S5.

### 14.4 Verdict and SFT note

**S4_PROMISING**: the structured-classification hypothesis is confirmed
(required + early cue drives 6→99 emission and 2→6 genuine REGRESS with
zero new failure modes), but promotion is blocked on the 2-rep
eagerness return. Full eval skipped by rule; Q12 closeout stands with
S3 (safe) and S4 (capable-but-eager) characterized.

SFT read-only note (no tuning executed, per handoff sources only):
Gemini 3.1 Flash-Lite supervised tuning is the owner-cited path;
classification/chat are supported use cases; start ≈100 high-quality
examples; tuning jobs live in `us-central1`/`europe-west4` while tuned
serving is `us`/`eu`-only; controlled generation on tuned models can
degrade through training/inference misalignment. SFT deserves separate
planning **only** if the owner accepts that prompt/schema evidence is
exhausted — it is not proposed automatically. This round ≈ US$0.20
Vertex; cumulative 0009 ≈ US$1.85 of US$3.

## Correcciones de revisión

1. **Orden:** B0/P/C1 y sus límites quedan como candidato y evidencia con fingerprint; SPEC/ADR/CONTEXT/CHANGELOG se actualizan sólo tras resultados y decisión del owner. Las SPEC vigentes describen comportamiento aceptado, no hipótesis de esta ronda.
2. **Privacidad:** la política ausente de PII incidental bloquea memoria de callers reales, pero permite el ensayo sintético no sensible y aislado. La retención productiva sigue sin aceptarse.
3. **Cloud Run:** se corrigió la distinción entre flags de revisión y servicio y el alcance del máximo service-level para tags; el pre-state y el rollback ahora incluyen `latestRevision` frente a `revisionName`. La revisión tagged es la primera opción si su restauración es demostrable; el servicio temporal se compara sólo ante un riesgo concreto.
4. **Firestore:** el race test antecede a cualquier cambio de escritura. La discrepancia `set(option)` de la documentación 2.29.0 y la firma instalada 2.30.0 quedan como incertidumbre de API/comportamiento, a verificar antes de escoger una precondition; no se prescribe `update()` ni transacción.
5. **Decisiones y autorización:** no se identificó una nueva decisión ya aceptada que exija cambiar SPEC antes del experimento. El implementer puede recibir el handoff sintético B0→P→C1, lab y métricas; el owner aún debe decidir retención/PII y comportamiento productivo después de evidencia. Las revisiones, gasto Vertex/Firestore y cleanup cloud necesitan autorización separada; aquí no se ejecutó benchmark ni mutación cloud.

## 15. Selección del perfil conversacional (ejecutada, evidencia 2026-09-19)

Scope: cerrar la selección sintética sin abrir experimento técnico
nuevo. Este capítulo no reescribe los §§1–14; los conserva como
trayectoria. La nomenclatura descriptiva rige desde aquí: la variante
histórica denominada en este documento «clasificación procedimental
estructurada obligatoria» fue la seleccionada; después se usa
exclusivamente ese nombre. Lo mismo aplica a «memoria conversacional
reciente» (ventana de tres pares) y a «Gemini 3.5 Flash-Lite».

- Descartados y archivados: variantes de prompt compacto y de
  confirmación (evidencia en runs `165445`–`170934`), proveedores
  externos evaluados vía bake-off (pantallas y `D1*`, sin full
  verificable para Baseten) y defaults a Gemini 2.5/3.1. El adapter
  externo, el endpoint temporal de benchmark, su script de deploy y sus
  tests fueron retirados del runtime activo tras archivar fuente, hashes
  y metodología; el scorer histórico se conserva aislado como evidencia.
- Focused: Gemini 3.1 y 3.5 con el perfil aceptado (runs `000811`,
  `001146`, `000938`, `001509`); una sola repetición de goal-correction
  y laterales contienen los FAIL visibles, sin dispatch ni criticals.
- Full final: `fullA-rescored` (SHA `8bcc6bb9…`) y `fullB-rescored`
  (SHA `4d06ec08…`), 47 casos/39 familias × 3 repeticiones; Gemini 3.5:
  174/174 válidos, 0 INFRA, 0 fallos de modelo, 0 criticals, 142/174
  PASS general; latencia backend de llamadas al modelo p50 ≈987 ms /
  p95 ≈1258 ms (nearest-rank, excluidos eventos sin modelo). Rescore
  sólo de ruta runtime; rows inmutados; fusión `fixA` declarada.
- Scorecard: reconstrucción trazable en
  `evals/conversation/selection-evidence/` con numeradores,
  denominadores, tratamiento de INFRA/oracle/reruns y cero criticals.
  Las definiciones R/H/COMBINED del owner no se encontraron en `evals/`
  ni `docs/`; no se sustituyen por el PASS general. Veredicto:
  EVIDENCE_INSUFFICIENT para el freeze hasta formalizar el scorecard,
  con la selección del modelo cerrada.
- Riesgos aceptados por el owner: avance procedimental prematuro raro
  bloqueado por guards, variación semántica segura, p50 sobre el ideal
  y p95 dentro del objetivo backend. Guards intactos; sin retención
  real; capacidad ocho callers, timeout/fallback, Q9, XCALLY E2E y
  comparativa regional siguen diferidos.
- Limpieza cloud de esta búsqueda: no demostrada localmente; acceso
  read-only con fallo TLS/OAuth → NO DISPONIBLE. Sin mutación.
