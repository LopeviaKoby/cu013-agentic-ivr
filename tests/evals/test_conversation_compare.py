"""Deterministic tests for the pure paired comparator; no model, no ADC."""

from __future__ import annotations

import pytest

from evals.conversation_compare import (
    compare_runs,
    merge_reruns,
)
from evals.conversation_lab import LabError
from tests.evals.fixtures import make_artifact, make_repetition, make_trial

IMPROVED_VARIANT = {
    "source_git_sha": "abc",
    "effective_prompt_hash": "new-prompt-hash",
    "model_id": "gemini-2.5-flash-lite",
    "working_tree_diff_hash": "clean",
}

MODEL_VARIANT = {
    "source_git_sha": "abc",
    "effective_prompt_hash": "prompt-hash",
    "model_id": "gemini-3-flash",
    "working_tree_diff_hash": "clean",
}


def _runs_with(
    baseline_verdicts: dict[str, str],
    candidate_verdicts: dict[str, str],
    *,
    family: str = "family-a",
) -> tuple[dict, dict]:
    baseline = make_artifact(
        run_id="baseline",
        cases=[
            make_trial(
                case_id="case-a",
                family=family,
                repetitions=[make_repetition(case_verdicts=baseline_verdicts)],
            )
        ],
    )
    candidate = make_artifact(
        run_id="candidate",
        variant=IMPROVED_VARIANT,
        cases=[
            make_trial(
                case_id="case-a",
                family=family,
                repetitions=[make_repetition(case_verdicts=candidate_verdicts)],
            )
        ],
    )
    return baseline, candidate


def test_target_improvement_without_regressions_accepts() -> None:
    baseline, candidate = _runs_with({"route": "FAIL"}, {"route": "PASS"})
    comparison = compare_runs(
        baseline,
        candidate,
        variables=["effective_prompt_hash"],
        target_families=["family-a"],
    )
    assert comparison["verdict"] == "ACCEPT"
    assert len(comparison["semantic"]["targeted_improvements"]) == 1
    assert comparison["semantic"]["unrelated_regressions"] == []


def test_unrelated_regression_needs_owner_decision() -> None:
    baseline, candidate = _runs_with({"route": "PASS"}, {"route": "FAIL"}, family="family-b")
    comparison = compare_runs(
        baseline,
        candidate,
        variables=["effective_prompt_hash"],
        target_families=["family-a"],
    )
    assert comparison["verdict"] == "NEEDS OWNER DECISION"
    assert len(comparison["semantic"]["unrelated_regressions"]) == 1


def test_targeted_regression_needs_owner_decision() -> None:
    baseline, candidate = _runs_with({"route": "PASS"}, {"route": "FAIL"}, family="family-a")
    comparison = compare_runs(
        baseline,
        candidate,
        variables=["effective_prompt_hash"],
        target_families=["family-a"],
    )
    assert comparison["verdict"] == "NEEDS OWNER DECISION"
    assert len(comparison["semantic"]["targeted_regressions"]) == 1


def test_new_critical_violation_forces_reject() -> None:
    baseline = make_artifact(
        run_id="baseline",
        cases=[
            make_trial(
                case_id="case-a",
                repetitions=[make_repetition(case_verdicts={"route": "PASS"})],
            )
        ],
    )
    candidate = make_artifact(
        run_id="candidate",
        variant=IMPROVED_VARIANT,
        cases=[
            make_trial(
                case_id="case-a",
                repetitions=[
                    make_repetition(
                        case_verdicts={"route": "PASS"},
                        critical_findings=["unauthorized_dispatch"],
                    )
                ],
            )
        ],
    )
    comparison = compare_runs(baseline, candidate, variables=["effective_prompt_hash"])
    assert comparison["verdict"] == "REJECT"
    assert comparison["critical_gate"]["reject"] is True
    assert comparison["critical_gate"]["new"][0]["class"] == "unauthorized_dispatch"


def test_duplicate_side_effect_forces_reject() -> None:
    baseline = make_artifact(run_id="baseline")
    candidate = make_artifact(
        run_id="candidate",
        variant=IMPROVED_VARIANT,
        cases=[
            make_trial(
                case_id="case-a",
                repetitions=[
                    make_repetition(
                        case_verdicts={"route": "PASS"},
                        critical_findings=["duplicate_side_effect"],
                    )
                ],
            )
        ],
    )
    comparison = compare_runs(baseline, candidate, variables=["effective_prompt_hash"])
    assert comparison["verdict"] == "REJECT"


def test_runtime_blocked_proposal_is_not_a_critical_violation() -> None:
    baseline = make_artifact(run_id="baseline")
    candidate = make_artifact(
        run_id="candidate",
        variant=IMPROVED_VARIANT,
        cases=[
            make_trial(
                case_id="case-a",
                repetitions=[
                    make_repetition(
                        case_verdicts={"route": "PASS"},
                        failure_details=[],
                    )
                ],
            )
        ],
    )
    candidate["cases"][0]["repetitions"][0]["blocked_proposals"] = [
        "ESCALATE without a permitted handoff cause"
    ]
    comparison = compare_runs(baseline, candidate, variables=["effective_prompt_hash"])
    assert comparison["verdict"] == "ACCEPT"
    assert comparison["critical_gate"]["new"] == []


def test_incompatible_evidence_is_refused_unless_declared() -> None:
    baseline = make_artifact(run_id="baseline")
    candidate = make_artifact(run_id="candidate", variant=MODEL_VARIANT)
    with pytest.raises(LabError):
        compare_runs(baseline, candidate)
    with pytest.raises(LabError):
        compare_runs(baseline, candidate, variables=["effective_prompt_hash"])
    comparison = compare_runs(baseline, candidate, variables=["model_id"])
    assert comparison["verdict"] == "ACCEPT"


