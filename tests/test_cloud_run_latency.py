"""Deterministic reporting tests for the Cloud Run HTTPS benchmark client."""

from evals.cloud_run_latency import summarize


def test_summary_keeps_the_first_measured_request_in_temporal_order() -> None:
    results: list[dict[str, object]] = [
        {"status": 200, "round_trip_ms": 300.0, "error": False},
        {"status": 200, "round_trip_ms": 100.0, "error": False},
        {"status": 200, "round_trip_ms": 200.0, "error": False},
    ]

    summary = summarize(results)

    assert summary.first_ms == 300.0
    assert summary.min_ms == 100.0
    assert summary.p50_ms == 200.0
