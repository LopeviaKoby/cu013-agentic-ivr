"""Pure paired comparator for CU013 conversation evaluation artifacts.

Compares two structured run artifacts written by `conversation_eval.py`
without calling the model. It never rewrites evidence, never averages failures
into a vanity score and never invents an SLO:

- incompatible run identities are refused unless the differing dimensions are
  declared as the variable under test or as accepted confounders;
- any new candidate occurrence of an executed critical violation forces
  REJECT;
- unresolved unrelated regressions and incomplete paired evidence force
  NEEDS OWNER DECISION;
- runtime-blocked unsafe model proposals stay separate from executed
  violations: they are model semantic failures, not executed criticals;
- a targeted improvement with no regressions can ACCEPT.

Usage:
    python evals/conversation_compare.py --baseline baseline.json \
        --candidate candidate.json [--variable model_id] \
        [--confounder corpus_changed] [--target-family fam1] \
        [--candidate-rerun rerun.json]

Exit codes: 0 ACCEPT, 1 NEEDS OWNER DECISION, 2 REJECT, 3 incompatible evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.conversation_lab import (
    COMPARISON_ARTIFACT_KIND,
    DEFAULT_RESULTS_DIR,
    LAB_SCHEMA_VERSION,
    RUN_ARTIFACT_KIND,
    SPOKEN_QUALITY_CRITERIA,
    SPOKEN_QUALITY_RATINGS,
    LabError,
    sanitization_findings,
)

VERDICT_ACCEPT = "ACCEPT"
VERDICT_REJECT = "REJECT"
VERDICT_OWNER = "NEEDS OWNER DECISION"

PROMPT_EXPLAINING_DIMENSIONS = {
    "effective_prompt_hash",
    "response_schema_hash",
    "state_projection_hash",
    "decision_schema_hash",
    "memory_renderer_hash",
    "procedure_schema_hash",
    # The memory variant itself changes the rendered model input by
    # construction (procedure-only adds the procedure block, recent memory
    # adds the window), so its token delta is explained when declared as
    # the variable under test.
    "memory_variant",
    "memory_n",
    # Prompt wording changes the rendered block wording by construction.
    "prompt_strategy",
    "prompt_strategy_hash",
    # Required structured procedure classification changes the sent schema
    # by construction.
    "strict_procedure_observation",
}
MODEL_EXPLAINING_DIMENSIONS = {
    "model_id",
    "provider",
    "region",
    "model_location",
    "api_version",
    "thinking_budget",
    "thinking_level",
    "timeout_ms",
    "attempts",
    "model_revision",
}


def load_artifact(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != RUN_ARTIFACT_KIND:
        raise LabError(f"{path}: not a {RUN_ARTIFACT_KIND} artifact")
    if payload.get("schema_version") != LAB_SCHEMA_VERSION:
        raise LabError(f"{path}: unsupported run artifact schema")
    findings = sanitization_findings(payload)
    if findings:
        raise LabError(f"{path}: evidence failed sanitization: {findings}")
    return payload


def repetition_index(
    artifact: Mapping[str, Any],
) -> dict[tuple[str, str, int], tuple[Mapping[str, Any], Mapping[str, Any]]]:
    index: dict[tuple[str, str, int], tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    for case in artifact["cases"]:
        for repetition in case["repetitions"]:
            index[(case["case_id"], case["trial_id"], repetition["repetition_id"])] = (
                case,
                repetition,
            )
    return index


def merge_reruns(
    artifact: dict[str, Any], reruns: Sequence[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Merge focused rerun evidence without erasing the original artifact."""
    merged = json.loads(json.dumps(artifact))
    merges: list[dict[str, Any]] = []
    for rerun in reruns:
        replaced: list[str] = []
        index = repetition_index(merged)
        for case in rerun["cases"]:
            for repetition in case["repetitions"]:
                key = (case["case_id"], case["trial_id"], repetition["repetition_id"])
                if key in index:
                    target_case, target_repetition = index[key]
                    target_case["repetitions"].remove(target_repetition)
                    target_case["repetitions"].append(repetition)
                    replaced.append(f"{key[0]}/{key[1]}/rep{key[2]}")
                else:
                    merged["cases"].append(case)
                    replaced.append(f"{key[0]}/{key[1]}/rep{key[2]} (added)")
        merges.append({"run_id": rerun["run_id"], "replaced": sorted(set(replaced))})
    return merged, merges


