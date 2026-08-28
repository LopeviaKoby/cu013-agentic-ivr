---
name: cu013-firestore-session
description: Operates and maintains durable conversation session persistence in Google Cloud Firestore.
---

# cu013-firestore-session

## Responsibility
Persist and retrieve multi-turn conversational session states cleanly and minimally in Firestore `(default)` database.

## Allowed Changes
- Adding minimal session metadata required for dialogue progression.
- Tuning document serialization and TTL policies.

## Forbidden Changes
- Using an in-memory session store in production.
- Creating complex event-sourcing or turn-by-turn subcollections without proven necessity.
- Storing unredacted PII or sensitive authentication credentials in session documents.
- Duplicating legacy V1 schema structures.

## Inputs / Contracts
- `conversation_id: str`, `SessionData` instances.

## Outputs / Contracts
- Loaded `SessionData | None`, successful persistence futures.

## Trusted References
- [app/firestore.py](../../app/firestore.py)
- [AGENTS.md](../../AGENTS.md)

## Quality Checks
- `pytest tests/test_firestore.py`
- Serialization / deserialization roundtrip tests.

## STOP Conditions
- Firestore permission or quota failure on `planillas-acv-tivit`.
- Document schema changes requiring large legacy migration.
