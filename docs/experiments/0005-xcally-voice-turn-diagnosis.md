# Experiment 0005: XCALLY voice turn diagnosis and prior-request policy

- Status: Completed
- Lifecycle: Planned → Running → Completed
- Authority: Experimental evidence only; not an architectural decision
- Date: 2026-09-16

## Question and hypothesis

A real XCALLY voice turn with a compound request ("quiero desbloquear mi
cuenta pero antes explícame qué puedes hacer") was answered with
`COLLECT_IDENTITY` instead of answering the explicit prior question with
`CONTINUE`. Where is that route produced, is a keyword/regex NLU involved,
what semantic state did the model receive, and can the runtime preserve the
pre-auth action intent for the next turn?

Hypothesis before inspecting: the route comes from the model decision; the
runtime only governs legality/state; the prompt rule that orders
`COLLECT_IDENTITY` whenever identity is missing has no counterbalancing
instruction for an explicit prior question, so it pushes the model to skip
it. No durable conversational history exists to preserve the intent.

## Artifact under measurement

The serving revision was confirmed read-only before any code change:

```text
Cloud Run service:     cu013-runtime-dev (us-east1)
latest ready revision: cu013-runtime-dev-00008-7gz (100% traffic)
image tag:             us-east1-docker.pkg.dev/cu013-xcally-agentic/
                       cu013-containers-dev/cu013-runtime-dev:2a37b2a0b8819a8f4e3189d2722b3f759ae4adf5
image digest:          sha256:6ca03e035c00d7f5d2679c3350a4970f0277ac6d008ddd9a2addbdfcd5869ba5
min instances:         1 (warm window in progress at diagnosis time)
served commit:         2a37b2a0b8819a8f4e3189d2722b3f759ae4adf5
secret reference:      cu013-api-key-dev (name only; value never read)
```

`git diff --stat 2a37b2a0b8819a8f4e3189d2722b3f759ae4adf5 HEAD -- app tests`
is empty and `2a37b2a` is an ancestor of HEAD `11667bca`; only documentation
changed between the served commit and the inspected tree. The inspected
`app/` code is therefore the code that served the call.

## Evidence of the call

Correlation from the owner's XCALLY capture:

```text
conversation_id / UNIQUEID: Ivr02-1789592921.349324
turn_id:                    1dd80a99db2a4d7792ee828e5ebd845e
x-cloud-trace-context:      a57a84d9d4af0f9c5e926fe00a42e28c;o=1
XCALLY local time:          2026-09-16 16:09:00–16:09:01 America/Lima
HTTP Date / UTC:            2026-09-16 21:09:01 GMT
```

Cloud Logging (UTC window `21:08:50Z`–`21:09:15Z`, `us-east1`, service
`cu013-runtime-dev`) contains exactly one request; attribution of the
`turn_metric` lines is therefore defensible without per-turn identifiers:

| Measurement | Value (ms) | Class |
|---|---|---|
| Cloud Run request latency | 1 192.998 | OBSERVED |
| `handler` segment | 1 189.943 | OBSERVED |
| `session_load` segment | 135.305 | OBSERVED |
| `model` segment | 984.207 | OBSERVED |
| `graph` segment | 987.002 | OBSERVED |
| `session_save` segment | 67.160 | OBSERVED |
| `runtime` = `graph` − `model` | 2.795 | DERIVED |
| HTTP status | 200 | OBSERVED |
| Token counters (prompt/completion/total) | 410 / 48 / 458 | OBSERVED |
| Route `COLLECT_IDENTITY` | — | OBSERVED only in the XCALLY capture; NOT AVAILABLE server-side |
| End-of-speech / ASR endpointing | — | NOT AVAILABLE |
| XCALLY network-only latency | — | NOT AVAILABLE |
| TTS synthesis / first audible audio | — | NOT AVAILABLE |
| Full voice E2E | — | NOT AVAILABLE |

The application `turn handled conversation_id=… turn_id=… route=…` line is
absent from Cloud Logging: `app.api.app` logs at INFO but its logger has no
handler and the root level under Uvicorn suppresses it. Only
`cu013.metrics` emits INFO through its dedicated stderr handler. Server-side
route and `turn_id` are consequently not recoverable from logs for this
call; the XCALLY response is the observable evidence. This extends XC-002.

Read-only `SessionRecord` for the conversation (Firestore, no PII):

```text
turn_count=1, revision=1, identity_validated=False,
requested_action=None, pending_operation=None
created_at=2026-09-16T21:09:00.629687Z, updated_at=2026-09-16T21:09:01.616944Z
```

This was the first turn of the conversation, so the semantic projection the
model received is proven: `identidad_validada: no`,
`acción_solicitada: ninguna`, `operación_pendiente: ninguna`, plus the
current transcript. No conversational history is sent.

## Route origin (demonstrated in code)

```text
HTTP POST /turns
→ app/api/app.py handle_turn
→ app/conversation/engine.py SessionConversationEngine.handle_turn
→ app/session/service.py TurnService.handle_turn
→ LangGraph START → run_model → advance_turn → END
→ app/conversation/gemini.py GeminiTurnModel.decide
→ ModelTurnDecision (message, route, action_requested)
→ TurnOutcome(message=decision.message, route=decision.route)
```

- The model produces `route` initially; `parse_decision` validates it
  against the closed `Route` enum (`app/session/turns.py`).
- No runtime node rewrites `route`: `advance_turn` returns a `TurnDelta`
  (`identity_validated`, `requested_action`, `pending_operation`) and never
  reads or writes `model_decision.route`;
  `SessionConversationEngine` copies the model decision into the outcome.
- There is no keyword/regex NLU anywhere in `app/`; a repository-wide search
  for `re.`, `regex`, `keyword`, `startswith`, `transcript.lower` finds only
  docstrings and Firestore attribute names. The only semantic machinery is
  the model plus `app/conversation/gemini.py`'s system prompt.
- The prompt rule relevant to the failure was: "Usa COLLECT_IDENTITY cuando
  falte capturar el documento o la fecha de nacimiento del llamante" with no
  rule for an explicit prior informational request. That instruction, plus
  the `identidad_validada: no` state, is the only available semantic cause
  of the observed `COLLECT_IDENTITY`.
- Durable after the turn: `identity_validated`, `requested_action`,
  `pending_operation`, counters and timestamps. Transient and lost at turn
  end: transcript, the full model decision (including
  `action_requested`), and the ephemeral graph state.

## Correction

- The system prompt moved to `app/conversation/prompts.py`; `gemini.py`
  stays centered on provider, baseline config, transport, parsing and error
  mapping. The prompt remains versioned with the code; no prompt framework,
  external template, dynamic configuration, RAG or keyword routing was
  introduced, and model, `thinking_budget`, output schema and call count are
  unchanged.
- New policy rule (`PRIOR_REQUEST_RULE`, placed before the identity rule):
  when the caller expresses an action but prepends an explicit question,
  clarification, comparison or informational request, the assistant answers
  that request briefly and uses `CONTINUE`, and does not start
  `COLLECT_IDENTITY` until the conversation is ready to proceed.

## Deterministic coverage

- `tests/conversation/test_prompts.py`: the prompt documents every closed
  route and every decision field, and the prior-request policy precedes the
  identity-collection rule.
- `tests/api/test_turns.py`: the boundary preserves a model `CONTINUE` route
  and message, and a pre-auth `action_requested` suggestion remains
  transient (not durable).

## Real-model probe (manual, not CI)

`evals/conversation_policy_eval.py` calls the real model with ADC, one
process, no retries and no caching, at the baseline `gemini-2.5-flash-lite`,
`thinking_budget=0`. 5 repetitions of the compound transcript plus one
control per remaining trigger; only route, `action_requested` and latency
were recorded:

```text
PRIOR_REQUEST (×5):  CONTINUE 5/5, action_requested=null
                     latency 687–3516 ms (first call includes connection setup)
DIRECT_ACTION (×1):  COLLECT_IDENTITY, action_requested=UNLOCK_ACCOUNT
PRIOR_QUESTION (×1): CONTINUE, action_requested=null
```

The model emitted `action_requested=UNLOCK_ACCOUNT` before identity
validation in the direct control even though the prompt forbids it; the
runtime discarded it as designed (`advance_turn` only durably records an
action after `identity_validated=True`). Runtime remains the last word.

## Limitations

- The probe is one model and a synthetic sample; it is not a quality verdict
  and was not added to CI.
- The change is not yet validated with a DEV voice call: that requires an
  owner-authorized commit and deploy, because the serving revision still
  contains the old prompt.
- Server-side route/turn_id correlation is unavailable for this call (see
  above); XC-002 stays open.
- Pre-auth intent retention is not representable in the current durable
  session contract (see `docs/gaps.md`, `CNV-001`). The probe confirms the
  immediate contract only; it does not simulate retention.

## Conclusion

The premature `COLLECT_IDENTITY` is explained by the prompt policy, not by
any keyword/regex routing or runtime override, and the minimal correction
holds in 5/5 real-model repetitions while the direct-action control still
proceeds to identity collection. The pre-auth action intent remains
transient by design of the current contract; making it durable is an owner
decision.

## References

- [System specification](../specs/system.md)
- [Account actions specification](../specs/account-actions.md)
- [XCALLY boundary specification](../specs/xcally-boundary.md)
- [Implementation gaps](../gaps.md)
- [Experiment 0004: Cloud Run DEV warm baseline](0004-cloud-run-latency.md)
- [Conversation policy probe](../../evals/conversation_policy_eval.py)