def check_compatibility(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    variables: Sequence[str],
    confounders: Sequence[str],
) -> dict[str, Any]:
    """Verify identities and report which differing dimensions are declared."""
    declared = set(variables) | set(confounders)
    declared |= {name.removesuffix("_changed") for name in declared}
    differences: list[str] = []
    baseline_variant = baseline["variant"]
    candidate_variant = candidate["variant"]
    for name in sorted(set(baseline_variant) | set(candidate_variant)):
        if baseline_variant.get(name) != candidate_variant.get(name):
            differences.append(name)
    if baseline["corpus"]["sha256"] != candidate["corpus"]["sha256"]:
        differences.append("corpus")
    if baseline["evaluator"] != candidate["evaluator"]:
        differences.append("evaluator")
    if baseline["repetition_policy"] != candidate["repetition_policy"]:
        differences.append("repetition_policy")
    if baseline["schema_version"] != candidate["schema_version"]:
        differences.append("schema_version")
    unexplained = [name for name in differences if name not in declared]
    declared_variables = [name for name in differences if name in set(variables)]
    declared_confounders = [name for name in differences if name in set(confounders)]
    return {
        "ok": not unexplained,
        "differing_dimensions": differences,
        "declared_variables": declared_variables,
        "declared_confounders": declared_confounders,
        "unexplained_dimensions": unexplained,
        "declared_but_identical": sorted(
            name for name in set(variables) | set(confounders) if name not in differences
        ),
    }


