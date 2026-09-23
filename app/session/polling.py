"""Deterministic polling sequence, dedupe and observation budget.

The runtime owns the poll budget; XCALLY initiates each GET and reports one
observation with a strictly increasing ``poll_sequence``. Fingerprints hash
only the closed observation kind (plus the technical error fields), never the
raw external literal, so an unknown RD status can be deduplicated without
ever reaching durable state.
"""

import hashlib
import json
from datetime import datetime
from enum import StrEnum

from app.session.record import (
    DEFAULT_OBSERVATION_LIMIT,
    PollingState,
    PollReceipt,
)

__all__ = [
    "ObservationKind",
    "SequenceDecision",
    "append_receipt",
    "classify_sequence",
    "new_polling_state",
    "observation_fingerprint",
]


class ObservationKind(StrEnum):
    """Closed observation kinds; the raw external literal is never one."""

    PENDING = "PENDING"
    UNRECOGNIZED = "UNRECOGNIZED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ERROR = "ERROR"

    def is_terminal(self) -> bool:
        """A terminal observation ends the operation."""
        return self in {ObservationKind.SUCCEEDED, ObservationKind.FAILED}


class SequenceDecision(StrEnum):
    """How one reported sequence relates to the durable receipts."""

    NEW = "NEW"
    REPLAY = "REPLAY"
    CONFLICT = "CONFLICT"


def new_polling_state(
    operation_id: str,
    *,
    now: datetime,
    observation_limit: int = DEFAULT_OBSERVATION_LIMIT,
) -> PollingState:
    """Open the polling plane for one operation; nothing is consumed yet."""
    return PollingState(
        operation_id=operation_id,
        started_at=now,
        observation_limit=observation_limit,
    )


def observation_fingerprint(
    kind: ObservationKind,
    *,
    phase: str | None = None,
    error_kind: str | None = None,
    http_status: int | None = None,
) -> str:
    """SHA-256 of the closed observation; the raw external value never enters."""
    payload: dict[str, object] = {"kind": kind.value}
    if phase is not None:
        payload["phase"] = phase
    if error_kind is not None:
        payload["error_kind"] = error_kind
    if http_status is not None:
        payload["http_status"] = http_status
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def classify_sequence(
    polling: PollingState, *, sequence: int, fingerprint: str
) -> SequenceDecision:
    """Classify one sequence: new, exact replay or safe conflict.

    The first observation must be sequence 1 and every new observation must be
    exactly the last plus one; anything else is a conflict. A repeated
    sequence is a replay only when its fingerprint matches the stored receipt.
    """
    receipts = polling.receipts
    if not receipts:
        return SequenceDecision.NEW if sequence == 1 else SequenceDecision.CONFLICT
    last = receipts[-1].sequence
    if sequence == last + 1:
        return SequenceDecision.NEW
    if sequence > last + 1:
        return SequenceDecision.CONFLICT
    for receipt in receipts:
        if receipt.sequence == sequence:
            if receipt.fingerprint == fingerprint:
                return SequenceDecision.REPLAY
            return SequenceDecision.CONFLICT
    return SequenceDecision.CONFLICT


def append_receipt(polling: PollingState, *, sequence: int, fingerprint: str) -> PollingState:
    """Consume one observation; only new, non-replay observations call this."""
    receipt = PollReceipt(sequence=sequence, fingerprint=fingerprint)
    return polling.model_copy(update={"receipts": (*polling.receipts, receipt)})
