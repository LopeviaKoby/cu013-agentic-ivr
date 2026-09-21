"""Deterministic doubles and synthetic fixtures for the boundary tests.

No model, network, Firestore or credentials are involved. Every value is
synthetic and PII-safe.
"""

SYNTHETIC_API_KEY = "synthetic-api-key-0000"
SYNTHETIC_TRANSCRIPT = "synthetic transcript 0000"
SYNTHETIC_DTMF = "SYNTHETIC-DTMF-0000"
SYNTHETIC_MESSAGE = "synthetic message 0000"
SYNTHETIC_OPERATION_ID = "synthetic-operation-0000"

TURNS_URL = "/api/v1/conversations/{conversation_id}/turns"
INTEGRATION_EVENTS_URL = "/api/v1/conversations/{conversation_id}/integration-events"


def turns_url(conversation_id: str) -> str:
    return TURNS_URL.format(conversation_id=conversation_id)


def integration_events_url(conversation_id: str) -> str:
    return INTEGRATION_EVENTS_URL.format(conversation_id=conversation_id)
