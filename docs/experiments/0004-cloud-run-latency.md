# Experiment 0004: Cloud Run DEV warm baseline (pre-XCALLY E2E)

- Status: Completed
- Lifecycle: Planned → Running → Completed
- Authority: Experimental evidence only; not an architectural decision
- Date: 2026-09-16

## Question and hypothesis

What is the measured latency of the real backend path when the boundary runs
on Cloud Run `us-east1` with one warm instance, compared against the local
DEV baseline of [Experiment 0003](0003-gemini-baseline-latency.md)?

```text
local HTTPS client
→ Cloud Run
→ Firestore load
→ Gemini 2.5 Flash-Lite
→ LangGraph/runtime
→ Firestore save
→ Cloud Run
→ local HTTPS client
```

This is still pre-XCALLY: no Cally Square, ASR or TTS. It is a DEV warm
baseline, not an SLO and not a final model selection.

## Artifact under measurement

```text
git sha (clean HEAD):  2a37b2a0b8819a8f4e3189d2722b3f759ae4adf5
image tag:             us-east1-docker.pkg.dev/cu013-xcally-agentic/
                       cu013-containers-dev/cu013-runtime-dev:2a37b2a...
image digest:          sha256:6ca03e035c00d7f5d2679c3350a4970f0277ac6d008ddd9a2addbdfcd5869ba5
revision (measured):   cu013-runtime-dev-00006-hn4 (100% traffic during the window)
revision after stop:   cu013-runtime-dev-00007-mnb (created by min-instances=0)
secret reference:      cu013-api-key-dev:2 (name and numeric version only; value never read)
```

Effective Cloud Run configuration (verified read-only):

```text
region:            us-east1
runtime SA:        cu013-runtime-dev@cu013-xcally-agentic.iam.gserviceaccount.com
cpu / memory:      1 vCPU / 512 MiB
concurrency:       1
min / max:         1 during the window → 0 after stop; max 1
billing:           request-based, CPU throttling on
ingress auth:      allow-unauthenticated (PROVISIONAL DEV; boundary auth stays X-API-Key)
model defaults:    project cu013-xcally-agentic, location us-east1,
                   model gemini-2.5-flash-lite, thinking_budget=0, attempts=1
```

## Methodology

- Real HTTPS from the local DEV host to the service URL; no ASGI shim.
- Preflight: missing key → 401, wrong key → 401, valid key → 200.
- 5 warmups, then 30 measured requests strictly sequential (RESET ×10,
  UNLOCK ×10, NEUTRAL ×6, one MULTI_TURN sequence of 4 turns on a single
  conversation).
- Client metrics: round-trip timing per request and per scenario (first,
  p50, p95, min, max, errors, timeouts, statuses).
- Server metrics: `turn_metric` lines from Cloud Logging of revision
  `00006-hn4` inside the measured window
  `2026-09-16T16:01:10.458331Z`–`2026-09-16T16:01:37.729027Z`; 30 of the 35
  groups in the window are the measured requests (the first 5 are warmups)
  and every group contains `handler`, `session_load`, `model`, `graph` and
  `session_save`; `runtime = graph − model` derived per request.
- Token counters only; no transcript, DTMF, model text or API key is ever
  recorded or printed.

## Client results (HTTPS round-trip, local host)

```text
preflight:  no_key=401  wrong_key=401  valid_key=200
measured:   30 requests, 0 errors, 0 timeouts, statuses {200: 30}
prefix:     cu013benchcr_1789574462
```

| Scenario | first | p50 | p95 | min | max |
|---|---|---|---|---|---|
| RESET (10) | 833.1 | 833.1 | 1744.1 | 703.1 | 1744.1 |
| UNLOCK (10) | 879.5 | 852.8 | 925.1 | 832.4 | 925.1 |
| overall (30) | 833.1 | 878.0 | 1145.4 | 703.1 | 1744.1 |

(ms). The recorded console output contains only RESET, UNLOCK and overall;
the owner confirmed the NEUTRAL and MULTI_TURN client-side aggregates are not
recoverable. Their server-side numbers are complete below, and no re-run was
performed: the warm window was closed and re-measuring would require a new
deployment window.

## Server results (in-region, revision 00006-hn4)

Overall, 30 measured requests, all segments complete in every group (ms):

| Segment | first | p50 | p95 | min | max |
|---|---|---|---|---|---|
| handler | 610.4 | 656.6 | 919.6 | 482.3 | 1526.3 |
| session_load | 26.5 | 12.6 | 36.2 | 7.9 | 42.9 |
| model | 546.3 | 595.3 | 794.7 | 430.5 | 1461.7 |
| graph | 550.6 | 603.0 | 798.2 | 434.3 | 1465.5 |
| runtime (graph − model) | 4.3 | 3.7 | 4.6 | 3.3 | 16.9 |
| session_save | 32.5 | 29.3 | 101.5 | 14.2 | 109.9 |

Token counters: prompt p50 406 (397–407), completion p50 48 (34–57),
total p50 452 (431–463).

