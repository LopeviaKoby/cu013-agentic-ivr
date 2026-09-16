"""Deterministic doubles and synthetic fixtures for the boundary tests.

No model, network, Firestore or credentials are involved. Every value is
synthetic and PII-safe.
"""

SYNTHETIC_API_KEY = "synthetic-api-key-0000"
SYNTHETIC_TRANSCRIPT = "synthetic transcript 0000"
SYNTHETIC_DTMF = "SYNTHETIC-DTMF-0000"
SYNTHETIC_MESSAGE = "synthetic message 0000"

TURNS_URL = "/api/v1/conversations/{conversation_id}/turns"


def turns_url(conversation_id: str) -> str:
    return TURNS_URL.format(conversation_id=conversation_id)
