"""Lightweight PII-safe turn instrumentation; no observability platform.

Segments are monotonic durations with fixed names and counters carry only
token counts. No transcript, DTMF, generated text or any payload data may
ever be recorded here.
"""

from typing import Protocol


class TurnMetrics(Protocol):
    """Optional timing and counter seam for benchmarks and future telemetry."""

    def record_segment(self, name: str, duration_ms: float) -> None: ...

    def record_counter(self, name: str, value: int) -> None: ...


class NullTurnMetrics:
    """No-op metrics for normal operation without instrumentation."""

    def record_segment(self, name: str, duration_ms: float) -> None: ...

    def record_counter(self, name: str, value: int) -> None: ...


class RecordingTurnMetrics:
    """In-memory capture for deterministic tests and the DEV benchmark."""

    def __init__(self) -> None:
        self.segments: list[tuple[str, float]] = []
        self.counters: list[tuple[str, int]] = []

    def record_segment(self, name: str, duration_ms: float) -> None:
        self.segments.append((name, duration_ms))

    def record_counter(self, name: str, value: int) -> None:
        self.counters.append((name, value))

    def drain_segments(self) -> list[tuple[str, float]]:
        segments, self.segments = self.segments, []
        return segments

    def drain_counters(self) -> list[tuple[str, int]]:
        counters, self.counters = self.counters, []
        return counters
