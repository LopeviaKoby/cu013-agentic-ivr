"""Metamorphic robustness layer for the CU013 conversational candidate.

Deterministic, invariant-preserving transforms are applied to selected golden
cases: fillers, frustration, repetition, self-correction, irrelevant context,
colloquial tail and a duration question. Each transformed case keeps the
source case oracles, so the shared verdict machinery decides whether the
business invariants (goal, progress, challenge, dispatch, claims) survived the
perturbation. No exact wording is ever required.

Usage:
    python evals/metamorphic_eval.py [--harness-language es|en]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from google.genai import Client
from google.genai.types import HttpOptions

from app.conversation.gemini import GeminiBaseline, GeminiTurnModel
from app.session.memory import RECENT_CONVERSATION_MEMORY, ExperimentalMemoryConfig
from app.session.metrics import RecordingTurnMetrics
from evals.conversation_eval import finalize_repetition, replay_trial, resolve_prompt_source
from evals.conversation_lab import (
    Outcome,
    iter_trials,
    load_corpus,
    sanitization_findings,
    summarize_verdicts,
    utc_now,
    validate_corpus,
)

Transform = Callable[[str], str]

TRANSFORMS: dict[str, Transform] = {
    "filler_prefix": lambda text: f"eh, perdón, {text}",
    "frustration_prefix": lambda text: f"esto es un desastre, {text}",
    "repetition": lambda text: f"{text}, {text}",
    "self_correction_prefix": lambda text: f"digo, mejor dicho, {text}",
    "irrelevant_context_prefix": lambda text: f"por cierto, ¿el café es gratis? {text}",
    "colloquial_tail": lambda text: f"{text}, dale",
    "duration_suffix": lambda text: f"{text} ¿y cuánto tarda?",
}

# Source families where the transform keeps the oracle valid. Confirmation
# sources exclude appended questions because a question can legitimately
# change the confirmation classification.
SOURCE_FAMILIES: dict[str, tuple[str, ...]] = {
    "direct-supported-request": (
        "filler_prefix",
        "frustration_prefix",
        "repetition",
        "self_correction_prefix",
        "irrelevant_context_prefix",
        "colloquial_tail",
        "duration_suffix",
    ),
    "side-question-before-action": (
        "filler_prefix",
        "frustration_prefix",
        "repetition",
        "self_correction_prefix",
    ),
    "goal-cancellation": (
        "filler_prefix",
        "frustration_prefix",
        "repetition",
        "self_correction_prefix",
        "colloquial_tail",
    ),
    "confirmation-affirmative": (
        "filler_prefix",
        "repetition",
        "self_correction_prefix",
    ),
    "identity-validated": (
        "filler_prefix",
        "frustration_prefix",
        "repetition",
    ),
    "procedure-lost-step": (
        "filler_prefix",
        "frustration_prefix",
        "irrelevant_context_prefix",
    ),
}


def build_metamorphic_cases(corpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for case in corpus:
        transforms = SOURCE_FAMILIES.get(case["family"])
        if transforms is None:
            continue
        turns = list(case.get("turns") or [])
        if not turns or not turns[0].get("transcript"):
            continue
        for name in transforms:
            transformed = json.loads(json.dumps(case))
            first = transformed["turns"][0]
            first["transcript"] = TRANSFORMS[name](first["transcript"])
            transformed["case_id"] = f"meta-{name.replace('_', '-')}-{case['case_id']}"
            transformed["family"] = f"metamorphic-{case['family']}"
            transformed["scenario_kind"] = case["scenario_kind"]
            transformed["tags"] = [f"transform:{name}", f"source:{case['case_id']}"]
            # Controls are review metadata that reference the golden set; the
            # transformed copy keeps the oracles only.
            transformed.pop("controls", None)
            cases.append(transformed)
    return cases


async def replay_case(
    model: GeminiTurnModel,
    metrics: RecordingTurnMetrics,
    case: dict[str, Any],
    *,
    now: datetime,
    experimental: ExperimentalMemoryConfig,
) -> list[tuple[int | None, str]]:
    results: list[tuple[int | None, str]] = []
    for trial_id, turn_index in iter_trials(case):
        replay = await replay_trial(
            model,
            metrics,
            case,
            trial_id,
            turn_index,
            now=now,
            experimental=experimental,
        )
        repetition = finalize_repetition(case, replay, repetition_id=1)
        results.append((turn_index, repetition.classification))
    return results


async def run(
    source_cases: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    harness_language: str,
) -> int:
    problems = validate_corpus(cases)
    if problems:
        for problem in problems:
            print(f"METAMORPHIC {problem}", file=sys.stderr)
        return 2
    prompt_source = resolve_prompt_source(
        "prompt_composition_protocols", harness_language=harness_language
    )
    baseline = GeminiBaseline.from_env()
    client = Client(
        vertexai=True,
        project=baseline.project,
        location=baseline.location,
        http_options=HttpOptions(api_version=baseline.api_version),
    )
    metrics = RecordingTurnMetrics()
    model = GeminiTurnModel(client, baseline, prompts=prompt_source, metrics=metrics)
    experimental = ExperimentalMemoryConfig(variant=RECENT_CONVERSATION_MEMORY, window_n=3)
    now = datetime.now(UTC)
    verdicts: list[str] = []
    invariant = 0
    divergent: list[dict[str, Any]] = []
    try:
        # Source baseline: the same oracle verdicts without the perturbation.
        source_results: dict[tuple[str, int | None], str] = {}
        for case in source_cases:
            for turn_index, classification in await replay_case(
                model, metrics, case, now=now, experimental=experimental
            ):
                source_results[(case["case_id"], turn_index)] = classification
        for case in cases:
            source_id = next(
                tag.split(":", 1)[1] for tag in case.get("tags", []) if tag.startswith("source:")
            )
            for turn_index, classification in await replay_case(
                model, metrics, case, now=now, experimental=experimental
            ):
                verdicts.append(classification)
                baseline_verdict = source_results.get((source_id, turn_index))
                if classification == baseline_verdict:
                    invariant += 1
                elif (
                    classification != Outcome.INFRA.value
                    and baseline_verdict != Outcome.INFRA.value
                ):
                    divergent.append(
                        {
                            "case_id": case["case_id"],
                            "source": source_id,
                            "baseline": baseline_verdict,
                            "observed": classification,
                        }
                    )
    finally:
        await client.aio.aclose()
    summary = summarize_verdicts(verdicts)
    compared = invariant + len(divergent)
    invariance = round(invariant / compared, 4) if compared else 0.0
    report = {
        "phase": "metamorphic",
        "harness_language": harness_language,
        "transforms": sorted(TRANSFORMS),
        "source_cases": len(source_cases),
        "cases": len(cases),
        "verdicts": summary,
        "invariance_rate": invariance,
        "divergent": divergent,
        "recorded_at": utc_now(),
    }
    findings = sanitization_findings(report)
    if findings:
        raise ValueError(f"metamorphic report failed sanitization: {findings}")
    output = REPO_ROOT / "evals" / "results" / f"metamorphic-{harness_language}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "cases": len(cases),
                "verdicts": summary,
                "invariance": invariance,
                "divergent": len(divergent),
            }
        )
    )
    for item in divergent:
        print("DIVERGENT", item["case_id"], item["baseline"], "->", item["observed"])
    print(f"report={output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CU013 metamorphic robustness suite")
    parser.add_argument("--harness-language", choices=["es", "en"], default="es")
    args = parser.parse_args(argv)
    corpus = load_corpus()
    source_cases = [case for case in corpus if case["family"] in SOURCE_FAMILIES]
    cases = build_metamorphic_cases(corpus)
    return asyncio.run(run(source_cases, cases, args.harness_language))


if __name__ == "__main__":
    sys.exit(main())