Per scenario (p50 / p95, ms):

| Scenario | handler | load | model | runtime | save |
|---|---|---|---|---|---|
| RESET | 610.4 / 1526.3 | 22.8 / 42.9 | 546.3 / 1461.7 | 3.8 / 4.6 | 32.5 / 68.2 |
| UNLOCK | 656.6 / 919.6 | 11.4 / 21.4 | 627.2 / 794.7 | 3.5 / 4.0 | 25.4 / 109.9 |
| NEUTRAL | 693.3 / 774.4 | 10.1 / 17.6 | 665.9 / 729.7 | 3.7 / 4.2 | 17.7 / 30.2 |
| MULTI_TURN | 635.0 / 703.1 | 12.6 / 15.2 | 588.4 / 656.6 | 3.7 / 16.9 | 27.6 / 32.2 |

Outliers: one RESET request reached handler 1526.3 ms (model 1461.7 ms);
`runtime` max 16.9 ms was the first turn of the multi-turn conversation.
No errors, timeouts or missing segments in the measured set.

## Comparison against the local baseline (Experiment 0003)

Same model and flow; 0003 ran through ASGI in-process from the same host over
the public internet, 0004 runs on Cloud Run in-region.

| Segment | 0003 p50 | 0004 p50 | Δ | 0003 p95 | 0004 p95 | Δ |
|---|---|---|---|---|---|---|
| handler | 1281.0 | 656.6 | −48.7% | 1922.0 | 919.6 | −52.2% |
| session_load | 219.0 | 12.6 | −94.2% | 421.0 | 36.2 | −91.4% |
| model | 782.0 | 595.3 | −23.9% | 1062.0 | 794.7 | −25.2% |
| session_save | 234.0 | 29.3 | −87.5% | 266.0 | 101.5 | −61.9% |

The Firestore path collapses in-region (load and save are single-digit to
low-tens of milliseconds at p50); the model remains the dominant component
(p50 ≈595 ms, 91% of the handler p50) and the largest source of variance.
Client HTTPS round-trip (p50 878.0, p95 1145.4) adds roughly 220 ms over the
in-region handler at p50–p95 (internet RTT, TLS and ingress).

## Multi-turn continuity

The 4-turn sequence on one conversation completed with one saved document
per turn (4 saves, one conversation, routes handled per turn); the server
segments for the four turns are consistent with the durable projection
being reloaded each turn. The multi-turn client-side aggregate is not
recoverable from the recorded output; its four requests are complete in the
server-side dataset.

## Limitations

- Not voice E2E: no XCALLY, ASR endpointing or TTS;
  `end-of-speech → first useful audio` remains unknown.
- One warm instance only during the window; `min=0` was restored after the
  run (verified read-only). Cold-start latency is not measured.
- Sequential requests, concurrency 1, n=30; no concurrency benchmark.
- `turn_metric` lines carry no per-turn ID and the application `turn handled`
  lines do not reach Cloud Logging in this revision (only `cu013.metrics` has
  an INFO handler), so scenario attribution is by strict sequential order.
- The recorded client output has no NEUTRAL and MULTI_TURN client-side
  aggregates (confirmed not recoverable); their in-region server segments
  are complete.
- Client numbers are from one local host and one network path.

## Synthetic data inventory (no deletion performed)

97 documents in `cu013dev_sessions`:

```text
cu013benchcr_1789574462  (this run)          33
cu013audit-20260916-metrics-01                1
cu013bench_1789534751    (session 3, run 1)  31
cu013bench_1789534995    (session 3, run 2)  32
```

Deletion requires explicit owner authorization; no wildcard or
collection-group deletes were used. Experiment 0003's inventory note is
corrected from "54" to the inventoried 63 documents.

## FS-002 reevaluation

FS-002 stays open. The in-region evidence now bounds Firestore I/O
(load p95 36.2 ms, save p95 101.5 ms; max 42.9 / 109.9 ms) and confirms the
SDK defaults (60 s/300 s) are unjustifiable as productive policy, but the
value cannot be fixed responsibly until the full voice budget is measured
(XCALLY, ASR endpointing, TTS); the indicated range is low hundreds of
milliseconds per call. See [Gaps de implementación](../gaps.md).

## Conclusion

The pre-XCALLY path works end-to-end on Cloud Run with one warm instance:
30/30 measured requests succeeded, the boundary authentication behaved
exactly as in DEV, and in-region latency is roughly half the local baseline
at p50 and p95. The model dominates the remaining latency; the voice budget
question now depends on the still-unmeasured ASR/TTS/XCALLY segments. The
service is back at `min=0`.

## References

- [Experiment 0003 — local Gemini baseline](0003-gemini-baseline-latency.md)
- [Boundary HTTP XCALLY ↔ CU013](../specs/xcally-boundary.md)
- [Runbook Cloud Run DEV benchmark](../runbooks/cloud-run-dev-benchmark.md)
- [Gaps de implementación](../gaps.md)
