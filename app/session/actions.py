"""Account actions authorized for the first slice.

Kept in its own module so the experimental memory plane
(`app.session.memory`) and the durable contract (`app.session.record`) can
share it without an import cycle.
"""

from enum import StrEnum


class Action(StrEnum):
    """Account actions authorized for the first slice."""

    RESET_PASSWORD = "RESET_PASSWORD"
    UNLOCK_ACCOUNT = "UNLOCK_ACCOUNT"
