"""Pure prompt composition for the CU013 conversational turn.

The system instruction is composed deterministically from immutable modules:
the stable general rules (``core``), the minimal capability catalog
(``catalog``), the applicable protocol text and the static decision examples
(``few_shot``). Protocol selection depends exclusively on the durable
``ConversationGoal`` and, when a guided step is tracked, on the durable
``procedure_current``: the projected window keeps the common protocol sections
plus the current step section, always by document order and never by reading
the transcript, embeddings or a second model call.

The renderer performs no I/O and no keyword routing; ``PromptBundle`` and
``StaticPrompt`` both satisfy ``PromptSource``: the bundle is the active
product path, while the static source exists only for the evaluation lane that
replays a frozen baseline text.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.session.actions import Action
from app.session.record import ConversationGoal

__all__ = [
    "BASE_INSTRUCTION_KEY",
    "CATALOG_MODULE_NAME",
    "COMPOSITION_SEPARATOR",
    "CORE_MODULE_NAME",
    "FEW_SHOT_MODULE_NAME",
    "PROJECTION_MODE_FULL",
    "PROJECTION_MODE_STEP_WINDOW",
    "PROMPT_COMPOSITION_NONE",
    "PROMPT_COMPOSITION_PROTOCOLS",
    "PROMPT_COMPOSITION_SINGLE_BASELINE",
    "ComposedInstructions",
    "PromptBundle",
    "PromptModule",
    "PromptSource",
    "ProtocolStructure",
    "StaticPrompt",
    "build_prompt_bundle",
    "compose_instructions_text",
    "hash_prompt_text",
    "parse_protocol_structure",
    "projected_instruction_key",
]

BASE_INSTRUCTION_KEY = "base"
COMPOSITION_SEPARATOR = "\n\n"
CORE_MODULE_NAME = "core.md"
CATALOG_MODULE_NAME = "catalog.md"
FEW_SHOT_MODULE_NAME = "few_shot.md"
PROTOCOL_SECTION_TITLE = "## Protocolo activo: {action}"

PROMPT_COMPOSITION_PROTOCOLS = "prompt_composition_protocols"
PROMPT_COMPOSITION_SINGLE_BASELINE = "single_baseline_snapshot"
PROMPT_COMPOSITION_NONE = "none"

PROJECTION_MODE_FULL = "full"
PROJECTION_MODE_STEP_WINDOW = "step_window"


class PromptSource(Protocol):
    """Deterministic system-instruction selector; no I/O on the turn path."""

    def system_instructions(
        self, goal: ConversationGoal | None, procedure_current: str | None = None
    ) -> str: ...


def hash_prompt_text(text: str) -> str:
    """SHA-256 of one prompt text, always over normalized UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def projected_instruction_key(action: Action, step: str) -> str:
    return f"{action.value}@{step}"


@dataclass(frozen=True)
class PromptModule:
    """One immutable prompt module with its normalized-text digest."""

    name: str
    text: str
    sha256: str


@dataclass(frozen=True)
class ProtocolStructure:
    """Deterministic view of one protocol: preamble, common and step sections.

    The step sections are the level-3 headings in document order; the loader
    validates their count against the runtime guided steps before any
    projection exists, so a mislabeled protocol fails startup instead of
    composing the wrong window.
    """

    preamble: str
    common_sections: tuple[str, ...]
    guided_sections: tuple[str, ...]

    def projected_text(self, step_index: int) -> str:
        """Common sections plus the current step section, in document order."""
        if not 0 <= step_index < len(self.guided_sections):
            raise IndexError("guided step outside the protocol structure")
        parts = [self.preamble, *self.common_sections, self.guided_sections[step_index]]
        return COMPOSITION_SEPARATOR.join(part for part in parts if part)


