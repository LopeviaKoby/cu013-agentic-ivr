"""Durable contract tests: closed whitelist, mapping and PII exclusion."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.session.record import (
    SCHEMA_VERSION,
    Action,
    OperationStatus,
    PendingOperation,
    SessionRecord,
    session_record_from_document,
    session_record_to_document,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

DOCUMENT_WHITELIST = {
    "schema_version",
    "conversation_id",
    "turn_count",
    "revision",
    "identity_validated",
    "requested_action",
    "pending_operation",
    "created_at",
    "updated_at",
}

PII_SENTINELS = ("SYNTHETIC-DOC-0000", "1900-01-01-SYNTHETIC", "SYNTHETIC-PASSWORD-0000")


def make_record(**overrides: object) -> SessionRecord:
    values: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "conversation_id": "conversation-1",
        "turn_count": 2,
        "revision": 2,
        "identity_validated": True,
        "requested_action": Action.RESET_PASSWORD,
        "pending_operation": PendingOperation(
            operation_id="operation-1",
            action=Action.RESET_PASSWORD,
            status=OperationStatus.PENDING,
        ),
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return SessionRecord(**values)


def test_new_record_is_semantic_and_empty() -> None:
    record = SessionRecord.new("conversation-1", now=NOW)
    assert record.schema_version == SCHEMA_VERSION
    assert record.conversation_id == "conversation-1"
    assert record.turn_count == 0
    assert record.revision == 0
    assert record.identity_validated is False
    assert record.requested_action is None
    assert record.pending_operation is None
    assert record.created_at == NOW
    assert record.updated_at == NOW


def test_document_whitelist_is_exact() -> None:
    assert set(session_record_to_document(make_record())) == DOCUMENT_WHITELIST


def test_document_round_trip_preserves_the_record() -> None:
    record = make_record()
    assert session_record_from_document(session_record_to_document(record)) == record


def test_pending_operation_and_action_persist_as_values() -> None:
    document = session_record_to_document(make_record())
    assert document["requested_action"] == "RESET_PASSWORD"
    assert document["pending_operation"] == {
        "operation_id": "operation-1",
        "action": "RESET_PASSWORD",
        "status": "pending",
    }


def test_timestamps_are_datetimes_for_native_firestore_timestamps() -> None:
    document = session_record_to_document(make_record())
    assert isinstance(document["created_at"], datetime)
    assert isinstance(document["updated_at"], datetime)


def test_unwhitelisted_durable_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_record(document_number="SYNTHETIC-DOC-0000")


def test_raw_identity_value_is_not_a_valid_durable_value() -> None:
    with pytest.raises(ValidationError):
        make_record(identity_validated="SYNTHETIC-DOC-0000")


def test_stored_document_with_unwhitelisted_field_is_rejected() -> None:
    document = session_record_to_document(make_record())
    document["password"] = "SYNTHETIC-PASSWORD-0000"
    with pytest.raises(ValidationError):
        session_record_from_document(document)


def test_stored_document_missing_a_whitelisted_field_is_rejected() -> None:
    document = session_record_to_document(make_record())
    del document["requested_action"]
    with pytest.raises(ValidationError):
        session_record_from_document(document)


def test_persisted_document_never_contains_pii_sentinels() -> None:
    rendered = repr(session_record_to_document(make_record()))
    for sentinel in PII_SENTINELS:
        assert sentinel not in rendered
