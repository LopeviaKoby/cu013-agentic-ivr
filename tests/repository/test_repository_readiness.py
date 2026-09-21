"""Repository readiness gate: single source of truth, no legacy manifests.

Deterministic only: no model, no network, no credentials. It protects the
repository philosophy with objective, stable rules:

- no canonical JSON manifests exist and no active doc links to them;
- the effective baseline is derived from config/code with a runtime
  fingerprint (descriptive names, global model location, MINIMAL,
  required procedure classification, three-pair window, no budget on
  Gemini 3);
- no active imports or references to discarded providers;
- no historic short labels in active code or canonical docs (experiments
  and ignored outputs are explicitly excluded);
- local links in canonical artifacts are not broken and do not point to
  ignored outputs or deleted files as normative sources;
- the effective Firestore version matches the adopted lock.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()

DELETED_MANIFESTS = [
    ROOT / "evals/conversation/accepted-baseline.json",
    ROOT / "evals/conversation/baselines/21896d12e04da173eda5b0fb4949ac5841812fdd.json",
    ROOT / "evals/conversation/selection-evidence/active-conversation-baseline.json",
    ROOT / "evals/conversation/selection-evidence/checksums.json",
    ROOT / "evals/conversation/selection-evidence/selection-scorecard-reconstruction.json",
]

MANIFEST_LINK_MARKERS = [
    "accepted-baseline.json",
    "selection-evidence/",
    "selection-scorecard",
    "checksums.json",
    "evals/conversation/baselines/",
]

# Historic short labels that must not appear as standalone uppercase tokens
# in active code or canonical docs. Experiments and ignored outputs are
# excluded from this rule. Matching is case-sensitive whole-word so frozen
# lowercase run-artifact values do not trip the gate; active comments, docs
# and identifiers use descriptive names.
FORBIDDEN_TOKENS_PATTERN = re.compile(r"\b(S4|C1|N3|G35|G31|S5A|S5B)\b")

# Early experiment variants and prompt-policy codes were removed from active
# code, harness and docs in favour of self-sufficient values. This pattern
# blocks the old lowercase aliases as whole words, plus a bare "p" only when
# it clearly appears as a variant/policy value (quoted or next to the word
# variant/arm), so ordinary identifiers and prose are not false positives.
FORBIDDEN_EXPERIMENT_ALIASES_PATTERN = re.compile(
    r"\b(b0|c1|s0|s1|s2|s3)\b"
    r"|(?:\bvariant\b|\bmemory[-_]variant\b|\bprompt[-_]policy\b|\barm\b)[^\n]{0,24}\bp\b",
    re.IGNORECASE,
)

EXCLUDED_DIR_NAMES = {
    ".venv",
    ".git",
    ".codegraph",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "htmlcov",
    "dist",
    "build",
}

# Directories excluded from the historic-label and manifest-link rules.
HISTORY_EXCLUDED = {"docs/experiments", "evals/results"}


def _is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDED_DIR_NAMES:
        return True
    try:
        rel = path.relative_to(ROOT).as_posix()
    except ValueError:
        return True
    for prefix in HISTORY_EXCLUDED:
        if rel == prefix or rel.startswith(prefix + "/"):
            return True
    # Owner-supplied IOP PDFs are local and ignored by design; their
    # versioned manifest is canonical, the binaries are not scanned here.
    if rel == "docs/iop" or rel.startswith("docs/iop/"):
        return True
    return False


def _active_markdown_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*.md"):
        if path.resolve() == SELF:
            continue
        if _is_excluded(path):
            continue
        files.append(path)
    return sorted(files)


def _active_python_files() -> list[Path]:
    files: list[Path] = []
    for base in (ROOT / "app", ROOT / "evals", ROOT / "tests", ROOT / "ops"):
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path.resolve() == SELF:
                continue
            if _is_excluded(path):
                continue
            # Ignored run outputs never live under these bases, but keep the
            # guard explicit for future moves.
            files.append(path)
    # Canonical config is checked separately for baseline identity.
    return sorted(files)


def test_no_canonical_manifests_exist() -> None:
    for path in DELETED_MANIFESTS:
        assert not path.exists(), f"canonical manifest must not exist: {path}"


def test_active_docs_do_not_link_to_deleted_manifests() -> None:
    offenders: list[str] = []
    for path in _active_markdown_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for marker in MANIFEST_LINK_MARKERS:
            if marker in text:
                offenders.append(f"{path.relative_to(ROOT)}: {marker}")
    assert not offenders, "active docs link to deleted manifests: " + "; ".join(offenders)


def test_effective_baseline_matches_accepted_profile() -> None:
    from app.conversation.gemini import (
        ACTIVE_CONVERSATION_MODEL,
        ACTIVE_MODEL_LOCATION,
        ACTIVE_THINKING_LEVEL,
        active_conversation_baseline,
        response_schema_for,
    )
    from app.session.memory import ACTIVE_RECENT_TURN_PAIRS, MEMORY_WINDOW_N_DEFAULT

    baseline = active_conversation_baseline()
    assert baseline.provider == "vertex_ai"
    assert baseline.model == ACTIVE_CONVERSATION_MODEL == "gemini-3.5-flash-lite"
    assert baseline.location == ACTIVE_MODEL_LOCATION == "global"
    assert baseline.thinking_level == ACTIVE_THINKING_LEVEL == "MINIMAL"
    assert baseline.strict_procedure_observation is True
    assert ACTIVE_RECENT_TURN_PAIRS == 3
    assert MEMORY_WINDOW_N_DEFAULT == 3
    schema = response_schema_for(baseline)
    assert isinstance(schema, dict)
    assert "procedure_observation" in schema["required"]


def test_gemini3_sends_level_without_budget() -> None:
    from google.genai.types import ThinkingLevel

    from app.conversation.gemini import GeminiTurnModel, active_conversation_baseline
    from tests.conversation.test_gemini_model import FakeGenaiClient

    client = FakeGenaiClient()
    config = GeminiTurnModel(client, active_conversation_baseline())._config()  # type: ignore[arg-type]
    assert config.thinking_config is not None
    assert config.thinking_config.thinking_level == ThinkingLevel.MINIMAL
    assert config.thinking_config.thinking_budget is None


def test_no_active_references_to_discarded_providers() -> None:
    offenders: list[str] = []
    for path in _active_python_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        lowered = text.lower()
        if "openrouter" in lowered:
            offenders.append(str(path.relative_to(ROOT)))
    # Canonical docs must not present a discarded provider as active either.
    for path in _active_markdown_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        # Historical ADR notes may name a discarded provider once as
        # non-productive context; the active specs, README, CONTEXT,
        # CHANGELOG, testing standard, runbooks and skills must not.
        if (
            path.relative_to(ROOT).as_posix()
            == "docs/decisions/0011-select-active-conversation-profile.md"
        ):
            continue
        if "openrouter" in text.lower():
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, "active references to discarded providers: " + ", ".join(offenders)


def test_no_historic_short_labels_in_active_code_or_docs() -> None:
    offenders: list[str] = []
    for path in _active_python_files() + _active_markdown_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in FORBIDDEN_TOKENS_PATTERN.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line_no}:{match.group(0)}")
    assert not offenders, "historic short labels in active scope: " + "; ".join(offenders[:20])


def test_no_experiment_aliases_in_active_code_or_docs() -> None:
    offenders: list[str] = []
    for path in _active_python_files() + _active_markdown_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in FORBIDDEN_EXPERIMENT_ALIASES_PATTERN.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line_no}:{match.group(0)!r}")
    assert not offenders, "experiment aliases in active scope: " + "; ".join(offenders[:20])


_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def test_canonical_local_links_are_not_broken() -> None:
    broken: list[str] = []
    for doc in _active_markdown_files():
        try:
            text = doc.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in _LINK_PATTERN.finditer(text):
            target = match.group(2).strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            # Strip anchor and title.
            target_path = target.split("#", 1)[0].strip().strip("<>").strip("\"'")
            if not target_path or target_path.startswith(("http://", "https://", "mailto:", "#")):
                continue
            candidate = (doc.parent / target_path).resolve()
            try:
                candidate.relative_to(ROOT)
                inside = True
            except ValueError:
                inside = False
            if inside and not candidate.exists():
                broken.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert not broken, "broken local links: " + "; ".join(broken[:20])


def test_specs_do_not_point_to_ignored_outputs_as_normative() -> None:
    offenders: list[str] = []
    scopes = [ROOT / "docs/specs", ROOT / "docs/decisions", ROOT / "docs/engineering"]
    for scope in scopes:
        if not scope.exists():
            continue
        for doc in scope.rglob("*.md"):
            if _is_excluded(doc):
                continue
            try:
                text = doc.read_text(encoding="utf-8")
            except OSError:
                continue
            for match in _LINK_PATTERN.finditer(text):
                target = match.group(2).strip().split("#", 1)[0].strip()
                if "evals/results/" in target:
                    offenders.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert not offenders, "normative links to ignored outputs: " + "; ".join(offenders)


def test_effective_firestore_matches_lock() -> None:
    import importlib.metadata

    lock_text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    pinned: str | None = None
    for line in lock_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("google-cloud-firestore=="):
            pinned = stripped.split("==", 1)[1].strip()
            break
    assert pinned, "google-cloud-firestore pin missing in requirements.lock"
    effective = importlib.metadata.version("google-cloud-firestore")
    assert effective == pinned, f"effective Firestore {effective} != lock {pinned}"