def parse_protocol_structure(text: str) -> ProtocolStructure:
    """Split normalized protocol markdown into preamble, common and steps."""
    preamble: list[str] = []
    common: list[str] = []
    guided: list[str] = []
    current: list[str] | None = None
    current_kind = "preamble"

    def flush() -> None:
        if current is None:
            return
        block = "".join(current).strip()
        if not block:
            return
        if current_kind == "preamble":
            preamble.append(block)
        elif current_kind == "common":
            common.append(block)
        else:
            guided.append(block)

    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("### "):
            flush()
            current = [line]
            current_kind = "guided"
        elif stripped.startswith("## "):
            flush()
            current = [line]
            current_kind = "common"
        else:
            if current is None:
                current = [line]
                current_kind = "preamble"
            else:
                current.append(line)
    flush()
    return ProtocolStructure(
        preamble="\n".join(preamble).strip(),
        common_sections=tuple(section.strip() for section in common),
        guided_sections=tuple(section.strip() for section in guided),
    )


@dataclass(frozen=True)
class ComposedInstructions:
    """One precomposed system instruction and its composition order."""

    key: str
    order: tuple[str, ...]
    text: str
    sha256: str


@dataclass(frozen=True)
class PromptBundle:
    """Immutable bundle of modules and precomposed system instructions."""

    core: PromptModule
    catalog: PromptModule
    few_shot: PromptModule | None
    protocols: tuple[PromptModule, ...]
    instructions: tuple[ComposedInstructions, ...]
    projection_modes: tuple[str, ...]
    fingerprint: str

    def system_instructions(
        self, goal: ConversationGoal | None, procedure_current: str | None = None
    ) -> str:
        """The precomposed instruction for the durable state; fail closed."""
        if goal is not None and procedure_current is not None:
            key = projected_instruction_key(goal.action, procedure_current)
            for instruction in self.instructions:
                if instruction.key == key:
                    return instruction.text
        key = goal.action.value if goal is not None else BASE_INSTRUCTION_KEY
        for instruction in self.instructions:
            if instruction.key == key:
                return instruction.text
        raise KeyError(f"no composed system instruction for {key!r}")

    def instruction(self, key: str) -> ComposedInstructions:
        for instruction in self.instructions:
            if instruction.key == key:
                return instruction
        raise KeyError(key)

    def module_hashes(self) -> dict[str, str]:
        hashes = {
            self.core.name: self.core.sha256,
            self.catalog.name: self.catalog.sha256,
        }
        if self.few_shot is not None:
            hashes[self.few_shot.name] = self.few_shot.sha256
        for protocol in self.protocols:
            hashes[protocol.name] = protocol.sha256
        return dict(sorted(hashes.items()))

    def instruction_hashes(self) -> dict[str, str]:
        return {instruction.key: instruction.sha256 for instruction in self.instructions}

    def composition_orders(self) -> dict[str, list[str]]:
        return {instruction.key: list(instruction.order) for instruction in self.instructions}

    def projected_steps(self) -> dict[str, list[str]]:
        """Projected instruction keys by action value, for identity records."""
        steps: dict[str, list[str]] = {}
        for instruction in self.instructions:
            if "@" in instruction.key:
                action_value, step = instruction.key.split("@", 1)
                steps.setdefault(action_value, []).append(step)
        return steps


@dataclass(frozen=True)
class StaticPrompt:
    """Single static system instruction; evaluation baseline lane only."""

    text: str

    def system_instructions(
        self, goal: ConversationGoal | None, procedure_current: str | None = None
    ) -> str:
        return self.text


def compose_instructions_text(
    core: PromptModule,
    catalog: PromptModule,
    few_shot: PromptModule | None,
    action: Action | None = None,
    protocol_text: str | None = None,
) -> str:
    """Compose core, catalog, optional protocol section and few-shot examples."""
    if (action is None) != (protocol_text is None):
        raise ValueError("action and protocol text must be provided together")
    parts = [core.text, catalog.text]
    if action is not None and protocol_text is not None:
        parts.append(PROTOCOL_SECTION_TITLE.format(action=action.value) + "\n\n" + protocol_text)
    if few_shot is not None:
        parts.append(few_shot.text)
    return COMPOSITION_SEPARATOR.join(parts)