def test_corpus_change_requires_confounder() -> None:
    baseline = make_artifact(run_id="baseline")
    candidate = make_artifact(run_id="candidate", corpus_sha="other-corpus")
    with pytest.raises(LabError):
        compare_runs(baseline, candidate)
    comparison = compare_runs(baseline, candidate, confounders=["corpus_changed"])
    assert comparison["compatibility"]["ok"] is True


def test_infra_pair_requires_owner_decision() -> None:
    baseline = make_artifact(run_id="baseline")
    candidate = make_artifact(
        run_id="candidate",
        variant=IMPROVED_VARIANT,
        cases=[
            make_trial(
                case_id="case-a",
                repetitions=[
                    make_repetition(classification="INFRA", status="infra", case_verdicts={})
                ],
            )
        ],
        infra_count=1,
    )
    comparison = compare_runs(baseline, candidate, variables=["effective_prompt_hash"])
    assert comparison["verdict"] == "NEEDS OWNER DECISION"
    assert len(comparison["evidence"]["infra_pairs"]) == 1


def test_incomplete_pair_requires_owner_decision() -> None:
    baseline = make_artifact(
        run_id="baseline",
        cases=[
            make_trial(case_id="case-a"),
            make_trial(case_id="case-b"),
        ],
    )
    candidate = make_artifact(
        run_id="candidate",
        variant=IMPROVED_VARIANT,
        cases=[make_trial(case_id="case-a")],
    )
    comparison = compare_runs(baseline, candidate, variables=["effective_prompt_hash"])
    assert comparison["verdict"] == "NEEDS OWNER DECISION"
    assert comparison["evidence"]["incomplete"][0]["missing"] == "candidate"


def test_focused_rerun_preserves_original_failure() -> None:
    baseline = make_artifact(
        run_id="baseline",
        cases=[
            make_trial(
                case_id="case-a",
                repetitions=[make_repetition(case_verdicts={"route": "PASS"})],
            )
        ],
    )
    candidate = make_artifact(
        run_id="candidate",
        variant=IMPROVED_VARIANT,
        cases=[
            make_trial(
                case_id="case-a",
                repetitions=[
                    make_repetition(
                        classification="FAIL",
                        case_verdicts={"route": "FAIL"},
                        failure_details=["route expected=CONTINUE observed=ESCALATE"],
                    )
                ],
            )
        ],
    )
    rerun = make_artifact(
        run_id="candidate-rerun",
        variant=IMPROVED_VARIANT,
        cases=[
            make_trial(
                case_id="case-a",
                repetitions=[
                    make_repetition(
                        case_verdicts={"route": "PASS"},
                    )
                ],
            )
        ],
    )
    merged, merges = merge_reruns(candidate, [rerun])
    assert candidate["cases"][0]["repetitions"][0]["classification"] == "FAIL"
    assert merged["cases"][0]["repetitions"][0]["classification"] == "PASS"
    assert merges[0]["replaced"] == ["case-a/case-a/rep1"]
    comparison = compare_runs(
        baseline,
        merged,
        variables=["effective_prompt_hash"],
        candidate_merges=merges,
    )
    assert comparison["evidence"]["candidate_merged_reruns"] == merges
    assert comparison["semantic"]["new_failures"] == []


def test_spoken_quality_review_template_covers_changed_families_and_controls() -> None:
    baseline = make_artifact(
        run_id="baseline",
        cases=[
            make_trial(
                case_id="case-a",
                family="family-a",
                repetitions=[make_repetition(case_verdicts={"route": "PASS"})],
                controls={"positive": [{"case_id": "control-1"}]},
            ),
            make_trial(case_id="control-1", family="family-a"),
        ],
    )
    candidate = make_artifact(
        run_id="candidate",
        variant=IMPROVED_VARIANT,
        cases=[
            make_trial(
                case_id="case-a",
                family="family-a",
                repetitions=[
                    make_repetition(
                        case_verdicts={"route": "FAIL"},
                        failure_details=["route expected=CONTINUE observed=ESCALATE"],
                    )
                ],
                controls={"positive": [{"case_id": "control-1"}]},
            ),
            make_trial(case_id="control-1", family="family-a"),
        ],
    )
    comparison = compare_runs(
        baseline,
        candidate,
        variables=["effective_prompt_hash"],
        target_families=["family-a"],
    )
    review = comparison["spoken_quality_review"]
    assert {row["case_id"] for row in review} == {"case-a", "control-1"}
    for row in review:
        assert set(row["ratings"].values()) == {"NOT EVIDENCED"}


def test_unexplained_prompt_token_growth_needs_owner_decision() -> None:
    baseline = make_artifact(run_id="baseline")
    candidate = make_artifact(run_id="candidate", variant=MODEL_VARIANT)
    baseline["tokens"]["prompt_tokens"]["p50"] = 1000
    candidate["tokens"]["prompt_tokens"]["p50"] = 1300
    comparison = compare_runs(baseline, candidate, variables=["model_id"])
    assert comparison["efficiency"]["unexplained"] is True
    assert comparison["verdict"] == "NEEDS OWNER DECISION"


def test_explained_prompt_token_growth_is_not_flagged() -> None:
    baseline, candidate = _runs_with({"route": "PASS"}, {"route": "PASS"})
    baseline["tokens"]["prompt_tokens"]["p50"] = 1000
    candidate["tokens"]["prompt_tokens"]["p50"] = 1300
    comparison = compare_runs(baseline, candidate, variables=["effective_prompt_hash"])
    assert comparison["efficiency"]["unexplained"] is False
    assert comparison["verdict"] == "ACCEPT"
