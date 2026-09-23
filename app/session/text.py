"""Whitespace normalization for next-step-v1 messages.

Only CR, LF, tab and runs of spaces are normalized: a message that reaches the
wire never carries control whitespace. Unicode letters, apostrophes, ASCII
quotes and backslashes are preserved byte-for-byte. The function is never
applied to passwords, documents or dates: those values never enter the
backend.
"""

import re

__all__ = ["normalize_message"]

_WHITESPACE = re.compile(r"[ \t\r\n]+")


def normalize_message(value: str | None) -> str | None:
    """Collapse control whitespace; ``None`` stays ``None``."""
    if value is None:
        return None
    return _WHITESPACE.sub(" ", value).strip(" ")