def _composition_order(
    protocol_name: str | None, *, step: str | None, with_few_shot: bool
) -> tuple[str, ...]:
    order = [CORE_MODULE_NAME, CATALOG_MODULE_NAME]
    if protocol_name is not None:
        order.append(protocol_name)
        if step is not None:
            order.append(f"step:{step}")
    if with_few_shot:
        order.append(FEW_SHOT_MODULE_NAME)
    return tuple(order)


def build_composed_instructions(
    core: PromptModule,
    catalog: PromptModule,
    few_shot: PromptModule | None,
    protocols: Sequence[tuple[Action, PromptModule]],
    guided_steps: Sequence[tuple[Action, tuple[str, ...]]] = (),
) -> tuple[ComposedInstructions, ...]:
    """Precompose base, full-protocol and projected per-step instructions."""
    with_few_shot = few_shot is not None
    composed = [
        ComposedInstructions(
            key=BASE_INSTRUCTION_KEY,
            order=_composition_order(None, step=None, with_few_shot=with_few_shot),
            text=compose_instructions_text(core, catalog, few_shot),
            sha256="",
        )
    ]
    steps_by_action = dict(guided_steps)
    for action, protocol in protocols:
        composed.append(
            ComposedInstructions(
                key=action.value,
                order=_composition_order(protocol.name, step=None, with_few_shot=with_few_shot),
                text=compose_instructions_text(core, catalog, few_shot, action, protocol.text),
                sha256="",
            )
        )
        steps = steps_by_action.get(action, ())
        if not steps:
            continue
        structure = parse_protocol_structure(protocol.text)
        if len(structure.guided_sections) != len(steps):
            raise ValueError(
                f"protocol {protocol.name} must define exactly {len(steps)} guided sections"
            )
        for index, step in enumerate(steps):
            composed.append(
                ComposedInstructions(
                    key=projected_instruction_key(action, step),
                    order=_composition_order(protocol.name, step=step, with_few_shot=with_few_shot),
                    text=compose_instructions_text(
                        core, catalog, few_shot, action, structure.projected_text(index)
                    ),
                    sha256="",
                )
            )
    return tuple(
        ComposedInstructions(
            key=instruction.key,
            order=instruction.order,
            text=instruction.text,
            sha256=hash_prompt_text(instruction.text),
        )
        for instruction in composed
    )


def build_prompt_bundle(
    core: PromptModule,
    catalog: PromptModule,
    few_shot: PromptModule | None,
    protocols: Sequence[tuple[Action, PromptModule]],
    guided_steps: Sequence[tuple[Action, tuple[str, ...]]] = (),
) -> PromptBundle:
    """Build the immutable bundle; every supported action needs a protocol."""
    declared = {action for action, _ in protocols}
    missing = sorted(action.value for action in Action if action not in declared)
    if missing:
        raise ValueError(f"missing runtime protocol for: {', '.join(missing)}")
    modules = tuple(protocol for _, protocol in protocols)
    instructions = build_composed_instructions(core, catalog, few_shot, protocols, guided_steps)
    modes = tuple(
        PROJECTION_MODE_STEP_WINDOW if steps else PROJECTION_MODE_FULL for _, steps in guided_steps
    )
    fingerprint_payload: dict[str, object] = {
        "core": core.sha256,
        "catalog": catalog.sha256,
        "few_shot": few_shot.sha256 if few_shot is not None else None,
        "protocols": {protocol.name: protocol.sha256 for protocol in modules},
        "composition_orders": {
            instruction.key: list(instruction.order) for instruction in instructions
        },
        "instructions": {instruction.key: instruction.sha256 for instruction in instructions},
        "projection_modes": list(modes),
    }
    fingerprint = hash_prompt_text(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"))
    )
    return PromptBundle(
        core=core,
        catalog=catalog,
        few_shot=few_shot,
        protocols=modules,
        instructions=instructions,
        projection_modes=modes or (PROJECTION_MODE_FULL,),
        fingerprint=fingerprint,
    )
