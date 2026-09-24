"""Synthetic prompt modules for deterministic tests.

Private owner protocols never appear here: every synthetic protocol carries
placeholder text and the required ``# <ACTION>`` capability header, so loader,
renderer and adapter tests exercise the real validation and composition paths
without depending on private inputs.
"""

from __future__ import annotations

from pathlib import Path

from app.conversation.prompt_loader import (
    PROTOCOL_FILENAMES,
    load_prompt_bundle,
    validate_prompt_module,
)
from app.conversation.prompt_renderer import PromptBundle, PromptModule, build_prompt_bundle

SYNTHETIC_CORE = "# Rol\n\nReglas generales sintéticas de prueba."
SYNTHETIC_CATALOG = "# Capacidades\n\n- RESET_PASSWORD\n- UNLOCK_ACCOUNT"
SYNTHETIC_RESET_BODY = "Procedimiento sintético de reset."
SYNTHETIC_UNLOCK_BODY = "Procedimiento sintético de desbloqueo."

PROTOCOL_BODIES: dict[str, str] = {
    "RESET_PASSWORD.runtime.md": f"# RESET_PASSWORD\n\n{SYNTHETIC_RESET_BODY}",
    "UNLOCK_ACCOUNT.runtime.md": f"# UNLOCK_ACCOUNT\n\n{SYNTHETIC_UNLOCK_BODY}",
}


def make_module(name: str, text: str) -> PromptModule:
    return validate_prompt_module(name, text.encode("utf-8"))


def make_bundle() -> PromptBundle:
    """A fully synthetic in-memory bundle; no file I/O involved."""
    protocols = tuple(
        (action, make_module(filename, PROTOCOL_BODIES[filename]))
        for action, filename in PROTOCOL_FILENAMES
    )
    return build_prompt_bundle(
        make_module("core.md", SYNTHETIC_CORE),
        make_module("catalog.md", SYNTHETIC_CATALOG),
        protocols,
    )


def write_synthetic_protocols(directory: Path) -> Path:
    """Write the two synthetic protocol files with valid capability headers."""
    directory.mkdir(parents=True, exist_ok=True)
    for filename, body in PROTOCOL_BODIES.items():
        (directory / filename).write_text(body, encoding="utf-8")
    return directory


def synthetic_protocol_bundle(directory: Path) -> PromptBundle:
    """Real versioned templates plus synthetic private protocols."""
    return load_prompt_bundle(protocol_dir=write_synthetic_protocols(directory))
