"""Active conversational baseline tests: exact reproducible profile.

No Vertex AI, network or credentials are involved. These tests pin the
accepted baseline in descriptive language: Gemini 3.5 Flash-Lite on
Vertex AI, model location global, reasoning level MINIMAL, structured
procedure classification required, recent memory of three completed
pairs in the synthetic lane, one model call per transcript turn and zero
calls on polling without new speech. The baseline is derived from
configuration and code; the harness calculates its fingerprint in
runtime. No canonical JSON manifest exists.
"""

from pathlib import Path

from app.conversation.gemini import (
    ACTIVE_ATTEMPTS,
    ACTIVE_CONVERSATION_MODEL,
    ACTIVE_MODEL_LOCATION,
    ACTIVE_THINKING_LEVEL,
    ACTIVE_TIMEOUT_MS,
    active_conversation_baseline,
    contents_for,
    response_schema_for,
    system_instructions_for,
)
from app.conversation.prompts import SYSTEM_INSTRUCTIONS


def test_active_baseline_identity_is_single_and_explicit() -> None:
    baseline = active_conversation_baseline()
    assert baseline.provider == "vertex_ai"
    assert baseline.model == ACTIVE_CONVERSATION_MODEL == "gemini-3.5-flash-lite"
    assert baseline.location == ACTIVE_MODEL_LOCATION == "global"
    assert baseline.api_version == "v1"
    assert baseline.thinking_level == ACTIVE_THINKING_LEVEL == "MINIMAL"
    assert baseline.strict_procedure_observation is True
    assert baseline.timeout_ms == ACTIVE_TIMEOUT_MS == 30000
    assert baseline.attempts == ACTIVE_ATTEMPTS == 1


def test_active_schema_requires_structured_procedure_classification() -> None:
    schema = response_schema_for(active_conversation_baseline())
    assert isinstance(schema, dict)
    assert "procedure_observation" in schema["required"]
    assert "default" not in schema["properties"]["procedure_observation"]
    order = list(schema["properties"])
    assert order.index("procedure_observation") < order.index("goal")


def test_active_prompt_is_single_baseline_text() -> None:
    baseline = active_conversation_baseline()
    assert system_instructions_for(baseline) == SYSTEM_INSTRUCTIONS
    contents = contents_for(state_block="objetivo: ninguno", transcript="hola")
    assert "objetivo: ninguno" in contents


def test_gemini3_request_sends_level_without_budget() -> None:
    from google.genai.types import ThinkingLevel

    from app.conversation.gemini import GeminiTurnModel
    from tests.conversation.test_gemini_model import FakeGenaiClient

    client = FakeGenaiClient()
    config = GeminiTurnModel(client, active_conversation_baseline())._config()  # type: ignore[arg-type]
    assert config.thinking_config is not None
    assert config.thinking_config.thinking_level == ThinkingLevel.MINIMAL
    assert config.thinking_config.thinking_budget is None


def test_no_benchmark_router_in_active_composition() -> None:
    import app.main as main_module

    assert not hasattr(main_module, "benchmark_router")
    assert not hasattr(main_module, "BENCHMARK_ENV")


def test_no_canonical_baseline_manifests_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    deleted = [
        root / "evals/conversation/accepted-baseline.json",
        root / "evals/conversation/baselines/21896d12e04da173eda5b0fb4949ac5841812fdd.json",
        root / "evals/conversation/selection-evidence/active-conversation-baseline.json",
        root / "evals/conversation/selection-evidence/checksums.json",
        root / "evals/conversation/selection-evidence/selection-scorecard-reconstruction.json",
    ]
    for path in deleted:
        assert not path.exists(), f"canonical manifest must not exist: {path}"


def test_variant_fingerprint_derived_from_effective_sources() -> None:
    from evals.conversation_eval import build_variant_identity
    from evals.conversation_lab import hash_text

    baseline = active_conversation_baseline()
    identity = build_variant_identity(baseline)
    assert identity["provider"] == "vertex_ai"
    assert identity["model_id"] == "gemini-3.5-flash-lite"
    assert identity["model_location"] == "global"
    assert identity["thinking_level"] == "MINIMAL"
    assert identity["thinking_budget"] is None
    assert identity["strict_procedure_observation"] is True
    assert identity["effective_prompt_hash"] == hash_text(SYSTEM_INSTRUCTIONS)
    assert identity["memory_n"] == 3


def test_config_model_location_is_global_not_infrastructure() -> None:
    import yaml

    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert config["vertex"]["location"] == "global"
    assert config["cloud_run"]["region"] == "us-east1"
    assert config["gcp"]["region"] == "us-east1"


def test_active_memory_window_is_three_pairs() -> None:
    from app.session.memory import (
        ACTIVE_RECENT_TURN_PAIRS,
        MEMORY_WINDOW_N_DEFAULT,
    )

    assert ACTIVE_RECENT_TURN_PAIRS == 3
    assert MEMORY_WINDOW_N_DEFAULT == 3
