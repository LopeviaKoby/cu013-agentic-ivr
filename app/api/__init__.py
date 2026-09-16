"""HTTP boundary consumed by Cally Square.

Contract models, API-key authentication, error translation and the
application factory. See `docs/specs/xcally-boundary.md`.
"""

from app.api.app import create_app

__all__ = ["create_app"]
