"""Deterministic loader tests: validation, hashing and fail-closed startup.

No private owner protocol is used here: every file is synthetic placeholder
text written to a temporary directory. No model, network or credentials are
involved.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from app.conversation.prompt_loader import (
    MAX_PROMPT_MODULE_BYTES,
    PROTOCOL_FILENAMES,
    PromptBundleError,
    load_prompt_bundle,
    normalize_prompt_text,
    validate_prompt_module,
)
from app.conversation.prompt_renderer import hash_prompt_text
from app.session.actions import Action
from tests.conversation.prompt_fixtures import (
    SYNTHETIC_RESET_BODY,
    write_synthetic_protocols,
)

RESET_FILENAME = PROTOCOL_FILENAMES[0][1]
UNLOCK_FILENAME = PROTOCOL_FILENAMES[1][1]


def valid_reset_protocol() -> bytes:
    return b"# RESET_PASSWORD\n\nProcedimiento sintetico.\n"


def test_load_prompt_bundle_reads_packaged_templates_and_private_protocols(
    tmp_path: Path,
) -> None:
    bundle = load_prompt_bundle(protocol_dir=write_synthetic_protocols(tmp_path))
    assert "# Rol" in bundle.core.text
    assert "Capacidades soportadas" in bundle.catalog.text
    assert len(bundle.protocols) == 2
    base = bundle.system_instructions(None)
    assert base.startswith(bundle.core.text)
    assert bundle.catalog.text in base


def test_missing_protocol_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(PromptBundleError, match="missing private runtime protocol"):
        load_prompt_bundle(protocol_dir=tmp_path)


def test_empty_protocol_fails_closed(tmp_path: Path) -> None:
    write_synthetic_protocols(tmp_path)
    (tmp_path / RESET_FILENAME).write_text("   \n\n", encoding="utf-8")
    with pytest.raises(PromptBundleError, match="empty"):
        load_prompt_bundle(protocol_dir=tmp_path)


def test_nul_byte_fails_closed(tmp_path: Path) -> None:
    write_synthetic_protocols(tmp_path)
    (tmp_path / RESET_FILENAME).write_bytes(b"# RESET_PASSWORD\n\nbad\x00value\n")
    with pytest.raises(PromptBundleError, match="NUL"):
        load_prompt_bundle(protocol_dir=tmp_path)


def test_oversize_protocol_fails_closed(tmp_path: Path) -> None:
    write_synthetic_protocols(tmp_path)
    oversize = b"# RESET_PASSWORD\n" + b"a" * MAX_PROMPT_MODULE_BYTES
    (tmp_path / RESET_FILENAME).write_bytes(oversize)
    with pytest.raises(PromptBundleError, match="64 KiB"):
        load_prompt_bundle(protocol_dir=tmp_path)


def test_invalid_utf8_fails_closed(tmp_path: Path) -> None:
    write_synthetic_protocols(tmp_path)
    (tmp_path / RESET_FILENAME).write_bytes(b"# RESET_PASSWORD\n\n\xff\xfe\n")
    with pytest.raises(PromptBundleError, match="UTF-8"):
        load_prompt_bundle(protocol_dir=tmp_path)


def test_mislabeled_protocol_fails_closed(tmp_path: Path) -> None:
    write_synthetic_protocols(tmp_path)
    (tmp_path / RESET_FILENAME).write_bytes(b"# UNLOCK_ACCOUNT\n\nwrong capability\n")
    with pytest.raises(PromptBundleError, match="capability"):
        load_prompt_bundle(protocol_dir=tmp_path)


def test_mislabeled_protocol_error_never_echoes_content(tmp_path: Path) -> None:
    canary = "PRIVATE-CANARY-0000"
    write_synthetic_protocols(tmp_path)
    (tmp_path / UNLOCK_FILENAME).write_text(f"# WRONG\n\n{canary}\n", encoding="utf-8")
    with pytest.raises(PromptBundleError) as excinfo:
        load_prompt_bundle(protocol_dir=tmp_path)
    assert canary not in str(excinfo.value)


def test_newline_normalization_is_stable_and_hashed() -> None:
    lf = validate_prompt_module("synthetic.md", b"# RESET_PASSWORD\n\nPaso\n")
    crlf = validate_prompt_module("synthetic.md", b"# RESET_PASSWORD\r\n\r\nPaso\r\n")
    cr = validate_prompt_module("synthetic.md", b"# RESET_PASSWORD\r\rPaso\r")
    assert lf.text == "# RESET_PASSWORD\n\nPaso\n"
    assert crlf.text == lf.text
    assert cr.text == "# RESET_PASSWORD\n\nPaso\n"
    assert crlf.sha256 == lf.sha256 == hash_prompt_text(lf.text)
    assert normalize_prompt_text("a\r\nb\rc\n") == "a\nb\nc\n"


def test_bundle_hashes_are_stable_across_loads(tmp_path: Path) -> None:
    first = load_prompt_bundle(protocol_dir=write_synthetic_protocols(tmp_path / "one"))
    second = load_prompt_bundle(protocol_dir=write_synthetic_protocols(tmp_path / "two"))
    assert first.fingerprint == second.fingerprint
    assert first.instruction_hashes() == second.instruction_hashes()
    assert first.module_hashes() == second.module_hashes()


def test_bundle_is_immutable(tmp_path: Path) -> None:
    bundle = load_prompt_bundle(protocol_dir=write_synthetic_protocols(tmp_path))
    with pytest.raises(dataclasses.FrozenInstanceError):
        bundle.fingerprint = "changed"  # type: ignore[misc]
    assert isinstance(bundle.protocols, tuple)
    assert isinstance(bundle.instructions, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        bundle.core.text = "changed"  # type: ignore[misc]


def test_files_are_not_read_after_startup(tmp_path: Path) -> None:
    directory = write_synthetic_protocols(tmp_path)
    bundle = load_prompt_bundle(protocol_dir=directory)
    for path in sorted(directory.iterdir()):
        path.unlink()
    assert bundle.system_instructions(None)
    assert bundle.system_instructions(None) == bundle.instruction("base").text


def test_few_shot_ablation_variants_load_or_omit_the_module(tmp_path: Path) -> None:
    from app.conversation.prompt_loader import FEW_SHOT_TEMPLATES, few_shot_name_for

    assert few_shot_name_for("f4") == "few_shot.md"
    assert few_shot_name_for("f2") == "few_shot_f2.md"
    assert few_shot_name_for("f1") == "few_shot_f1.md"
    assert few_shot_name_for("f0") is None
    assert sorted(FEW_SHOT_TEMPLATES) == ["f0", "f1", "f2", "f4"]
    directory = write_synthetic_protocols(tmp_path)
    for variant in ("f4", "f2", "f1"):
        bundle = load_prompt_bundle(
            protocol_dir=directory, few_shot_name=few_shot_name_for(variant)
        )
        assert bundle.few_shot is not None
        assert bundle.few_shot.name == few_shot_name_for(variant)
    bare = load_prompt_bundle(protocol_dir=directory, few_shot_name=None)
    assert bare.few_shot is None


def test_few_shot_content_ablation_drops_exactly_one_example(tmp_path: Path) -> None:
    from app.conversation.prompt_loader import drop_example

    directory = write_synthetic_protocols(tmp_path)
    base = load_prompt_bundle(protocol_dir=directory, few_shot_name="few_shot.md")
    assert base.few_shot is not None
    text = base.few_shot.text
    assert text.count("<ejemplo>") >= 1
    variants = set()
    for index in range(1, text.count("<ejemplo>") + 1):
        dropped = load_prompt_bundle(
            protocol_dir=directory, few_shot_name="few_shot.md", few_shot_drop=index
        )
        assert dropped.few_shot is not None
        assert dropped.few_shot.text.count("<ejemplo>") == text.count("<ejemplo>") - 1
        assert dropped.few_shot.sha256 != base.few_shot.sha256
        variants.add(dropped.few_shot.sha256)
    assert len(variants) == text.count("<ejemplo>")
    with pytest.raises(PromptBundleError, match="drop index"):
        drop_example(text, 99)


def test_english_harness_templates_load_without_touching_protocols(
    tmp_path: Path,
) -> None:
    from app.conversation.prompt_loader import HARNESS_TEMPLATES

    directory = write_synthetic_protocols(tmp_path)
    templates = HARNESS_TEMPLATES["en"]
    bundle = load_prompt_bundle(
        protocol_dir=directory,
        core_name=templates["core"] or "core_en.md",
        catalog_name=templates["catalog"] or "catalog_en.md",
        few_shot_name=templates["few_shot"],
    )
    assert bundle.core.name == "core_en.md"
    assert bundle.catalog.name == "catalog_en.md"
    assert bundle.few_shot is not None and bundle.few_shot.name == "few_shot_en.md"
    base = bundle.system_instructions(None)
    assert "Always answer in Spanish" in base
    # Protocols keep their original language and content.
    reset = bundle.system_instructions(_goal_for("RESET_PASSWORD"))
    assert SYNTHETIC_RESET_BODY in reset
    assert "RESET_PASSWORD" in reset


def _goal_for(action: str):  # type: ignore[no-untyped-def]
    from app.session.record import ConversationGoal

    return ConversationGoal(action=Action(action), revision=1)


def test_explicit_protocol_file_paths_override_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.conversation.prompt_loader import PROTOCOL_FILE_ENV
    from tests.conversation.prompt_fixtures import PROTOCOL_BODIES

    write_synthetic_protocols(tmp_path / "bundle")
    reset_dir = tmp_path / "reset"
    unlock_dir = tmp_path / "unlock"
    reset_dir.mkdir()
    unlock_dir.mkdir()
    (reset_dir / "RESET_PASSWORD.runtime.md").write_text(
        PROTOCOL_BODIES["RESET_PASSWORD.runtime.md"], encoding="utf-8"
    )
    (unlock_dir / "UNLOCK_ACCOUNT.runtime.md").write_text(
        PROTOCOL_BODIES["UNLOCK_ACCOUNT.runtime.md"], encoding="utf-8"
    )
    monkeypatch.setenv(
        PROTOCOL_FILE_ENV[Action.RESET_PASSWORD], str(reset_dir / "RESET_PASSWORD.runtime.md")
    )
    monkeypatch.setenv(
        PROTOCOL_FILE_ENV[Action.UNLOCK_ACCOUNT], str(unlock_dir / "UNLOCK_ACCOUNT.runtime.md")
    )
    bundle = load_prompt_bundle(protocol_dir=tmp_path / "bundle")
    assert SYNTHETIC_RESET_BODY in bundle.system_instructions(_goal_for("RESET_PASSWORD"))
    monkeypatch.delenv(PROTOCOL_FILE_ENV[Action.RESET_PASSWORD])
    monkeypatch.delenv(PROTOCOL_FILE_ENV[Action.UNLOCK_ACCOUNT])


def test_guided_step_cardinality_mismatch_fails_startup(tmp_path: Path) -> None:
    """Projection never guesses: a structure mismatch fails closed."""
    write_synthetic_protocols(tmp_path)
    (tmp_path / RESET_FILENAME).write_text(
        "# RESET_PASSWORD\n\nProcedimiento.\n\n### Portal uno\n\nPaso A.\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="guided sections"):
        load_prompt_bundle(protocol_dir=tmp_path)


def test_missing_protocol_identity_header_is_rejected() -> None:
    module = validate_prompt_module("synthetic.md", b"Procedimiento sin cabecera\n")
    action = PROTOCOL_FILENAMES[0][0]
    from app.conversation.prompt_loader import validate_protocol_identity

    with pytest.raises(PromptBundleError, match="capability"):
        validate_protocol_identity(action, module)
