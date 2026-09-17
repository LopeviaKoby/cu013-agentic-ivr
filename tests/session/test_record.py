"""Durable contract tests: closed whitelist, mapping, migration and PII exclusion."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.session.record import (
    IDENTITY_TTL,
    SCHEMA_VERSION,
    Action,
    DeliveryStatus,
    IdentityState,
    OperationStatus,
    SessionRecord,
    session_record_from_document,
    session_record_to_document,
)
from tests.session.doubles import make_identity, make_operation, make_record

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)

DOCUMENT_WHITELIST = {
    "schema_version",
    "conversation_id",
    "turn_count",
    "revision",
    "goal",
    "identity",
    "confirmation",
    "dispatch",
    "external_operation",
    "created_at",
    "updated_at",
}

PII_SENTINELS = ("SYNTHETIC-DOC-0000", "1900-01-01-SYNTHETIC", "SYNTHETIC-PASSWORD-0000")


def make_v1_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": 1,
        "conversation_id": "conversation-1",
        "turn_count": 3,
        "revision": 3,
        "identity_validated": True,
        "requested_action": "UNLOCK_ACCOUNT",
        "pending_operation": {
            "operation_id": "operation-1",
            "action": "UNLOCK_ACCOUNT",
            "status": "pending",
        },
        "created_at": NOW,
        "updated_at": NOW + timedelta(minutes=2),
    }
    document.update(overrides)
    return document


def test_new_record_is_semantic_and_empty() -> None:
    record = SessionRecord.new("conversation-1", now=NOW)
    assert record.schema_version == SCHEMA_VERSION
    assert record.conversation_id == "conversation-1"
    assert record.turn_count == 0
    assert record.revision == 0
    assert record.goal is None
    assert record.identity.validated_at is None
    assert record.identity.caller_failures == 0
    assert record.confirmation is None
    assert record.dispatch is None
    assert record.external_operation is None
    assert record.created_at == NOW
    assert record.updated_at == NOW


def test_document_whitelist_is_exact() -> None:
    assert set(session_record_to_document(make_record())) == DOCUMENT_WHITELIST


def test_document_round_trip_preserves_the_record() -> None:
    record = make_record()
    assert session_record_from_document(session_record_to_document(record)) == record


def test_semantic_planes_persist_as_values() -> None:
    document = session_record_to_document(
        make_record(
            goal={"action": "RESET_PASSWORD", "revision": 4},
            identity={"validated_at": NOW, "caller_failures": 1},
        )
    )
    assert document["goal"] == {"action": "RESET_PASSWORD", "revision": 4}
    assert document["identity"] == {"validated_at": NOW, "caller_failures": 1}
    assert document["confirmation"] is None
    assert document["dispatch"] is None
    assert document["external_operation"] is None


def test_timestamps_are_datetimes_for_native_firestore_timestamps() -> None:
    document = session_record_to_document(make_record())
    assert isinstance(document["created_at"], datetime)
    assert isinstance(document["updated_at"], datetime)
    assert isinstance(document["identity"]["validated_at"], datetime)  # type: ignore[index]


def test_unwhitelisted_durable_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_record(document_number="SYNTHETIC-DOC-0000")


def test_raw_identity_value_is_not_a_valid_durable_value() -> None:
    with pytest.raises(ValidationError):
        make_record(identity="SYNTHETIC-DOC-0000")


def test_delivery_status_only_applies_to_reset() -> None:
    with pytest.raises(ValidationError):
        make_operation(
            Action.UNLOCK_ACCOUNT,
            status=OperationStatus.CONFIRMED,
            delivery=DeliveryStatus.CONFIRMED,
        )


def test_stored_document_with_unwhitelisted_field_is_rejected() -> None:
    document = session_record_to_document(make_record())
    document["password"] = "SYNTHETIC-PASSWORD-0000"
    with pytest.raises(ValidationError):
        session_record_from_document(document)


def test_stored_document_missing_a_whitelisted_field_is_rejected() -> None:
    document = session_record_to_document(make_record())
    del document["identity"]
    with pytest.raises(ValidationError):
        session_record_from_document(document)


def test_stored_document_with_unknown_schema_version_is_rejected() -> None:
    document = session_record_to_document(make_record())
    document["schema_version"] = 99
    with pytest.raises(ValueError, match="unsupported durable schema version"):
        session_record_from_document(document)


def test_persisted_document_never_contains_pii_sentinels() -> None:
    rendered = repr(session_record_to_document(make_record()))
    for sentinel in PII_SENTINELS:
        assert sentinel not in rendered


def test_identity_ttl_is_valid_before_the_absolute_expiry() -> None:
    identity = make_identity(NOW)
    assert identity.is_valid_at(NOW)
    assert identity.is_valid_at(NOW + IDENTITY_TTL - timedelta(seconds=1))


def test_identity_ttl_expires_at_the_boundary_and_after() -> None:
    identity = make_identity(NOW)
    assert not identity.is_valid_at(NOW + IDENTITY_TTL)
    assert not identity.is_valid_at(NOW + IDENTITY_TTL + timedelta(seconds=1))


def test_identity_requires_handoff_after_three_caller_failures() -> None:
    assert not make_identity(failures=2).requires_handoff()
    assert make_identity(failures=3).requires_handoff()


def test_migration_never_turns_a_legacy_boolean_into_a_valid_authorization() -> None:
    record = session_record_from_document(make_v1_document(identity_validated=True))
    assert record.identity.validated_at is None
    assert record.identity.caller_failures == 0
    assert not record.identity_is_valid(NOW)
    assert not record.identity_is_valid(NOW + timedelta(minutes=1))


def test_migration_turns_a_legacy_action_into_at_most_a_goal() -> None:
    record = session_record_from_document(make_v1_document(requested_action="RESET_PASSWORD"))
    assert record.goal is not None
    assert record.goal.action is Action.RESET_PASSWORD
    assert record.goal.revision == 1
    assert record.confirmation is None
    assert record.dispatch is None


def test_migration_without_a_legacy_action_creates_no_goal() -> None:
    record = session_record_from_document(make_v1_document(requested_action=None))
    assert record.goal is None


def test_migration_preserves_only_the_truth_the_old_schema_recorded() -> None:
    record = session_record_from_document(make_v1_document())
    assert record.external_operation is not None
    assert record.external_operation.operation_id == "operation-1"
    assert record.external_operation.action is Action.UNLOCK_ACCOUNT
    assert record.external_operation.status is OperationStatus.PENDING
    assert record.external_operation.delivery is None
    assert record.dispatch is None
    assert record.confirmation is None


def test_migration_preserves_a_legacy_terminal_status_without_inferring_delivery() -> None:
    document = make_v1_document(
        pending_operation={
            "operation_id": "operation-1",
            "action": "RESET_PASSWORD",
            "status": "confirmed",
        }
    )
    record = session_record_from_document(document)
    assert record.external_operation is not None
    assert record.external_operation.status is OperationStatus.CONFIRMED
    assert record.external_operation.delivery is None
    assert record.dispatch is None


def test_migration_preserves_counters_and_timestamps() -> None:
    record = session_record_from_document(make_v1_document())
    assert record.conversation_id == "conversation-1"
    assert record.turn_count == 3
    assert record.revision == 3
    assert record.created_at == NOW
    assert record.updated_at == NOW + timedelta(minutes=2)


def test_migration_rejects_a_legacy_document_with_unwhitelisted_fields() -> None:
    with pytest.raises(ValidationError):
        session_record_from_document(make_v1_document(password="SYNTHETIC-PASSWORD-0000"))


def test_migration_rejects_an_unknown_legacy_status() -> None:
    document = make_v1_document(
        pending_operation={
            "operation_id": "operation-1",
            "action": "UNLOCK_ACCOUNT",
            "status": "invented",
        }
    )
    with pytest.raises(ValidationError):
        session_record_from_document(document)


def test_identity_state_never_holds_raw_identity_values() -> None:
    with pytest.raises(ValidationError):
        IdentityState(validated_at="SYNTHETIC-DOC-0000")
