"""Startup loader for the versioned templates and private runtime protocols.

The bundle is built exactly once during ``build_app``, before the engine and
model path exist, and stays in RAM for the process lifetime: there is no hot
reload and the turn path performs zero file reads. A missing, oversized,
non-UTF-8, NUL-carrying, empty or mislabeled module fails startup closed; the
application never serves a partial prompt.

``core.md``, ``catalog.md`` and ``few_shot.md`` travel inside the package; the
private ``RESET_PASSWORD.runtime.md`` and ``UNLOCK_ACCOUNT.runtime.md``
protocols are owner-supplied, never versioned and mounted from Secret Manager
in DEV. For an action with guided runtime steps, the loader validates that the
protocol's level-3 sections match the guided-step count and precomposes one
projected instruction per step.
"""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path
from typing import Final

from app.conversation.prompt_renderer import (
    CATALOG_MODULE_NAME,
    CORE_MODULE_NAME,
    PromptBundle,
    PromptModule,
    build_prompt_bundle,
    hash_prompt_text,
)
from app.session.actions import Action
from app.session.memory import GUIDED_STEPS

MAX_PROMPT_MODULE_BYTES: Final = 64 * 1024
PROTOCOL_DIR_ENV: Final = "CU013_PROTOCOL_DIR"
DEFAULT_PROTOCOL_DIR: Final = Path("/var/run/secrets/cu013/protocols")
TEMPLATE_PACKAGE: Final = "app.conversation"
TEMPLATE_DIRECTORY: Final = "prompt_templates"
PROTOCOL_FILENAMES: Final[tuple[tuple[Action, str], ...]] = (
    (Action.RESET_PASSWORD, "RESET_PASSWORD.runtime.md"),
    (Action.UNLOCK_ACCOUNT, "UNLOCK_ACCOUNT.runtime.md"),
)
# Cloud Run forbids two secret volumes in one directory, so the deploy mounts
# each protocol in its own directory and points these variables at the exact
# files; the directory+filename convention remains the local default.
PROTOCOL_FILE_ENV: Final[dict[Action, str]] = {
    Action.RESET_PASSWORD: "CU013_PROTOCOL_RESET_FILE",
    Action.UNLOCK_ACCOUNT: "CU013_PROTOCOL_UNLOCK_FILE",
}
# Guided runtime steps per action. The protocol's level-3 sections must follow
# this order so the projected window stays deterministic; a cardinality
# mismatch fails startup instead of composing the wrong section.
GUIDED_STEPS_BY_ACTION: Final[tuple[tuple[Action, tuple[str, ...]], ...]] = (
    (Action.RESET_PASSWORD, GUIDED_STEPS),
)
# ``few_shot_min.md`` is the evidence-based minimum selected by the ablation:
# the cancellation example was dropped because the re-request property holds
# without examples. The discarded ablation variants live only on the
# experimental branch.
FEW_SHOT_MINIMAL_NAME: Final = "few_shot_min.md"


class PromptBundleError(RuntimeError):
    """The prompt bundle cannot be built; startup must fail closed."""


def normalize_prompt_text(text: str) -> str:
    """Normalize line endings only; never trims or rewrites content."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def validate_prompt_module(name: str, raw: bytes) -> PromptModule:
    """Validate one module's bytes and produce its normalized immutable form."""
    if len(raw) > MAX_PROMPT_MODULE_BYTES:
        raise PromptBundleError(f"prompt module {name} exceeds the 64 KiB cap")
    if b"\x00" in raw:
        raise PromptBundleError(f"prompt module {name} contains a NUL byte")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PromptBundleError(f"prompt module {name} is not valid UTF-8") from exc
    text = normalize_prompt_text(decoded)
    if not text.strip():
        raise PromptBundleError(f"prompt module {name} is empty")
    return PromptModule(name=name, text=text, sha256=hash_prompt_text(text))


def protocol_header_for(action: Action) -> str:
    return f"# {action.value}"


def validate_protocol_identity(action: Action, module: PromptModule) -> None:
    """Verify the expected capability from the protocol's real format.

    Every runtime protocol declares its capability as ``# <ACTION>`` on the
    first non-empty line; a mismatch fails startup instead of composing the
    wrong procedure for a goal.
    """
    first_line = next(
        (line.strip() for line in module.text.splitlines() if line.strip()),
        "",
    )
    expected = protocol_header_for(action)
    if first_line != expected:
        raise PromptBundleError(
            f"protocol {module.name} does not declare its capability as {expected!r}"
        )


def read_template_module(name: str) -> PromptModule:
    """Read one versioned template from the installed package resources."""
    template = resources.files(TEMPLATE_PACKAGE).joinpath(TEMPLATE_DIRECTORY, name)
    try:
        raw = template.read_bytes()
    except OSError as exc:
        raise PromptBundleError(f"missing packaged prompt template {name}") from exc
    return validate_prompt_module(name, raw)


def read_protocol_module(path: Path, action: Action) -> PromptModule:
    """Read one private protocol and validate size, encoding and identity."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PromptBundleError(f"missing private runtime protocol {path.name}") from exc
    module = validate_prompt_module(path.name, raw)
    validate_protocol_identity(action, module)
    return module


def protocol_directory(protocol_dir: Path | None = None) -> Path:
    if protocol_dir is not None:
        return protocol_dir
    configured = os.environ.get(PROTOCOL_DIR_ENV)
    return Path(configured) if configured else DEFAULT_PROTOCOL_DIR


HARNESS_TEMPLATES: Final[dict[str, dict[str, str | None]]] = {
    # Spanish is the active product harness; English exists only for the
    # controlled A/B experiment. Protocols, state values and the schema are
    # never translated.
    "es": {
        "core": CORE_MODULE_NAME,
        "catalog": CATALOG_MODULE_NAME,
        "few_shot": FEW_SHOT_MINIMAL_NAME,
    },
    "en": {
        "core": "core_en.md",
        "catalog": "catalog_en.md",
        "few_shot": "few_shot_en.md",
    },
}


def load_prompt_bundle(
    *,
    protocol_dir: Path | None = None,
    few_shot_name: str | None = FEW_SHOT_MINIMAL_NAME,
    core_name: str = CORE_MODULE_NAME,
    catalog_name: str = CATALOG_MODULE_NAME,
) -> PromptBundle:
    """Build the immutable prompt bundle once; any missing piece fails closed.

    ``few_shot_name=None`` composes the bundle without decision examples;
    ``core_name``/``catalog_name`` select the harness language templates.
    """
    directory = protocol_directory(protocol_dir)
    protocols = tuple(
        (
            action,
            read_protocol_module(
                Path(os.environ[PROTOCOL_FILE_ENV[action]])
                if os.environ.get(PROTOCOL_FILE_ENV[action])
                else directory / filename,
                action,
            ),
        )
        for action, filename in PROTOCOL_FILENAMES
    )
    core = read_template_module(core_name)
    catalog = read_template_module(catalog_name)
    few_shot = read_template_module(few_shot_name) if few_shot_name is not None else None
    return build_prompt_bundle(
        core, catalog, few_shot, protocols, guided_steps=GUIDED_STEPS_BY_ACTION
    )
