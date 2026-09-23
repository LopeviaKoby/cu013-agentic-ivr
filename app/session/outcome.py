"""Canonical runtime outcome vocabulary shared by the two temporary adapters.

The runtime decides the next step; the conversational model never does. The
same domain transition feeds the legacy serializer and the next-step-v1
serializer, so ``NextStep`` is the single canonical projection. The legacy
``BoundaryRoute`` and ``IntegrationDirective`` vocabularies stay confined to
the legacy adapter and are derived from ``NextStep`` here, once.
"""

from enum import StrEnum

__all__ = [
    "LEGACY_ROUTE_BY_NEXT_STEP",
    "NextStep",
    "legacy_route_value",
]


class NextStep(StrEnum):
    """What the runtime asks XCALLY to do after one turn or one event."""

    LISTEN = "LISTEN"
    COLLECT_IDENTITY = "COLLECT_IDENTITY"
    EXECUTE_ACTION = "EXECUTE_ACTION"
    POLL_RD = "POLL_RD"
    DELIVER_PASSWORD = "DELIVER_PASSWORD"
    TRANSFER = "TRANSFER"
    COMPLETE = "COMPLETE"


LEGACY_ROUTE_BY_NEXT_STEP: dict[NextStep, str] = {
    NextStep.LISTEN: "CONTINUE",
    NextStep.COLLECT_IDENTITY: "COLLECT_IDENTITY",
    NextStep.EXECUTE_ACTION: "EXECUTE_ACTION",
    NextStep.COMPLETE: "COMPLETE",
    NextStep.TRANSFER: "ESCALATE",
}


def legacy_route_value(next_step: NextStep) -> str:
    """Project one domain step onto the legacy ``route`` vocabulary.

    ``POLL_RD`` and ``DELIVER_PASSWORD`` never occur on the conversational
    lane; a caller that reaches them is a programming error, not a wire case.
    """
    return LEGACY_ROUTE_BY_NEXT_STEP[next_step]
