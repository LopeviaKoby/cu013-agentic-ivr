"""Next-step-v1 HTTP contract: one common envelope for both endpoints.

The selector is explicit and never heuristic: without the canonical
``X-CU013-Response-Contract`` header the legacy contract stays
byte-compatible, the exact ``next-step-v1`` value selects the new envelope,
and an empty, repeated or unknown version is rejected with 400 before any
handler runs. Authentication always precedes the selector. The header name
without the ``X-`` prefix is not read and is not kept as an alias: it had no
accredited real consumer.

The runtime decides ``next_step``; the model cannot. ``command`` exists if and
only if ``next_step`` is ``EXECUTE_ACTION``.
"""

from collections.abc import Sequence
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.api.errors import UnsupportedResponseContractError
from app.session.integration import IntegrationOperationState
from app.session.outcome import NextStep
from app.session.text import normalize_message
from app.session.turns import ExternalActionCommand

RESPONSE_CONTRACT_HEADER = "X-CU013-Response-Contract"
NEXT_STEP_CONTRACT = "next-step-v1"

__all__ = [
    "NEXT_STEP_CONTRACT",
    "RESPONSE_CONTRACT_HEADER",
    "NextStepResponse",
    "ResponseContract",
    "next_step_response",
    "select_response_contract",
]


class ResponseContract(StrEnum):
    """Which response envelope the caller asked for."""

    LEGACY = "legacy"
    NEXT_STEP_V1 = "next-step-v1"


def select_response_contract(values: Sequence[str]) -> ResponseContract:
    """Select the envelope from the header values, failing closed.

    ``values`` is the complete repeated-header list: more than one value is an
    ambiguous request and never resolves to a contract by position.
    """
    if len(values) == 0:
        return ResponseContract.LEGACY
    if len(values) > 1:
        raise UnsupportedResponseContractError()
    if values[0] != NEXT_STEP_CONTRACT:
        raise UnsupportedResponseContractError()
    return ResponseContract.NEXT_STEP_V1


class NextStepResponse(BaseModel):
    """The common next-step-v1 envelope returned by both endpoints.

    All four keys are always present; ``message`` is null when nothing should
    be spoken and ``operation_state`` is null when no external operation is
    involved.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str | None = None
    next_step: NextStep
    operation_state: IntegrationOperationState | None = None
    command: ExternalActionCommand | None = None

    @model_validator(mode="after")
    def _command_only_with_execute_action(self) -> Self:
        if self.command is not None and self.next_step is not NextStep.EXECUTE_ACTION:
            raise ValueError("command is only valid with EXECUTE_ACTION")
        if self.next_step is NextStep.EXECUTE_ACTION and self.command is None:
            raise ValueError("EXECUTE_ACTION requires a command")
        return self


def next_step_response(
    *,
    message: str | None,
    next_step: NextStep,
    operation_state: IntegrationOperationState | None = None,
    command: ExternalActionCommand | None = None,
) -> NextStepResponse:
    """Build one validated envelope; message normalization happens here."""
    normalized = normalize_message(message)
    return NextStepResponse(
        message=normalized if normalized else None,
        next_step=next_step,
        operation_state=operation_state,
        command=command,
    )
