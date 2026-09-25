"""DEV environment migration accreditation: defaults now point at TIVIT.

Deterministic only: it reads the versioned configuration and the ops scripts
and pins the migrated current state (project, service, repository, secret,
region, model location, tiers, runtime SA, no impersonation, closed branch
guard). Historical experiment records are intentionally not asserted here.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "ops" / "gcp"


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def test_config_points_at_the_tivit_dev_environment() -> None:
    config = load_config()
    assert config["gcp"]["project_id"] == "tivit-cu013-prd"
    assert config["gcp"]["region"] == "us-east1"
    assert config["artifact_registry"]["repository"] == "cu013-containers-dev"
    assert config["artifact_registry"]["location"] == "us-east1"
    assert config["cloud_run"]["service"] == "cu013-runtime-dev"
    assert config["cloud_run"]["region"] == "us-east1"
    assert config["security"]["api_key_secret"] == "cu013-api-key-dev"
    assert config["firestore"]["database"] == "(default)"


def test_model_location_and_tiers_are_unchanged() -> None:
    config = load_config()
    assert config["vertex"]["location"] == "global"
    cloud_run = config["cloud_run"]
    assert cloud_run["cpu"] == 1
    assert cloud_run["memory"] == "512Mi"
    assert cloud_run["concurrency"] == 1
    assert cloud_run["max_instances"] == 1
    assert cloud_run["min_instances"] == 0
    assert cloud_run["benchmark_min_instances"] == 1
    assert cloud_run["billing"] == "request"


def test_vertex_fallback_project_is_the_tivit_dev_project(
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    from app.conversation.gemini import GeminiBaseline, active_conversation_baseline

    monkeypatch.delenv("CU013_VERTEX_PROJECT", raising=False)
    assert GeminiBaseline.from_env().project == "tivit-cu013-prd"
    assert active_conversation_baseline().project == "tivit-cu013-prd"


def test_ops_scripts_never_impersonate_and_target_the_runtime_sa() -> None:
    offenders: list[str] = []
    for path in sorted(OPS.glob("*.ps1")):
        text = path.read_text(encoding="utf-8")
        if "impersonate-service-account" in text:
            offenders.append(f"{path.name}: impersonation")
        if "cu013-xcally-agentic" in text:
            offenders.append(f"{path.name}: legacy project")
    assert not offenders, "; ".join(offenders)
    deploy = (OPS / "deploy-dev-benchmark.ps1").read_text(encoding="utf-8")
    assert "cu013-cloud-run-sa@tivit-cu013-prd.iam.gserviceaccount.com" in deploy
    assert "tivit-cu013-prd" in deploy


def test_deploy_branch_guard_is_a_closed_allow_list() -> None:
    deploy = (OPS / "deploy-dev-benchmark.ps1").read_text(encoding="utf-8")
    assert "$AllowedBranches" in deploy
    assert "-notcontains $branch" in deploy
    assert '-ne "dev"' not in deploy


def test_bootstrap_never_creates_service_accounts() -> None:
    bootstrap = (OPS / "bootstrap-dev.ps1").read_text(encoding="utf-8")
    assert "service-accounts create" not in bootstrap
    assert "cu013-cloud-run-sa@tivit-cu013-prd.iam.gserviceaccount.com" in bootstrap
    assert "secretmanager.secretAccessor" in bootstrap
