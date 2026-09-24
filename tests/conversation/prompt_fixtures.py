"""Synthetic prompt modules for deterministic tests.

Private owner protocols never appear here: every synthetic protocol carries
placeholder text and the required ``# <ACTION>`` capability header, so loader,
renderer and adapter tests exercise the real validation and composition paths
without depending on private inputs. The synthetic RESET protocol mirrors the
level-3 structure the projection contract requires.
"""

from __future__ import annotations

from pathlib import Path

from app.conversation.prompt_loader import (
    PROTOCOL_FILENAMES,
    load_prompt_bundle,
    validate_prompt_module,
)
from app.conversation.prompt_renderer import PromptBundle, PromptModule, build_prompt_bundle
from app.session.actions import Action
from app.session.memory import GUIDED_STEPS

SYNTHETIC_CORE = "# Rol\n\nReglas generales sintéticas de prueba."
SYNTHETIC_CATALOG = "# Capacidades\n\n- RESET_PASSWORD\n- UNLOCK_ACCOUNT"
SYNTHETIC_FEW_SHOT = "# Ejemplos\n\n<ejemplo>sintético</ejemplo>"
SYNTHETIC_RESET_BODY = "Procedimiento sintético de reset."
SYNTHETIC_RESET_STEP_BODY = "Paso sintético A."

SYNTHETIC_RESET_PROTOCOL = (
    "# RESET_PASSWORD\n"
    "\n"
    f"{SYNTHETIC_RESET_BODY}\n"
    "\n"
    "## Vías\n"
    "\n"
    "### Portal sintético uno\n"
    "\n"
    f"{SYNTHETIC_RESET_STEP_BODY}\n"
    "\n"
    "### Portal sintético dos\n"
    "\n"
    "Paso sintético B.\n"
    "\n"
    "### Mesa sintética\n"
    "\n"
    "Paso sintético C.\n"
)
SYNTHETIC_UNLOCK_BODY = "Procedimiento sintético de desbloqueo."

PROTOCOL_BODIES: dict[str, str] = {
    "RESET_PASSWORD.runtime.md": SYNTHETIC_RESET_PROTOCOL,
    "UNLOCK_ACCOUNT.runtime.md": f"# UNLOCK_ACCOUNT\n\n{SYNTHETIC_UNLOCK_BODY}",
}

SYNTHETIC_GUIDED_STEPS: tuple[tuple[Action, tuple[str, ...]], ...] = (
    (Action.RESET_PASSWORD, GUIDED_STEPS),
)


def make_module(name: str, text: str) -> PromptModule:
    return validate_prompt_module(name, text.encode("utf-8"))


def make_bundle(*, few_shot_text: str | None = SYNTHETIC_FEW_SHOT) -> PromptBundle:
    """A fully synthetic in-memory bundle; no file I/O involved.

    ``few_shot_text=None`` builds the F0 ablation without the module.
    """
    protocols = tuple(
        (action, make_module(filename, PROTOCOL_BODIES[filename]))
        for action, filename in PROTOCOL_FILENAMES
    )
    few_shot = make_module("few_shot.md", few_shot_text) if few_shot_text is not None else None
    return build_prompt_bundle(
        make_module("core.md", SYNTHETIC_CORE),
        make_module("catalog.md", SYNTHETIC_CATALOG),
        few_shot,
        protocols,
        guided_steps=SYNTHETIC_GUIDED_STEPS,
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
