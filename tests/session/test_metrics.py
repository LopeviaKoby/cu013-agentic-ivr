"""Metrics seam tests: PII-safe recording and structured logging."""

import logging
import subprocess
import sys

from app.session.metrics import RecordingTurnMetrics, StructuredLogTurnMetrics, logger


def test_recording_metrics_capture_and_drain() -> None:
    metrics = RecordingTurnMetrics()
    metrics.record_segment("model", 1.5)
    metrics.record_counter("prompt_tokens", 12)
    assert metrics.drain_segments() == [("model", 1.5)]
    assert metrics.drain_counters() == [("prompt_tokens", 12)]
    assert metrics.segments == []
    assert metrics.counters == []


def test_structured_log_metrics_emit_only_fixed_fields(caplog) -> None:
    metrics = StructuredLogTurnMetrics()
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="cu013.metrics"):
            metrics.record_segment("session_load", 123.456)
            metrics.record_counter("total_tokens", 7)
    finally:
        logger.removeHandler(caplog.handler)
    text = caplog.text
    assert "turn_metric segment=session_load duration_ms=123.456" in text
    assert "turn_metric counter=total_tokens value=7" in text
    assert "transcript" not in text


def test_structured_metrics_reach_uvicorn_process_output() -> None:
    program = """
import logging.config
from uvicorn.config import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)
from app.session.metrics import StructuredLogTurnMetrics

metrics = StructuredLogTurnMetrics()
metrics.record_segment("model", 123.456)
metrics.record_counter("total_tokens", 7)
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert "turn_metric segment=model duration_ms=123.456" in output
    assert "turn_metric counter=total_tokens value=7" in output
