"""Baseline semantic evaluation of the current model against the corpus.

Manual DEV runner, not CI: it replays the versioned conversation corpus
(`evals/conversation/cases.yaml`) against the real `GeminiTurnModel` with
ADC and reports, per family, the observed route, the semantic proposal
fields available today, latency and token usage.

The current model contract exposes only `message`, `route` and
`action_requested`. Expectations about conversation goals, confirmation
state, dispatch eligibility or external operation truth that the contract
cannot express are reported as NOT REPRESENTABLE IN CURRENT CONTRACT
instead of being faked. No prompt, schema or runtime change happens here.

Usage:
    python evals/conversation_baseline_eval.py [--families fam1,fam2]
"""

import argparse
import asyncio
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from google.genai import Client
from google.genai.types import HttpOptions

from app.conversation.gemini import GeminiBaseline, GeminiTurnModel

CORPUS_PATH = Path(__file__).parent / "conversation" / "cases.yaml"
DEFAULT_REPETITIONS = 3

NOT_REPRESENTABLE = "NOT REPRESENTABLE IN CURRENT CONTRACT"


def load_corpus() -> list[dict[str, Any]]:
    with CORPUS_PATH.open("r", encoding="utf-8") as handle:
        data: list[dict[str, Any]] = yaml.safe_load(handle)["cases"]
        return data


def classify_case(case: dict[str, Any]) -> tuple[str, str | None]:
    """Classify what the current contract can and cannot check."""
    expected = case["expected"]
    route = expected.get("route")
    if route is None:
        return "SKIPPED", None
    # Everything beyond route/first-utterance behavior is out of contract.
    deep_fields = [
        expected.get("confirmation_state"),
        expected.get("action_eligibility"),
        expected.get("dispatch_count"),
        expected.get("conversation_goal"),
    ]
    multi_turn = len(case.get("turns", [])) > 1
    has_external_events = bool(case.get("external_events"))
    if multi_turn or has_external_events or any(v is not None for v in deep_fields):
        return "PARTIAL", route
    return "FULL", route


async def run_case(
    model: GeminiTurnModel, case: dict[str, Any], repetitions: int
) -> dict[str, Any]:
    verdict, expected_route = classify_case(case)
    results: list[dict[str, Any]] = []
    first_transcript = next(
        (t.get("transcript") for t in case.get("turns", []) if t.get("transcript")), ""
    )
    for _ in range(repetitions if first_transcript else 1):
        start = time.monotonic()
        decision = await model.decide(
            transcript=first_transcript,
            identity_validated=bool(case["initial_state"].get("identity_validated")),
            requested_action=None,
            pending_operation=None,
        )
        latency_ms = (time.monotonic() - start) * 1000.0
        results.append(
            {
                "route": decision.route.value,
                "action_requested": (
                    decision.action_requested.value if decision.action_requested else None
                ),
                "latency_ms": round(latency_ms, 0),
            }
        )
    routes = Counter(r["route"] for r in results)
    return {
        "case_id": case["case_id"],
        "family": case["family"],
        "verdict": verdict,
        "expected_route": expected_route,
        "observed_routes": dict(routes),
        "route_stable_match": (
            len(routes) == 1 and expected_route in routes if verdict != "SKIPPED" else None
        ),
        "action_requested_values": sorted(
            {r["action_requested"] for r in results if r["action_requested"]}
        ),
        "latency_ms_max": max((r["latency_ms"] for r in results), default=0),
        "deep_expectations": NOT_REPRESENTABLE if verdict in {"PARTIAL"} else None,
    }


def print_report(report: list[dict[str, Any]], baseline: GeminiBaseline) -> None:
    print("=== CU013 conversation baseline eval (manual, outside CI) ===")
    print(f"provider={baseline.provider} project={baseline.project}")
    print(f"location={baseline.location} model={baseline.model}")
    print(f"api_version={baseline.api_version} thinking_budget={baseline.thinking_budget}")
    print()
    by_family: dict[str, list[dict[str, Any]]] = {}
    for item in report:
        by_family.setdefault(item["family"], []).append(item)
    families_ok = 0
    for family in sorted(by_family):
        items = by_family[family]
        checked = [i for i in items if i["verdict"] != "SKIPPED"]
        matches = [i for i in checked if i["route_stable_match"]]
        status = "OK" if checked and len(matches) == len(checked) else "MISMATCH"
        if status == "OK":
            families_ok += 1
        print(
            f"[{status}] family={family} cases={len(items)} "
            f"route_matches={len(matches)}/{len(checked)}"
        )
        for item in items:
            print(
                f"  {item['case_id']}: verdict={item['verdict']} "
                f"expected={item['expected_route']} observed={item['observed_routes']} "
                f"action_requested={item['action_requested_values'] or 'none'} "
                f"latency_max={item['latency_ms_max']:.0f}ms"
            )
            if item["deep_expectations"]:
                print(f"    {item['deep_expectations']}: goal/confirmation/dispatch/truth checks")
    total = len(report)
    print()
    print(
        f"families_ok={families_ok}/{len(by_family)} cases={total} "
        f"note: deep conversational properties are out of the current model contract"
    )


async def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--families", default=None, help="comma-separated family filter")
    parser.add_argument(
        "--repetitions", type=int, default=DEFAULT_REPETITIONS, help="calls per first turn"
    )
    args = parser.parse_args()

    cases = load_corpus()
    if args.families:
        wanted = {f.strip() for f in args.families.split(",")}
        cases = [c for c in cases if c["family"] in wanted]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2

    baseline = GeminiBaseline.from_env()
    client = Client(
        vertexai=True,
        project=baseline.project,
        location=baseline.location,
        http_options=HttpOptions(api_version=baseline.api_version),
    )
    model = GeminiTurnModel(client, baseline)
    try:
        report = [await run_case(model, case, args.repetitions) for case in cases]
        print_report(report, baseline)
    finally:
        await client.aio.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
