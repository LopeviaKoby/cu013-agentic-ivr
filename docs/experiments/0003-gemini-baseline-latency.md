# Experiment 0003: Gemini 2.5 Flash-Lite DEV backend latency baseline

- Status: Completed
- Lifecycle: Planned → Running → Completed
- Authority: Experimental evidence only; not an architectural decision
- Date: 2026-09-16

## Question and hypothesis

Can the real conversational engine — `gemini-2.5-flash-lite` over Vertex AI
behind the typed `TurnModel` seam — run inside the thin session turn with
exactly one model call, one Firestore load and one Firestore save per turn,
and what is the measured per-segment latency of the full backend path from
the DEV host?

This measurement is a DEV baseline, not an SLO and not a final model
selection. It is the evidence gate required before AD/TIVIT.

## Configuration

Effective baseline (single replaceable object, `app/conversation/gemini.py`):

```text
provider:         vertex_ai
project:          cu013-xcally-agentic
location:         us-east1
model:            gemini-2.5-flash-lite
api_version:      v1
thinking_budget:  0
timeout_ms:       15000 (harness bound, single attempt)
attempts:         1 (no hidden SDK retries)
```

Authentication: ADC impersonation of the planned runtime identity
`cu013-runtime-dev@cu013-xcally-agentic.iam.gserviceaccount.com`
(`roles/datastore.user` + `roles/aiplatform.user`). No Gemini API key and no
service-account JSON.

## Environment

```text
host:            local DEV workstation running OpenCode
network:         public internet to us-east1
Firestore:       (default), collection cu013dev_sessions
boundary:        real FastAPI app via httpx ASGI transport
```

## Methodology

- The benchmark drives the FastAPI boundary only: real API-key auth, real
  request validation, real engine, real Firestore and real Vertex AI.
- 5 warmup requests, then 30 measured requests, sequential.
- Scenarios: 13 RESET, 13 UNLOCK, one 4-turn multi-turn sequence on a single
  conversation (26 fresh conversations + 1 reused = 27 documents per run).
- Segments (monotonic clock): `handler`, `session_load`, `model`, `graph`,
  `session_save`, `total`; `runtime = graph - model` (derived).
- Percentiles: nearest-rank. Recorded per segment: first measured request,
  p50, p95, min, max, error count.
- PII-safe: transcripts are synthetic; no transcript, DTMF or generated text
  is recorded or printed. Token counters only, never content.
- Two executions were performed. The first (exploratory, prefix
  `cu013bench_1789534751`) validated the harness; the second
  (`cu013bench_1789534995`, with route/error-code capture) is the canonical
  dataset reported below.

## Authentication blocker (recorded)

The first execution attempt failed on every warmup: ADC still impersonated
`cu013-spike-firestore`, which lacks `aiplatform.endpoints.predict`
(403 PERMISSION_DENIED). The owner recreated ADC impersonation for
`cu013-runtime-dev`; the first attempt then failed with
`iam.serviceAccounts.getAccessToken` denied, and the owner granted
`roles/iam.serviceAccountTokenCreator` on `cu013-runtime-dev`. After that,
Firestore read and a minimal Vertex call (`thinking_budget=0`,
`FinishReason.STOP`) succeeded and the benchmark ran. No IAM or
infrastructure change was made by the agent.

## Results (canonical run, 30 measured requests, 0 errors)

Overall, ms:

| Segment | first | p50 | p95 | min | max |
|---|---|---|---|---|---|
| handler | 1922 | 1281 | 1922 | 1140 | 4563 |
| session_load | 843 | 219 | 421 | 218 | 843 |
| model | 813 | 782 | 1062 | 672 | 4094 |
| graph | 829 | 796 | 1062 | 672 | 4109 |
| runtime (graph − model) | 16 | 0 | 30 | 0 | 31 |
| session_save | 250 | 234 | 266 | 218 | 281 |
| total | 1922 | 1281 | 1922 | 1140 | 4563 |

Token counters (counts only): prompt tokens p50 406 (range 397–407),
completion p50 49 (34–59), total p50 456 (432–465). The prompt is dominated
by the system instructions.

Scenario summary:

| Scenario | requests | errors | routes observed |
|---|---|---|---|
| RESET | 13 | 0 | COLLECT_IDENTITY ×13 |
| UNLOCK | 13 | 0 | COLLECT_IDENTITY ×13 |
| MULTI_TURN | 4 | 0 | CONTINUE → COLLECT_IDENTITY → COLLECT_IDENTITY → CONTINUE |

Every route was validated by the typed decision contract
(`extra="forbid"`); no invalid model output occurred in the canonical run.

Exploratory run (same methodology, prefix `cu013bench_1789534751`): 29/30
succeeded with p50 handler ≈1297 ms, consistent with the canonical run; one
UNLOCK request failed after a model segment of ≈13.9 s (below the 15 s
harness timeout; the error code was not captured in that script version).

## Multi-turn continuity

The 4-turn sequence on one conversation persisted exactly one semantic
document: `turn_count=4`, `revision=4`, `identity_validated=False`,
`requested_action=None`. Semantic continuity across turns works; each model
call received the updated durable projection. Content-level conversational
history is absent by design (no history in `SessionRecord`) and remains out
of scope for this session.

## FS-002 reevaluation

With measured evidence, FS-002 stays open. See
[Gaps de implementación](../gaps.md). Summary: the mechanism (per-call
`timeout`) exists; the value cannot yet be fixed defensibly within the
<2 s voice budget because the model tail dominates and the ASR/TTS/XCALLY
segments plus in-region Cloud Run latency are unmeasured.

## Limitations

- Local DEV workstation over public internet: load/save include WAN RTT and
  do not represent Cloud Run in-region latency.
- httpx ASGI in-process transport: no real ingress network, no TLS.
- Sequential requests only; no concurrency benchmark.
- ASR endpointing, TTS and XCALLY network time are not measured;
  `end-of-speech → first useful audio` remains unknown.
- Model tail is the dominant variance: max 4.1 s canonical; the exploratory
  run observed one ≈14 s model call that errored (single attempt, no
  retries).
- Token counts are counters only; no model content was captured.
- 54 benchmark documents (2 runs × 27) remain under `cu013dev_sessions`;
  deletion was not authorized and was not performed.

## Conclusion

`gemini-2.5-flash-lite` is integrated as the first real engine with one
model call, one load and one save per normal turn, and the DEV backend
baseline is measured end-to-end through the boundary. Backend p50 ≈1.28 s
(65% of the 2 s voice budget without ASR/TTS/XCALLY) and p95 ≈1.92 s show
that the voice budget cannot be assumed and must be measured with the full
path before AD/TIVIT. FS-002 remains open with precise missing evidence.

## Adopted ADR and references

- [ADR-0007 — Evaluar Gemini 2.5 Flash-Lite](../decisions/0007-evaluate-gemini-25-flash-lite.md)
- [ADR-0009 — Thin Firestore Session Repository](../decisions/0009-use-thin-firestore-session-repository.md)
- [Boundary HTTP XCALLY ↔ CU013](../specs/xcally-boundary.md)
- [Especificación del sistema](../specs/system.md)
