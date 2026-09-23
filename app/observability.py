"""Shared PII-safe logging topology and validation-fact projection.

One parent namespace (``cu013``), one stderr handler, INFO level and no
propagation to the root logger, so the application never depends on Uvicorn's
logging configuration and never duplicates lines. Only closed event names and
closed field values may be emitted: conversation ids, turn ids, operation ids,
trace/request ids, payloads, transcripts, headers and exception messages never
reach a log line.
"""

import logging
import sys

__all__ = [
    "APP_LOGGER_NAME",
    "LOGGER_NAME",
    "METRICS_LOGGER_NAME",
    "configure_logging",
    "format_validation_facts",
    "validation_facts",
]

LOGGER_NAME = "cu013"
APP_LOGGER_NAME = "cu013.app"
METRICS_LOGGER_NAME = "cu013.metrics"

_LOG_FORMAT = "%(levelname)s %(message)s"
_SHARED_HANDLER_ATTR = "_cu013_shared_handler"


def configure_logging() -> None:
    """Configure the shared namespace once; idempotent and test-safe.

    The marker attribute identifies the handler this module owns, so a handler
    attached by a test (for example a capture handler) can never suppress the
    production one nor be counted as it.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if any(getattr(handler, _SHARED_HANDLER_ATTR, False) for handler in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    setattr(handler, _SHARED_HANDLER_ATTR, True)
    logger.addHandler(handler)


def validation_facts(exc: Exception) -> tuple[tuple[str, str], ...]:
    """Project a validation error to closed (location, type) pairs only.

    Never returns input values, messages, contexts or URLs: the offending
    payload must not be able to reach a log line.
    """
    facts: list[tuple[str, str]] = []
    for error in _safe_errors(exc):
        raw_location = error.get("loc", ())
        parts = raw_location if isinstance(raw_location, (list, tuple)) else ()
        location = ".".join(str(part) for part in parts) if parts else "body"
        facts.append((location, str(error.get("type", "unknown"))))
    if not facts:
        facts.append(("body", "unknown"))
    return tuple(facts)


def format_validation_facts(facts: tuple[tuple[str, str], ...]) -> str:
    """Render facts as a compact, closed, PII-safe string for one log line."""
    return "|".join(f"{location}:{kind}" for location, kind in facts)


def _safe_errors(exc: Exception) -> list[dict[str, object]]:
    errors_method = getattr(exc, "errors", None)
    if not callable(errors_method):
        return []
    try:
        raw = errors_method(include_input=False, include_context=False, include_url=False)
    except TypeError:
        try:
            raw = errors_method()
        except Exception:
            return []
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return [error for error in raw if isinstance(error, dict)]
