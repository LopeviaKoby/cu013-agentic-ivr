---
name: cu013-xcally-contract
description: Operates and maintains the telephony HTTP contract between XCALLY / Cally Square IVR and the backend.
---

# cu013-xcally-contract

## Responsibility
Maintain and enforce the strictly validated REST contract for POST `/turn` invoked by XCALLY Motion / Cally Square voice platform.

## Allowed Changes
- Adjusting field validators in Pydantic contracts for edge-case telephony inputs.
- Adding supported routing enum variants if approved by protocol definitions.

## Forbidden Changes
- Introducing legacy fields (`speech_ssml`, `listen`, `hangup`, `escalate`, `message`).
- Changing HTTP endpoints or making `/turn` stateful across raw connections.
- Adding API keys or unauthenticated custom protocol headers without approval.

## Inputs / Contracts
- `POST /turn`: `TurnRequest` with `conversation_id: str` and `text: str`.

## Outputs / Contracts
- `TurnResponse`: `turn_id: str`, `route: Route` (`CONTINUE | COLLECT_IDENTITY | COMPLETE | ESCALATE`), `text: str`.

## Trusted References
- [docs/XCALLY_CONTRACT.md](../../docs/XCALLY_CONTRACT.md)
- [AGENTS.md](../../AGENTS.md)

## Quality Checks
- `pytest tests/test_turn.py`
- Pydantic validation rejects empty `conversation_id` and empty `text`.

## STOP Conditions
- XCALLY requires fields not defined in [docs/XCALLY_CONTRACT.md](../../docs/XCALLY_CONTRACT.md).
- Ambiguity in routing semantics across telephony legs.
