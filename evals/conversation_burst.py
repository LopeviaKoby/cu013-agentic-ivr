"""Exp 0009 eight-session burst preparation (NOT executed against Cloud Run).

This module prepares the Phase A/B/C capacity benchmark from Experiment
0009 without running it: a barrier client for eight distinct synthetic
conversation ids, a deterministic async model seam, a cost estimator with a
stop-line check, a synthetic-document manifest writer, and the exact
proposed commands (printed, never executed here).

What each entrypoint does:

- ``--self-check``: validates the barrier + seam mechanics locally against
  an in-memory TurnService (no network, no cloud, no Vertex, no Firestore).
- ``--estimate-only``: prints resource quantities and the cost estimate per
  phase from explicit rate inputs, then checks the US$2.50 stop-line inside
  the US$3/month experiment budget.
- ``--print-plan``: prints the proposed (not executed) gcloud/deploy
  commands, Monitoring queries and rollback steps for owner authorization.
- ``--manifest-only``: writes the synthetic conversation-id manifest for
  later authorized cleanup (Git-ignored results dir).

Running the live benchmark additionally requires ``--execute-live --url
<tagged-revision-url>`` plus a separately authorized window; without that
flag any live URL is refused. Live execution also needs
``CU013_BURST_API_KEY`` in the environment (never a committed value).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.session.metrics import RecordingTurnMetrics
from app.session.record import SessionRecord
from app.session.repository import SessionRepository
from app.session.service import TurnService
from app.session.turns import (
    ModelTurnDecision,
    Route,
    TurnInput,
    build_turn_graph,
)

# ---------------------------------------------------------------------------
# Experiment constants (Experiment 0009, Phase A first)
# ---------------------------------------------------------------------------

BURST_IDS = 8
PHASE_A_BURSTS_PER_ARM = 30
PHASE_A_ARMS = ("no-memory", "procedure-only", "recent-memory")
PHASE_B_BURSTS_PER_ARM = 20
PHASE_B_ARMS = ("no-memory", "recent-memory")
PHASE_C_BURSTS = 5
PRIME_REQUESTS_PER_ARM = 8
DETERMINISTIC_MODEL_DELAY_S = 0.6
PHASE_A_CPU = 1
PHASE_A_MEMORY_GIB = 0.5
STOP_LINE_USD = 2.50
BUDGET_USD = 3.00

# Rates retrieved 2026-09-18; the owner reconfirms them at authorization.
# Cloud Run request-based Tier 1 (us-east1):
#   https://cloud.google.com/run/pricing
# Firestore Standard Native: https://cloud.google.com/firestore/pricing
# Vertex: https://ai.google.dev/gemini-api/docs/pricing
DEFAULT_RATES = {
    "run_vcpu_per_s": 0.000024,
    "run_gib_per_s": 0.0000025,
    "run_idle_per_s": 0.0000025,
    "run_per_million_requests": 0.40,
    "firestore_per_100k_reads": 0.03,
    "firestore_per_100k_writes": 0.09,
    "firestore_per_100k_deletes": 0.01,
    "vertex_per_million_input_tokens": 0.10,
    "vertex_per_million_output_tokens": 0.40,
}

# Representative per-turn figures for the estimate. Handler wall comes from
# Experiment 0004 (p50 handler 657 ms) plus the 600 ms deterministic seam the
# plan declares; tokens come from the local paired memory runs.
ESTIMATE_HANDLER_WALL_S = 1.3
ESTIMATE_PROMPT_TOKENS = 1650
ESTIMATE_COMPLETION_TOKENS = 100


class DeterministicBurstModel:
    """Phase A seam: same render path, fixed delay, fixed safe result.

    The graph still renders the prompt/memory block and validates the
    decision through advance_turn; the seam itself awaits a declared delay
    and returns a fixed CONTINUE decision. No Vertex, no AD, no side effect.
    """

    def __init__(self, *, delay_s: float = DETERMINISTIC_MODEL_DELAY_S) -> None:
        self.delay_s = delay_s
        self.calls: list[dict] = []

    async def decide(self, **kwargs: Any) -> ModelTurnDecision:
        self.calls.append(dict(kwargs))
        await asyncio.sleep(self.delay_s)
        return ModelTurnDecision(
            message="continúa, por favor",
            route=Route.CONTINUE,
        )


def burst_conversation_ids(prefix: str) -> list[str]:
    """Eight distinct synthetic ids for one burst round."""
    return [f"{prefix}-{index}" for index in range(BURST_IDS)]


def estimate_phase(
    *,
    bursts: int,
    arms: int,
    vertex_calls: bool,
    prompt_tokens: int = ESTIMATE_PROMPT_TOKENS,
    completion_tokens: int = ESTIMATE_COMPLETION_TOKENS,
    wall_s: float = ESTIMATE_HANDLER_WALL_S,
    rates: dict | None = None,
) -> dict:
    """Resource quantities and cost for one benchmark phase (pure)."""
    rates = rates or dict(DEFAULT_RATES)
    requests = bursts * BURST_IDS * arms + PRIME_REQUESTS_PER_ARM * arms
    active_vcpu_s = requests * wall_s * PHASE_A_CPU
    active_gib_s = requests * wall_s * PHASE_A_MEMORY_GIB
    reads = requests  # one load per turn
    writes = requests  # one save per turn
    input_tokens = requests * prompt_tokens if vertex_calls else 0
    output_tokens = requests * completion_tokens if vertex_calls else 0
    cost = (
        active_vcpu_s * rates["run_vcpu_per_s"]
        + active_gib_s * rates["run_gib_per_s"]
        + requests / 1_000_000 * rates["run_per_million_requests"]
        + reads / 100_000 * rates["firestore_per_100k_reads"]
        + writes / 100_000 * rates["firestore_per_100k_writes"]
        + input_tokens / 1_000_000 * rates["vertex_per_million_input_tokens"]
        + output_tokens / 1_000_000 * rates["vertex_per_million_output_tokens"]
    )
    return {
        "requests": requests,
        "active_vcpu_s": round(active_vcpu_s, 1),
        "active_gib_s": round(active_gib_s, 1),
        "firestore_reads": reads,
        "firestore_writes": writes,
        "vertex_input_tokens": input_tokens,
        "vertex_output_tokens": output_tokens,
        "cost_usd": round(cost, 4),
    }


def estimate_all(rates: dict | None = None) -> dict:
    """Phase A (seam) + B (provider) + C (cold) + cleanup writes."""
    phase_a = estimate_phase(
        bursts=PHASE_A_BURSTS_PER_ARM,
        arms=len(PHASE_A_ARMS),
        vertex_calls=False,
        rates=rates,
    )
    phase_b = estimate_phase(
        bursts=PHASE_B_BURSTS_PER_ARM,
        arms=len(PHASE_B_ARMS),
        vertex_calls=True,
        rates=rates,
    )
    phase_c = estimate_phase(bursts=PHASE_C_BURSTS, arms=1, vertex_calls=True, rates=rates)
    # Authorized cleanup deletes every synthetic session document once:
    # Phase A uses 3 arms x 8 ids, Phase B 2 x 8, Phase C 8.
    cleanup_deletes = BURST_IDS * (len(PHASE_A_ARMS) + len(PHASE_B_ARMS) + 1)
    cleanup_cost = (
        cleanup_deletes / 100_000 * (rates or DEFAULT_RATES)["firestore_per_100k_deletes"]
    )
    total = phase_a["cost_usd"] + phase_b["cost_usd"] + phase_c["cost_usd"] + cleanup_cost
    return {
        "phase_a_backend_isolation": phase_a,
        "phase_b_provider_included": phase_b,
        "phase_c_cold_burst": phase_c,
        "cleanup": {"deletes": cleanup_deletes, "cost_usd": round(cleanup_cost, 4)},
        "total_usd": round(total, 4),
        "stop_line_usd": STOP_LINE_USD,
        "budget_usd": BUDGET_USD,
        "within_stop_line": total <= STOP_LINE_USD,
        "rate_sources": [
            "https://cloud.google.com/run/pricing",
            "https://cloud.google.com/firestore/pricing",
            "https://ai.google.dev/gemini-api/docs/pricing",
        ],
        "rates_retrieved": "2026-09-18; reconfirm at authorization",
        "notes": "Gross estimate: free-tier quotas assumed exhausted. "
        "Phase A uses the deterministic seam (no Vertex tokens). "
        "min=0 except authorized warm priming; no min=1 billable revision kept.",
    }


@dataclass
class BurstResult:
    """Client-side evidence for one burst; no transcripts, no messages."""

    burst_id: int
    conversation_ids: list[str]
    release_skew_ms: float
    walls_ms: list[float] = field(default_factory=list)
    statuses: list[int] = field(default_factory=list)
    errors: int = 0


async def run_local_burst(
    store_factory: Callable[[], object],
    *,
    prefix: str,
    burst_id: int = 0,
    experimental=None,
    delay_s: float = 0.01,
) -> BurstResult:
    """Barrier release of eight turns over local services (self-check only).

    Each id gets its own repository view over one shared store plus a fresh
    service per id, mirroring eight coincident callers without any cloud.
    """

    ids = burst_conversation_ids(prefix)
    barrier = asyncio.Barrier(BURST_IDS)
    release_at: list[float] = []
    walls: list[float] = []
    statuses: list[int] = []

    async def _one(conversation_id: str) -> None:
        store = store_factory()
        repository = SessionRepository(store)
        seed = SessionRecord.new(conversation_id, now=datetime.now(UTC))
        await repository.save(seed)
        model = DeterministicBurstModel(delay_s=delay_s)
        service = TurnService(
            repository, build_turn_graph(model=model), metrics=RecordingTurnMetrics()
        )
        await barrier.wait()
        if not release_at:
            release_at.append(time.monotonic())
        start = time.monotonic()
        try:
            await service.handle_turn(
                conversation_id,
                TurnInput(transcript="turno sintético de ráfaga"),
                experimental=experimental,
            )
            statuses.append(200)
        except Exception:
            statuses.append(500)
        walls.append((time.monotonic() - start) * 1000.0)

    await asyncio.gather(*(_one(conversation_id) for conversation_id in ids))
    skew = (max(walls) - min(walls)) if walls else 0.0
    return BurstResult(
        burst_id=burst_id,
        conversation_ids=ids,
        release_skew_ms=round(skew, 3),
        walls_ms=[round(value, 3) for value in walls],
        statuses=statuses,
        errors=sum(1 for status in statuses if status != 200),
    )


def manifest(prefix: str, rounds: int) -> dict:
    """Synthetic id manifest for later authorized Firestore cleanup."""
    ids = []
    for round_index in range(rounds):
        ids.extend(burst_conversation_ids(f"{prefix}-r{round_index}"))
    return {
        "prefix": prefix,
        "collection": "cu013dev_sessions",
        "conversation_ids": sorted(set(ids)),
        "cleanup": "delete only these documents, one by one, under cleanup authorization",
    }


def print_plan() -> None:
    """Proposed (never executed here) benchmark commands and queries."""
    print("=== Exp 0009 burst plan (PROPOSED ONLY - not executed) ===")
    print("Pre-state (read-only, capture full spec.traffic first):")
    print("  powershell -File ops/gcp/collect-burst-prestate.ps1 -Service cu013-runtime-dev")
    print("Phase A image per arm, then one tagged 0%-traffic revision:")
    print(
        "  gcloud run deploy cu013-runtime-dev --image IMAGE --no-traffic --tag exp0009-a "
        "--cpu 1 --memory 512Mi --concurrency 8 --max-instances 1 --min-instances 0 "
        "--region us-east1"
    )
    print("Conditional fallbacks only on measured contention/latency failure:")
    print("  concurrency=4/max_instances=2, then concurrency=2/max_instances=4")
    print("Client (after separate authorization, with key in env only):")
    print(
        "  python evals/conversation_burst.py --execute-live "
        "--url https://cu013-runtime-dev---exp0009-a-xxx.us-east1.run.app "
        "--arm recent-memory"
    )
    print("Monitoring (tagged revision + UTC window labels):")
    for metric in (
        "run.googleapis.com/container/cpu/utilizations",
        "run.googleapis.com/container/memory/utilizations",
        "run.googleapis.com/container/max_request_concurrencies",
        "run.googleapis.com/container/instance_count",
        "run.googleapis.com/container/startup_latencies",
        "run.googleapis.com/request_latencies",
        "run.googleapis.com/request_count",
    ):
        print(f"  {metric}")
    print("Rollback (exact pre-state semantics incl. latestRevision vs revisionName):")
    print("  gcloud run services update-traffic cu013-runtime-dev --remove-tags exp0009-a")
    print("  gcloud run revisions delete <benchmark-revision>  # only listed 0%-traffic revisions")
    print("  verify spec.traffic + effective traffic + min_instances=0 against pre-state capture")
    print("Cost: see --estimate-only (stop-line US$2.50 within US$3/month).")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exp 0009 burst preparation (no live run)")
    parser.add_argument("--self-check", action="store_true", help="local barrier mechanics check")
    parser.add_argument("--estimate-only", action="store_true", help="print the cost estimate")
    parser.add_argument("--print-plan", action="store_true", help="print proposed commands")
    parser.add_argument("--manifest-only", action="store_true", help="write the id manifest")
    parser.add_argument("--prefix", default="exp0009-burst")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "evals" / "results")
    parser.add_argument("--execute-live", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--url", default=None, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


async def _self_check(prefix: str) -> int:
    from tests.session.doubles import InMemorySessionDocumentStore

    result = await run_local_burst(InMemorySessionDocumentStore, prefix=prefix)
    print(f"burst_id={result.burst_id} ids={len(result.conversation_ids)}")
    print(f"errors={result.errors} statuses={sorted(set(result.statuses))}")
    print(f"walls_ms min/max={min(result.walls_ms):.1f}/{max(result.walls_ms):.1f}")
    ok = result.errors == 0 and len(result.conversation_ids) == BURST_IDS
    print("SELF-CHECK", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.execute_live or args.url:
        print(
            "refused: live Cloud Run execution needs a separate explicit "
            "authorization window; this command only prepares.",
            file=sys.stderr,
        )
        return 3
    if args.estimate_only:
        print(json.dumps(estimate_all(), indent=2, sort_keys=True))
        return 0 if estimate_all()["within_stop_line"] else 1
    if args.print_plan:
        print_plan()
        return 0
    if args.manifest_only:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        path = args.output_dir / f"{args.prefix}.manifest.json"
        path.write_text(json.dumps(manifest(args.prefix, args.rounds), indent=2) + "\n")
        print(f"manifest={path}")
        return 0
    if args.self_check:
        return asyncio.run(_self_check(args.prefix))
    print("choose one of --self-check, --estimate-only, --print-plan, --manifest-only")
    return 2


if __name__ == "__main__":
    sys.exit(main())
