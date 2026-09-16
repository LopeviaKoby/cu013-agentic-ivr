"""Thin Firestore Session Repository.

Durable contract, ephemeral turn state and the one-read/one-write turn cycle.
"""

from app.session.record import (
    Action,
    OperationStatus,
    PendingOperation,
    SessionRecord,
    session_record_from_document,
    session_record_to_document,
)
from app.session.repository import (
    FirestoreSessionDocumentStore,
    SessionDocumentStore,
    SessionPersistenceError,
    SessionRepository,
)
from app.session.service import TurnService, consolidate
from app.session.turns import GraphState, TurnGraph, TurnInput, build_turn_graph

__all__ = [
    "Action",
    "FirestoreSessionDocumentStore",
    "GraphState",
    "OperationStatus",
    "PendingOperation",
    "SessionDocumentStore",
    "SessionPersistenceError",
    "SessionRecord",
    "SessionRepository",
    "TurnGraph",
    "TurnInput",
    "TurnService",
    "build_turn_graph",
    "consolidate",
    "session_record_from_document",
    "session_record_to_document",
]
