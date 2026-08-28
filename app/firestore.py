from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from google.cloud import firestore

from app.config import get_settings


@dataclass
class SessionData:
    """Minimal conversation session state for Firestore persistence."""

    conversation_id: str
    turn_count: int = 0
    turns: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Serialize session data to a Firestore-compatible dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionData":
        """Deserialize Firestore document data into a SessionData instance."""
        return cls(
            conversation_id=data["conversation_id"],
            turn_count=data.get("turn_count", 0),
            turns=data.get("turns", []),
            created_at=data.get("created_at", datetime.now(UTC).isoformat()),
            updated_at=data.get("updated_at", datetime.now(UTC).isoformat()),
        )


_db: firestore.AsyncClient | None = None


def get_firestore_client() -> firestore.AsyncClient:
    """Return process-level singleton Firestore AsyncClient."""
    global _db
    if _db is None:
        settings = get_settings()
        _db = firestore.AsyncClient(
            project=settings.gcp_project_id,
            database=settings.firestore_database_id,
        )
    return _db


def reset_firestore_client() -> None:
    """Reset cached Firestore client (for testing)."""
    global _db
    _db = None


async def get_session(
    conversation_id: str, client: firestore.AsyncClient | None = None
) -> SessionData | None:
    """Load a session document by conversation_id from Firestore."""
    settings = get_settings()
    db = client or get_firestore_client()
    doc_ref = db.collection(settings.firestore_collection).document(conversation_id)
    snapshot = await doc_ref.get()

    if not snapshot.exists:
        return None

    data = snapshot.to_dict()
    if data is None:
        return None

    return SessionData.from_dict(data)


async def save_session(session: SessionData, client: firestore.AsyncClient | None = None) -> None:
    """Persist or update a session document in Firestore."""
    settings = get_settings()
    db = client or get_firestore_client()
    session.updated_at = datetime.now(UTC).isoformat()
    doc_ref = db.collection(settings.firestore_collection).document(session.conversation_id)
    await doc_ref.set(session.to_dict())