def pair_repetitions(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    baseline_index = repetition_index(baseline)
    candidate_index = repetition_index(candidate)
    pairs: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    infra_pairs: list[dict[str, Any]] = []
    keys = sorted(set(baseline_index) | set(candidate_index))
    for key in keys:
        case_id, trial_id, repetition_id = key
        pair_id = f"{case_id}/{trial_id}/rep{repetition_id}"
        baseline_entry = baseline_index.get(key)
        candidate_entry = candidate_index.get(key)
        if baseline_entry is None or candidate_entry is None:
            incomplete.append(
                {
                    "pair": pair_id,
                    "missing": "candidate" if candidate_entry is None else "baseline",
                }
            )
            continue
        baseline_case, baseline_rep = baseline_entry
        _candidate_case, candidate_rep = candidate_entry
        if baseline_rep["status"] != "valid" or candidate_rep["status"] != "valid":
            infra_pairs.append(
                {
                    "pair": pair_id,
                    "baseline_status": baseline_rep["status"],
                    "candidate_status": candidate_rep["status"],
                }
            )
            continue
        pairs.append(
            {
                "pair": pair_id,
                "case_id": case_id,
                "trial_id": trial_id,
                "family": baseline_case["family"],
                "scenario_kind": baseline_case["scenario_kind"],
                "baseline_classification": baseline_rep["classification"],
                "candidate_classification": candidate_rep["classification"],
                "baseline": baseline_rep,
                "candidate": candidate_rep,
            }
        )
    return {"pairs": pairs, "incomplete": incomplete, "infra_pairs": infra_pairs}


def critical_findings(artifact: Mapping[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for case in artifact["cases"]:
        for repetition in case["repetitions"]:
            for name in repetition.get("critical_findings", []):
                findings.append(
                    {
                        "case_id": case["case_id"],
                        "trial_id": case["trial_id"],
                        "repetition_id": str(repetition["repetition_id"]),
                        "class": name,
                    }
                )
    return findings


def _first_turn_divergence(
    baseline_rep: Mapping[str, Any], candidate_rep: Mapping[str, Any]
) -> int | None:
    baseline_turns = baseline_rep.get("turn_verdicts") or []
    candidate_turns = candidate_rep.get("turn_verdicts") or []
    for index in range(max(len(baseline_turns), len(candidate_turns))):
        baseline_verdicts = baseline_turns[index] if index < len(baseline_turns) else {}
        candidate_verdicts = candidate_turns[index] if index < len(candidate_turns) else {}
        if baseline_verdicts != candidate_verdicts:
            return index + 1
    if baseline_rep.get("case_verdicts") != candidate_rep.get("case_verdicts"):
        return candidate_rep.get("first_divergent_turn")
    return None


def _new_property_failures(
    baseline_rep: Mapping[str, Any], candidate_rep: Mapping[str, Any]
) -> list[str]:
    failures: list[str] = []
    for name, verdict in candidate_rep.get("case_verdicts", {}).items():
        if verdict == "FAIL" and baseline_rep.get("case_verdicts", {}).get(name) != "FAIL":
            failures.append(f"case.{name}")
    baseline_turns = baseline_rep.get("turn_verdicts") or []
    candidate_turns = candidate_rep.get("turn_verdicts") or []
    for index, verdicts in enumerate(candidate_turns):
        baseline_verdicts = baseline_turns[index] if index < len(baseline_turns) else {}
        for name, verdict in verdicts.items():
            if verdict == "FAIL" and baseline_verdicts.get(name) != "FAIL":
                failures.append(f"turn{index + 1}.{name}")
    return failures


def _fixed_properties(
    baseline_rep: Mapping[str, Any], candidate_rep: Mapping[str, Any]
) -> list[str]:
    fixed: list[str] = []
    for name, verdict in baseline_rep.get("case_verdicts", {}).items():
        if verdict == "FAIL" and candidate_rep.get("case_verdicts", {}).get(name) == "PASS":
            fixed.append(f"case.{name}")
    baseline_turns = baseline_rep.get("turn_verdicts") or []
    candidate_turns = candidate_rep.get("turn_verdicts") or []
    for index, verdicts in enumerate(baseline_turns):
        candidate_verdicts = candidate_turns[index] if index < len(candidate_turns) else {}
        for name, verdict in verdicts.items():
            if verdict == "FAIL" and candidate_verdicts.get(name) == "PASS":
                fixed.append(f"turn{index + 1}.{name}")
    return fixed


def compare_semantics(
    pairing: Mapping[str, Any], *, target_families: Sequence[str]
) -> dict[str, Any]:
    targets = set(target_families)
    new_failures: list[dict[str, Any]] = []
    targeted_improvements: list[dict[str, Any]] = []
    targeted_regressions: list[dict[str, Any]] = []
    unrelated_regressions: list[dict[str, Any]] = []
    first_divergences: list[dict[str, Any]] = []
    changed_cases: list[dict[str, Any]] = []
    for pair in pairing["pairs"]:
        baseline_rep = pair["baseline"]
        candidate_rep = pair["candidate"]
        failures = _new_property_failures(baseline_rep, candidate_rep)
        fixed = _fixed_properties(baseline_rep, candidate_rep)
        divergence = _first_turn_divergence(baseline_rep, candidate_rep)
        classification_changed = pair["baseline_classification"] != pair["candidate_classification"]
        if divergence is not None or classification_changed:
            changed_cases.append(
                {
                    "pair": pair["pair"],
                    "case_id": pair["case_id"],
                    "family": pair["family"],
                    "baseline": pair["baseline_classification"],
                    "candidate": pair["candidate_classification"],
                    "first_divergent_turn": divergence,
                }
            )
        if divergence is not None:
            first_divergences.append({"pair": pair["pair"], "turn": divergence})
        entry = {
            "pair": pair["pair"],
            "case_id": pair["case_id"],
            "family": pair["family"],
            "properties": failures,
            "baseline": pair["baseline_classification"],
            "candidate": pair["candidate_classification"],
            "first_divergent_turn": divergence,
        }
        if failures:
            new_failures.append(entry)
            if pair["family"] in targets:
                targeted_regressions.append(entry)
            else:
                unrelated_regressions.append(entry)
        if fixed:
            improvement = {
                "pair": pair["pair"],
                "case_id": pair["case_id"],
                "family": pair["family"],
                "properties": fixed,
                "targeted": pair["family"] in targets or not targets,
            }
            targeted_improvements.append(improvement)
    return {
        "new_failures": new_failures,
        "targeted_improvements": [item for item in targeted_improvements if item["targeted"]],
        "other_improvements": [item for item in targeted_improvements if not item["targeted"]],
        "targeted_regressions": targeted_regressions,
        "unrelated_regressions": unrelated_regressions,
        "changed_cases": changed_cases,
        "first_divergences": first_divergences,
    }


def compare_distributions(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    baseline_aggregate = baseline["aggregate"]
    candidate_aggregate = candidate["aggregate"]
    changed: list[dict[str, Any]] = []
    for group in ("case_properties", "turn_properties"):
        baseline_group = baseline_aggregate.get(group, {})
        candidate_group = candidate_aggregate.get(group, {})
        for name in sorted(set(baseline_group) | set(candidate_group)):
            if baseline_group.get(name) != candidate_group.get(name):
                changed.append(
                    {
                        "group": group,
                        "property": name,
                        "baseline": baseline_group.get(name),
                        "candidate": candidate_group.get(name),
                    }
                )
    return {
        "case_properties": {
            "baseline": baseline_aggregate.get("case_properties", {}),
            "candidate": candidate_aggregate.get("case_properties", {}),
        },
        "turn_properties": {
            "baseline": baseline_aggregate.get("turn_properties", {}),
            "candidate": candidate_aggregate.get("turn_properties", {}),
        },
        "changed_properties": changed,
        "routes": {
            "baseline": baseline_aggregate.get("route_distribution", {}),
            "candidate": candidate_aggregate.get("route_distribution", {}),
        },
    }


def _delta(candidate_value: Any, baseline_value: Any) -> float | None:
    if not isinstance(candidate_value, (int, float)) or not isinstance(
        baseline_value, (int, float)
    ):
        return None
    return round(candidate_value - baseline_value, 3)


def compare_efficiency(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    changed_dimensions: Sequence[str],
    confounders: Sequence[str],
) -> dict[str, Any]:
    baseline_latency = baseline["latency"]
    candidate_latency = candidate["latency"]
    baseline_tokens = baseline["tokens"]
    candidate_tokens = candidate["tokens"]
    findings: list[str] = []
    prompt_explained = bool(set(changed_dimensions) & PROMPT_EXPLAINING_DIMENSIONS) or (
        "prompt_changed" in confounders
    )
    model_explained = bool(set(changed_dimensions) & MODEL_EXPLAINING_DIMENSIONS) or (
        "provider_changed" in confounders
    )
    baseline_prompt = baseline_tokens["prompt_tokens"].get("p50")
    candidate_prompt = candidate_tokens["prompt_tokens"].get("p50")
    token_change = (
        baseline_prompt is not None
        and candidate_prompt is not None
        and baseline_prompt != candidate_prompt
    )
    baseline_model = baseline_latency["model_latency_ms"]
    candidate_model = candidate_latency["model_latency_ms"]
    latency_up = (
        baseline_model.get("p50") is not None
        and candidate_model.get("p50") is not None
        and candidate_model["p50"] > baseline_model["p50"]
        and candidate_model.get("p95") is not None
        and baseline_model.get("p95") is not None
        and candidate_model["p95"] > baseline_model["p95"]
    )
    unexplained_token_growth = token_change and not prompt_explained
    unexplained_latency = latency_up and not model_explained and not token_change
    if token_change:
        direction = "higher" if (candidate_prompt or 0) > (baseline_prompt or 0) else "lower"
        findings.append(
            f"prompt tokens per call are {direction} "
            f"(baseline p50={baseline_prompt}, candidate p50={candidate_prompt})"
        )
        if not prompt_explained:
            findings.append(
                "prompt token change is not explained by a declared variable or confounder"
            )
    if latency_up:
        findings.append(
            "model latency p50 and p95 are higher in this sample; "
            "provider variance remains a confounder"
        )
        if not model_explained and not token_change:
            findings.append("latency deterioration is not explained by the declared change")
    if not token_change and not latency_up:
        findings.append("no material regression observed in this sample")
    if not model_explained:
        findings.append("sample shows latency values but provider variance remains a confounder")
    return {
        "baseline": {
            "latency": baseline_latency,
            "tokens": baseline_tokens,
        },
        "candidate": {
            "latency": candidate_latency,
            "tokens": candidate_tokens,
        },
        "deltas": {
            "model_latency_p50_ms": _delta(candidate_model.get("p50"), baseline_model.get("p50")),
            "model_latency_p95_ms": _delta(candidate_model.get("p95"), baseline_model.get("p95")),
            "prompt_tokens_p50": _delta(candidate_prompt, baseline_prompt),
            "completion_tokens_p50": _delta(
                candidate_tokens["completion_tokens"].get("p50"),
                baseline_tokens["completion_tokens"].get("p50"),
            ),
        },
        "findings": findings,
        "unexplained": unexplained_token_growth or unexplained_latency,
    }


def spoken_quality_review(
    pairing: Mapping[str, Any], semantics: Mapping[str, Any], candidate: Mapping[str, Any]
) -> list[dict[str, Any]]:
    changed_families = {item["family"] for item in semantics["new_failures"]}
    changed_families.update(item["family"] for item in semantics["changed_cases"])
    rows: list[dict[str, Any]] = []
    controls_by_family: dict[str, list[str]] = {}
    for case in candidate["cases"]:
        for group in case.get("controls", {}).values():
            for control in group:
                controls_by_family.setdefault(case["family"], []).append(control["case_id"])
    for family in sorted(changed_families):
        for pair in pairing["pairs"]:
            if pair["family"] != family:
                continue
            rows.append(_review_row(pair, role="changed"))
        for control_id in sorted(set(controls_by_family.get(family, []))):
            for pair in pairing["pairs"]:
                if pair["case_id"] == control_id:
                    rows.append(_review_row(pair, role="control"))
    return rows


def _review_row(pair: Mapping[str, Any], *, role: str) -> dict[str, Any]:
    turns = pair["candidate"].get("turn_verdicts") or []
    return {
        "case_id": pair["case_id"],
        "trial_id": pair["trial_id"],
        "family": pair["family"],
        "role": role,
        "turn_ids": [f"turn{index + 1}" for index in range(len(turns))],
        "ratings": {criterion: "NOT EVIDENCED" for criterion in SPOKEN_QUALITY_CRITERIA},
        "allowed_ratings": list(SPOKEN_QUALITY_RATINGS),
    }


def compare_runs(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    variables: Sequence[str] = (),
    confounders: Sequence[str] = (),
    target_families: Sequence[str] = (),
    baseline_merges: Sequence[dict[str, Any]] = (),
    candidate_merges: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    compatibility = check_compatibility(
        baseline, candidate, variables=variables, confounders=confounders
    )
    if not compatibility["ok"]:
        raise LabError(
            "incompatible evidence: unexplained differing dimensions "
            f"{compatibility['unexplained_dimensions']}; declare them as --variable or "
            "--confounder"
        )
    pairing = pair_repetitions(baseline, candidate)
    baseline_criticals = critical_findings(baseline)
    candidate_criticals = critical_findings(candidate)
    baseline_keys = {json.dumps(item, sort_keys=True) for item in baseline_criticals}
    new_criticals = [
        item
        for item in candidate_criticals
        if json.dumps(item, sort_keys=True) not in baseline_keys
    ]
    semantics = compare_semantics(pairing, target_families=target_families)
    distributions = compare_distributions(baseline, candidate)
    efficiency = compare_efficiency(
        baseline,
        candidate,
        changed_dimensions=compatibility["differing_dimensions"],
        confounders=confounders,
    )
    review = spoken_quality_review(pairing, semantics, candidate)

    reasons: list[str] = []
    if new_criticals:
        described = ", ".join(
            f"{item['case_id']}/rep{item['repetition_id']} {item['class']}"
            for item in new_criticals
        )
        reasons.append(f"new executed critical violations: {described}")
    if pairing["incomplete"]:
        reasons.append(f"incomplete paired evidence: {len(pairing['incomplete'])} pair(s) missing")
    if pairing["infra_pairs"]:
        reasons.append(f"INFRA pairs require focused reruns: {len(pairing['infra_pairs'])} pair(s)")
    if semantics["unrelated_regressions"]:
        reasons.append(
            f"unresolved unrelated regressions: {len(semantics['unrelated_regressions'])}"
        )
    if semantics["targeted_regressions"]:
        reasons.append(f"targeted regressions: {len(semantics['targeted_regressions'])}")
    if efficiency["unexplained"]:
        reasons.append("unexplained efficiency deterioration")

    if new_criticals:
        verdict = VERDICT_REJECT
    elif reasons:
        verdict = VERDICT_OWNER
    else:
        verdict = VERDICT_ACCEPT

    return {
        "artifact_kind": COMPARISON_ARTIFACT_KIND,
        "schema_version": LAB_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "baseline": {
            "run_id": baseline["run_id"],
            "variant_digest": baseline["variant_digest"],
            "variant": baseline["variant"],
        },
        "candidate": {
            "run_id": candidate["run_id"],
            "variant_digest": candidate["variant_digest"],
            "variant": candidate["variant"],
        },
        "declared": {
            "variables": list(variables),
            "confounders": list(confounders),
            "target_families": list(target_families),
        },
        "compatibility": compatibility,
        "evidence": {
            "paired_valid": len(pairing["pairs"]),
            "incomplete": pairing["incomplete"],
            "infra_pairs": pairing["infra_pairs"],
            "baseline_infra": baseline.get("infra_count", 0),
            "candidate_infra": candidate.get("infra_count", 0),
            "baseline_merged_reruns": list(baseline_merges),
            "candidate_merged_reruns": list(candidate_merges),
        },
        "critical_gate": {
            "new": new_criticals,
            "baseline": baseline_criticals,
            "candidate": candidate_criticals,
            "reject": bool(new_criticals),
        },
        "semantic": semantics,
        "property_distributions": distributions,
        "efficiency": efficiency,
        "spoken_quality_review": review,
        "verdict": verdict,
        "reasons": reasons,
    }


def print_report(comparison: Mapping[str, Any]) -> None:
    print("=== CU013 conversation evaluation comparison (pure, no model) ===")
    baseline_label = comparison["baseline"]
    candidate_label = comparison["candidate"]
    print(f"baseline={baseline_label['run_id']} digest={baseline_label['variant_digest']}")
    print(f"candidate={candidate_label['run_id']} digest={candidate_label['variant_digest']}")
    print(f"declared={comparison['declared']}")
    compatibility = comparison["compatibility"]
    print(
        f"compatibility differing={compatibility['differing_dimensions']} "
        f"unexplained={compatibility['unexplained_dimensions']}"
    )
    evidence = comparison["evidence"]
    print(
        f"paired_valid={evidence['paired_valid']} incomplete={len(evidence['incomplete'])} "
        f"infra_pairs={len(evidence['infra_pairs'])}"
    )
    gate = comparison["critical_gate"]
    print(f"critical_gate new={gate['new']} baseline={gate['baseline']}")
    semantic = comparison["semantic"]
    print(f"new_failures={len(semantic['new_failures'])}")
    for item in semantic["new_failures"]:
        print(f"  FAIL {item['pair']} {item['family']} properties={item['properties']}")
    print(f"targeted_improvements={len(semantic['targeted_improvements'])}")
    for item in semantic["targeted_improvements"]:
        print(f"  FIXED {item['pair']} {item['family']} properties={item['properties']}")
    print(f"unrelated_regressions={len(semantic['unrelated_regressions'])}")
    print(f"targeted_regressions={len(semantic['targeted_regressions'])}")
    print(f"first_divergences={semantic['first_divergences']}")
    for change in comparison["property_distributions"]["changed_properties"]:
        print(
            f"  property {change['group']}.{change['property']} "
            f"baseline={change['baseline']} candidate={change['candidate']}"
        )
    print(f"routes baseline={comparison['property_distributions']['routes']['baseline']}")
    print(f"routes candidate={comparison['property_distributions']['routes']['candidate']}")
    for finding in comparison["efficiency"]["findings"]:
        print(f"efficiency: {finding}")
    print(f"efficiency_deltas={comparison['efficiency']['deltas']}")
    print("spoken_quality_review (manual; fill MEETS / CONCERN / NOT EVIDENCED):")
    for row in comparison["spoken_quality_review"]:
        print(f"  {row['case_id']} {row['role']} turns={row['turn_ids']} ratings={row['ratings']}")
    print(f"VERDICT {comparison['verdict']}")
    for reason in comparison["reasons"]:
        print(f"  reason: {reason}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CU013 paired conversation comparison")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--variable", action="append", default=[], help="declared variable")
    parser.add_argument("--confounder", action="append", default=[], help="declared confounder")
    parser.add_argument("--target-family", action="append", default=[], help="targeted family")
    parser.add_argument("--baseline-rerun", type=Path, action="append", default=[])
    parser.add_argument("--candidate-rerun", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        baseline = load_artifact(args.baseline)
        candidate = load_artifact(args.candidate)
        baseline, baseline_merges = merge_reruns(
            baseline, [load_artifact(path) for path in args.baseline_rerun]
        )
        candidate, candidate_merges = merge_reruns(
            candidate, [load_artifact(path) for path in args.candidate_rerun]
        )
        comparison = compare_runs(
            baseline,
            candidate,
            variables=args.variable,
            confounders=args.confounder,
            target_families=args.target_family,
            baseline_merges=baseline_merges,
            candidate_merges=candidate_merges,
        )
    except LabError as exc:
        print(f"comparator refused: {exc}", file=sys.stderr)
        return 3
    print_report(comparison)
    if not args.no_write:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = args.output_dir / (
            f"{baseline['run_id']}__{candidate['run_id']}.comparison.json"
        )
        output_path.write_text(
            json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"comparison_artifact={output_path}")
    if comparison["verdict"] == VERDICT_REJECT:
        return 2
    if comparison["verdict"] == VERDICT_OWNER:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
