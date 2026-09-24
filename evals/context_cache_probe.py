"""Context caching probe for the CU013 prompt bundle (manual, outside CI).

Three phases, measurement only:

- Phase A: exact provider token counts of the cacheable prefix per variant,
  compared with the documented Gemini 3 floor (4096 tokens). Below the floor
  the variant is NOT ELIGIBLE FOR EXPLICIT CACHE; no padding is ever added.
- Phase B: implicit caching microbenchmark (2 warmups + 10 valid serial calls
  per variant, small pacing) reporting `cached_content_token_count`, prompt
  tokens and model latency. Cache hits are a provider observation, not an
  assumption.
- Phase C: explicit caching is only attempted for naturally eligible
  variants; this probe refuses to create a cache below the floor and reports
  EXPLICIT CACHE NOT APPLICABLE instead. Any created cache would use a short
  TTL and would be deleted at the end, never including PII or caller text.

Usage:
    python evals/context_cache_probe.py --phase a
    python evals/context_cache_probe.py --phase b --variant RESET_PASSWORD:focused
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from google.genai import Client
from google.genai.types import HttpOptions

from app.conversation.gemini import GeminiBaseline, GeminiTurnModel
from app.conversation.prompt_renderer import PromptBundle, PromptSource
from app.session.actions import Action
from app.session.memory import (
    DEFAULT_PROMPT_POLICY,
    GUIDED_PROCEDURE_ID,
    GUIDED_STEPS,
    ExperimentalProcedureState,
    render_memory_block,
)
from app.session.metrics import RecordingTurnMetrics
from app.session.record import ConversationGoal
from evals.conversation_eval import resolve_prompt_source
from evals.conversation_lab import summarize_tokens, summarize_values

CACHE_FLOOR_TOKENS = 4096
WARMUPS = 2
MEASURED_CALLS = 10
PACING_SECONDS = 1.2
SAMPLE_TRANSCRIPT = "necesito restablecer mi contrasena"
EXPLICIT_TTL_SECONDS = 900


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CU013 context cache probe")
    parser.add_argument("--phase", choices=["a", "b", "c", "all"], default="a")
    parser.add_argument(
        "--prompt-variant",
        choices=["prompt_composition_protocols", "single_baseline_snapshot"],
        default="prompt_composition_protocols",
    )
    parser.add_argument(
        "--variant",
        default=None,
        help="comma-separated variant labels from phase A (default: all variants)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evals/results"),
        help="local evidence directory (Git-ignored)",
    )
    return parser.parse_args(argv)


def cacheable_variants(prompt_source: PromptSource) -> list[tuple[str, str]]:
    """Label and cacheable system-instruction text per natural variant."""
    if not isinstance(prompt_source, PromptBundle):
        return [("base", prompt_source.system_instructions(None))]
    variants = [("base", prompt_source.system_instructions(None))]
    for action in (Action.RESET_PASSWORD, Action.UNLOCK_ACCOUNT):
        goal = ConversationGoal(action=action, revision=1)
        variants.append((action.value, prompt_source.system_instructions(goal)))
        if action is Action.RESET_PASSWORD:
            for step in GUIDED_STEPS:
                variants.append(
                    (f"{action.value}:{step}", prompt_source.system_instructions(goal, step))
                )
    return variants


async def count_tokens(client: Client, model: str, text: str) -> int | None:
    try:
        response = await client.aio.models.count_tokens(model=model, contents=text)
    except Exception:
        return None
    total = response.total_tokens
    return int(total) if total is not None else None


async def phase_a(client: Client, baseline: GeminiBaseline, source: PromptSource) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for label, text in cacheable_variants(source):
        tokens = await count_tokens(client, baseline.model, text)
        eligible = tokens is not None and tokens >= CACHE_FLOOR_TOKENS
        rows.append(
            {
                "variant": label,
                "cacheable_prefix_tokens": tokens,
                "provisional_verdict": (
                    "eligible" if eligible else "NOT ELIGIBLE FOR EXPLICIT CACHE"
                ),
            }
        )
        await asyncio.sleep(PACING_SECONDS)
    return {
        "phase": "a",
        "cache_floor_tokens": CACHE_FLOOR_TOKENS,
        "floor_source": "Gemini 3 family cache minimum (implicit and explicit)",
        "variants": rows,
    }


def sample_context(label: str) -> tuple[ConversationGoal | None, str | None, str]:
    """Fixed synthetic state per variant: same inputs, only the prefix differs."""
    now = datetime.now(UTC)
    if label == "base":
        return None, None, ""
    if label.startswith("RESET_PASSWORD:") and ":" in label:
        step = label.split(":", 1)[1]
        procedure = ExperimentalProcedureState(
            procedure_id=GUIDED_PROCEDURE_ID,
            current_step=step,
            goal_revision=1,
            opened_at=now,
        )
        memory_context, _ = render_memory_block(
            (), procedure, None, window_n=3, strategy=DEFAULT_PROMPT_POLICY
        )
        return ConversationGoal(action=Action.RESET_PASSWORD, revision=1), step, memory_context
    action = Action.RESET_PASSWORD if label == "RESET_PASSWORD" else Action.UNLOCK_ACCOUNT
    return ConversationGoal(action=action, revision=1), None, ""


async def phase_b(
    client: Client,
    baseline: GeminiBaseline,
    source: PromptSource,
    *,
    variant_label: str | None,
) -> dict[str, Any]:
    labels = cacheable_variants(source)
    wanted = {label.strip() for label in variant_label.split(",")} if variant_label else None
    selected = [item for item in labels if wanted is None or item[0] in wanted]
    metrics = RecordingTurnMetrics()
    model = GeminiTurnModel(client, baseline, prompts=source, metrics=metrics)
    rows: list[dict[str, Any]] = []
    for label, _text in selected:
        goal, procedure_current, memory_context = sample_context(label)
        cached_values: list[int] = []
        prompt_values: list[int] = []
        latency_values: list[float] = []
        statuses: list[str] = []
        for index in range(WARMUPS + MEASURED_CALLS):
            start = time.monotonic()
            status = "ok"
            try:
                await model.decide(
                    transcript=SAMPLE_TRANSCRIPT,
                    goal=goal,
                    identity_validated=False,
                    confirmation=None,
                    external_operation=None,
                    memory_context=memory_context or None,
                    procedure_current=procedure_current,
                )
            except Exception as exc:
                status = f"INFRA:{type(exc).__name__}"
            latency_ms = (time.monotonic() - start) * 1000.0
            counters = dict(metrics.drain_counters())
            if index >= WARMUPS and status == "ok":
                prompt_values.append(counters.get("prompt_tokens", 0))
                cached_values.append(counters.get("cached_tokens", 0))
                latency_values.append(latency_ms)
            statuses.append(status)
            await asyncio.sleep(PACING_SECONDS)
        rows.append(
            {
                "variant": label,
                "warmups": WARMUPS,
                "measured_calls": len(latency_values),
                "statuses": statuses,
                "cached_tokens": summarize_values([float(v) for v in cached_values]),
                "prompt_tokens": summarize_tokens(prompt_values, missing=0),
                "model_latency_ms": summarize_values(latency_values),
                "implicit_cache_observed": any(v > 0 for v in cached_values),
            }
        )
    return {"phase": "b", "rows": rows}


async def phase_c(client: Client, baseline: GeminiBaseline, source: PromptSource) -> dict[str, Any]:
    eligible: list[str] = []
    measured: list[dict[str, Any]] = []
    for label, text in cacheable_variants(source):
        tokens = await count_tokens(client, baseline.model, text)
        measured.append({"variant": label, "cacheable_prefix_tokens": tokens})
        if tokens is not None and tokens >= CACHE_FLOOR_TOKENS:
            eligible.append(label)
        await asyncio.sleep(PACING_SECONDS)
    if not eligible:
        return {
            "phase": "c",
            "verdict": "EXPLICIT CACHE NOT APPLICABLE",
            "reason": ("no cacheable prefix reaches the provider floor; padding is forbidden"),
            "cache_floor_tokens": CACHE_FLOOR_TOKENS,
            "measured": measured,
            "caches_created": [],
            "caches_deleted": [],
        }
    return {
        "phase": "c",
        "verdict": "EXPLICIT CACHE REJECT",
        "reason": (
            "eligible prefixes exist but the experiment requires an explicit "
            "system_instruction/tools-free request path and a semantic-equivalence "
            "probe that is not authorized by this iteration's default flow"
        ),
        "cache_floor_tokens": CACHE_FLOOR_TOKENS,
        "measured": measured,
        "caches_created": [],
        "caches_deleted": [],
        "ttl_seconds": EXPLICIT_TTL_SECONDS,
    }


async def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = resolve_prompt_source(args.prompt_variant)
    baseline = GeminiBaseline.from_env()
    client = Client(
        vertexai=True,
        project=baseline.project,
        location=baseline.location,
        http_options=HttpOptions(api_version=baseline.api_version),
    )
    report: dict[str, Any] = {
        "prompt_variant": args.prompt_variant,
        "model": baseline.model,
        "model_location": baseline.location,
        "thinking_level": baseline.thinking_level,
        "cache_floor_tokens": CACHE_FLOOR_TOKENS,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    try:
        if args.phase in {"a", "all"}:
            report["a"] = await phase_a(client, baseline, source)
        if args.phase in {"b", "all"}:
            report["b"] = await phase_b(client, baseline, source, variant_label=args.variant)
        if args.phase in {"c", "all"}:
            report["c"] = await phase_c(client, baseline, source)
    finally:
        await client.aio.aclose()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = report["recorded_at"].replace(":", "").replace("-", "")
    output_path = args.output_dir / f"context-cache-probe-{stamp}.json"
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "report": str(output_path),
        "phase_a": report.get("a", {}).get("variants"),
        "phase_b": [
            {
                "variant": row["variant"],
                "cached_tokens_p50": row["cached_tokens"]["p50"],
                "implicit_cache_observed": row["implicit_cache_observed"],
                "prompt_tokens_p50": row["prompt_tokens"]["p50"],
                "latency_p50": row["model_latency_ms"]["p50"],
                "latency_p95": row["model_latency_ms"]["p95"],
            }
            for row in report.get("b", {}).get("rows", [])
        ],
        "phase_c": report.get("c", {}).get("verdict"),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
