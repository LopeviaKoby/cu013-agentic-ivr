"""Deterministic tests for the Exp 0009 burst preparation; no cloud, no Vertex."""

import json

from evals.conversation_burst import (
    BURST_IDS,
    DETERMINISTIC_MODEL_DELAY_S,
    DeterministicBurstModel,
    estimate_all,
    estimate_phase,
    manifest,
)
from evals.conversation_burst import main as burst_main


def test_burst_uses_eight_distinct_ids() -> None:
    from evals.conversation_burst import burst_conversation_ids

    ids = burst_conversation_ids("exp0009-burst")
    assert len(ids) == BURST_IDS == 8
    assert len(set(ids)) == 8


def test_estimate_phase_counts_requests_reads_writes() -> None:
    phase = estimate_phase(bursts=30, arms=3, vertex_calls=False)
    assert phase["requests"] == 30 * 8 * 3 + 8 * 3
    assert phase["firestore_reads"] == phase["requests"]
    assert phase["firestore_writes"] == phase["requests"]
    assert phase["vertex_input_tokens"] == 0
    assert phase["cost_usd"] > 0


def test_full_estimate_stays_within_the_stop_line() -> None:
    estimate = estimate_all()
    assert estimate["within_stop_line"] is True
    assert estimate["total_usd"] <= 2.50
    assert estimate["stop_line_usd"] == 2.50
    assert estimate["budget_usd"] == 3.00
    assert estimate["cleanup"]["deletes"] == 8 * (3 + 2 + 1)


async def test_deterministic_seam_returns_a_fixed_safe_result() -> None:
    model = DeterministicBurstModel(delay_s=0.0)
    decision = await model.decide(transcript="anything", goal=None)
    assert decision.route.value == "CONTINUE"
    assert decision.message
    assert len(model.calls) == 1
    assert DETERMINISTIC_MODEL_DELAY_S == 0.6


async def test_local_barrier_releases_eight_without_errors() -> None:
    from evals.conversation_burst import run_local_burst
    from tests.session.doubles import InMemorySessionDocumentStore

    result = await run_local_burst(
        InMemorySessionDocumentStore, prefix="exp0009-selfcheck", delay_s=0.0
    )
    assert len(result.conversation_ids) == 8
    assert result.errors == 0
    assert sorted(set(result.statuses)) == [200]
    assert len(result.walls_ms) == 8


def test_manifest_lists_only_synthetic_ids() -> None:
    data = manifest("exp0009-burst", rounds=2)
    assert len(data["conversation_ids"]) == 16
    assert all("exp0009-burst" in value for value in data["conversation_ids"])
    assert data["collection"] == "cu013dev_sessions"
    json.dumps(data)


def test_live_execution_is_refused_without_authorization() -> None:
    assert burst_main(["--url", "https://example.run.app"]) == 3
    assert burst_main(["--execute-live", "--url", "https://example.run.app"]) == 3
