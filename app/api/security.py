"""API-key authentication for the XCALLY boundary.

The expected key lives only in the process environment (local `.env`
injection or cloud secret injection). It is never read from `config.yaml`,
never logged, and compared in constant time.
"""

import os
import secrets
from typing import Annotated

from fastapi import Header

from app.api.errors import ApiKeyNotConfiguredError, AuthenticationError

API_KEY_ENV_VAR = "CU013_API_KEY"


def _expected_api_key() -> str | None:
    value = os.environ.get(API_KEY_ENV_VAR, "")
    return value or None


async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Reject unauthenticated callers without revealing which check failed."""
    expected = _expected_api_key()
    if expected is None:
        raise ApiKeyNotConfiguredError()
    provided = x_api_key if x_api_key is not None else ""
    if not secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise AuthenticationError()
