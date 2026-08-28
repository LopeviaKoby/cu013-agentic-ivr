import json
import logging
import re
import sys
from typing import Any

# Patterns that might contain sensitive PII
_SENSITIVE_PATTERNS = [
    re.compile(r"\b\d{8,12}\b"),  # Document/ID numbers
    re.compile(r"(?i)(password|contrase[nñ]a|token|secret|pin|otp)\s*[:=]\s*\S+"),
]


def redact_pii(text: str) -> str:
    """Redact potentially sensitive patterns from text before logging."""
    redacted = text
    for pattern in _SENSITIVE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class JSONFormatter(logging.Formatter):
    """Format logs as JSON objects suitable for Google Cloud Logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Include structured extra attributes if present
        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
            ):
                if isinstance(value, str):
                    log_entry[key] = redact_pii(value)
                else:
                    log_entry[key] = value

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure root logger with structured JSON formatting."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to prevent duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)

    return logging.getLogger("cu013")


logger = logging.getLogger("cu013")
