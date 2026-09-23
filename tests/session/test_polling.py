"""Deterministic polling sequence, dedupe and observation-budget tests.

No model, network, Firestore or credentials are involved. Fingerprints hash
only the closed observation kind, so no raw external literal can be persisted.
"""

from app.session.polling import (
    ObservationKind,
    SequenceDecision,
    append_receipt,
    classify_sequence,
    new_polling_state,
    observation_fingerprint,
)
from tests.session.doubles import NOW


def _polling(limit: int = 9):  # type: ignore[no-untyped-def]
    return new_polling_state("operation-1", now=NOW, observation_limit=limit)


def test_fingerprint_is_a_sha256_of_the_closed_kind_only() -> None:
    fingerprint = observation_fingerprint(ObservationKind.PENDING)
    assert len(fingerprint) == 64
    assert set(fingerprint) <= set("0123456789abcdef")
    assert fingerprint == observation_fingerprint(ObservationKind.PENDING)
    assert fingerprint != observation_fingerprint(ObservationKind.UNRECOGNIZED)


def test_unknown_status_literal_can_never_reach_the_fingerprint() -> None:
    fingerprint = observation_fingerprint(ObservationKind.UNRECOGNIZED)
    for canary in ("STATUS_NUEVO_RD", "CPF_NAO_ENCONTRADO", "SYNTHETIC-DOC-0000"):
        assert canary not in fingerprint


def test_error_fingerprint_carries_only_closed_technical_fields() -> None:
    first = observation_fingerprint(
        ObservationKind.ERROR, phase="POLL", error_kind="TIMEOUT", http_status=504
    )
    second = observation_fingerprint(
        ObservationKind.ERROR, phase="POLL", error_kind="TIMEOUT", http_status=504
    )
    third = observation_fingerprint(
        ObservationKind.ERROR, phase="POLL", error_kind="HTTP_ERROR", http_status=500
    )
    assert first == second
    assert first != third


def test_first_observation_must_be_sequence_one() -> None:
    polling = _polling()
    fingerprint = observation_fingerprint(ObservationKind.PENDING)
    assert classify_sequence(polling, sequence=2, fingerprint=fingerprint) is (
        SequenceDecision.CONFLICT
    )
    assert classify_sequence(polling, sequence=1, fingerprint=fingerprint) is (SequenceDecision.NEW)


def test_new_observations_advance_exactly_one_sequence() -> None:
    fingerprint = observation_fingerprint(ObservationKind.PENDING)
    polling = append_receipt(_polling(), sequence=1, fingerprint=fingerprint)
    assert classify_sequence(polling, sequence=2, fingerprint=fingerprint) is (SequenceDecision.NEW)
    assert classify_sequence(polling, sequence=4, fingerprint=fingerprint) is (
        SequenceDecision.CONFLICT
    )


def test_replay_requires_the_same_fingerprint() -> None:
    pending = observation_fingerprint(ObservationKind.PENDING)
    unrecognized = observation_fingerprint(ObservationKind.UNRECOGNIZED)
    polling = append_receipt(_polling(), sequence=1, fingerprint=pending)
    assert classify_sequence(polling, sequence=1, fingerprint=pending) is (SequenceDecision.REPLAY)
    assert classify_sequence(polling, sequence=1, fingerprint=unrecognized) is (
        SequenceDecision.CONFLICT
    )


def test_a_missing_older_sequence_is_a_conflict() -> None:
    fingerprint = observation_fingerprint(ObservationKind.PENDING)
    polling = append_receipt(_polling(), sequence=2, fingerprint=fingerprint)
    assert classify_sequence(polling, sequence=1, fingerprint=fingerprint) is (
        SequenceDecision.CONFLICT
    )


def test_receipts_never_count_a_replay_as_budget() -> None:
    fingerprint = observation_fingerprint(ObservationKind.PENDING)
    polling = _polling(limit=2)
    assert polling.observations_used == 0
    assert not polling.budget_exhausted()
    polling = append_receipt(polling, sequence=1, fingerprint=fingerprint)
    assert polling.observations_used == 1
    assert not polling.budget_exhausted()
    polling = append_receipt(polling, sequence=2, fingerprint=fingerprint)
    assert polling.observations_used == 2
    assert polling.budget_exhausted()
