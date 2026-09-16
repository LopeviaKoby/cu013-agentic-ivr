"""Metrics seam tests: PII-safe recording and structured logging."""

import logging

from app.session.metrics import RecordingTurnMetrics, StructuredLogTurnMetrics


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
    with caplog.at_level(logging.INFO, logger="cu013.metrics"):
        metrics.record_segment("session_load", 123.456)
        metrics.record_counter("total_tokens", 7)
    text = caplog.text
    assert "turn_metric segment=session_load duration_ms=123.456" in text
    assert "turn_metric counter=total_tokens value=7" in text
    assert "transcript" not in text
