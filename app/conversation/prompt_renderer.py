"""Pure prompt composition for the CU013 conversational turn.

The system instruction is composed deterministically from immutable modules:
the stable general rules (``core``), the minimal capability catalog, and, only
when the durable semantic state carries an active goal, the private runtime
protocol of that capability. The renderer never performs I/O, never inspects
the transcript and never routes by keywords: selection depends exclusively on
the durable ``ConversationGoal``.

``PromptBundle`` and ``StaticPrompt`` both satisfy ``PromptSource``: the bundle
is the active product path, while the static source exists only for the
evaluation lane that replays a frozen baseline text.
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
    "PROMPT_COMPOSITION_PROTOCOLS",
    "PROMPT_COMPOSITION_SINGLE_BASELINE",
    "ComposedInstructions",
    "PromptBundle",
    "PromptModule",
    "PromptSource",
    "StaticPrompt",
    "build_prompt_bundle",
    "compose_instructions_text",
    "composition_order",
    "hash_prompt_text",
]

BASE_INSTRUCTION_KEY = "base"
COMPOSITION_SEPARATOR = "\n\n"
CORE_MODULE_NAME = "core.md"
CATALOG_MODULE_NAME = "catalog.md"
PROTOCOL_SECTION_TITLE = "## Protocolo activo: {action}"

PROMPT_COMPOSITION_PROTOCOLS = "prompt_composition_protocols"
PROMPT_COMPOSITION_SINGLE_BASELINE = "single_baseline_snapshot"
PROMPT_COMPOSITION_NONE = "none"


class PromptSource(Protocol):
    """Deterministic system-instruction selector; no I/O on the turn path."""

    def system_instructions(self, goal: ConversationGoal | None) -> str: ...


def hash_prompt_text(text: str) -> str:
    """SHA-256 of one prompt text, always over normalized UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PromptModule:
    """One immutable prompt module with its normalized-text digest."""

    name: str
    text: str
    sha256: str


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
    protocols: tuple[PromptModule, ...]
    instructions: tuple[ComposedInstructions, ...]
    fingerprint: str

    def system_instructions(self, goal: ConversationGoal | None) -> str:
        """The precomposed instruction for the durable goal; fail closed."""
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
        hashes = {self.core.name: self.core.sha256, self.catalog.name: self.catalog.sha256}
        for protocol in self.protocols:
            hashes[protocol.name] = protocol.sha256
        return dict(sorted(hashes.items()))

    def instruction_hashes(self) -> dict[str, str]:
        return {instruction.key: instruction.sha256 for instruction in self.instructions}

    def composition_orders(self) -> dict[str, list[str]]:
        return {instruction.key: list(instruction.order) for instruction in self.instructions}


@dataclass(frozen=True)
class StaticPrompt:
    """Single static system instruction; evaluation baseline lane only."""

    text: str

    def system_instructions(self, goal: ConversationGoal | None) -> str:
        return self.text


def compose_instructions_text(
    core: PromptModule,
    catalog: PromptModule,
    action: Action | None = None,
    protocol: PromptModule | None = None,
) -> str:
    """Compose core, catalog and the optional active protocol in that order.

    ``action`` and ``protocol`` travel together: the stable section title
    names the active capability without duplicating the protocol body.
    """
    if (action is None) != (protocol is None):
        raise ValueError("action and protocol must be provided together")
    parts = [core.text, catalog.text]
    if action is not None and protocol is not None:
        parts.append(PROTOCOL_SECTION_TITLE.format(action=action.value) + "\n\n" + protocol.text)
    return COMPOSITION_SEPARATOR.join(parts)


def composition_order(
    protocol: PromptModule | None = None, *, action: Action | None = None
) -> tuple[str, ...]:
    order = [CORE_MODULE_NAME, CATALOG_MODULE_NAME]
    if action is not None and protocol is not None:
        order.append(protocol.name)
    return tuple(order)


def build_composed_instructions(
    core: PromptModule,
    catalog: PromptModule,
    protocols: Sequence[tuple[Action, PromptModule]],
) -> tuple[ComposedInstructions, ...]:
    """Precompose the base instruction and one instruction per protocol."""
    composed = [
        ComposedInstructions(
            key=BASE_INSTRUCTION_KEY,
            order=composition_order(),
            text=compose_instructions_text(core, catalog),
            sha256="",
        )
    ]
    composed.extend(
        ComposedInstructions(
            key=action.value,
            order=composition_order(protocol, action=action),
            text=compose_instructions_text(core, catalog, action, protocol),
            sha256="",
        )
        for action, protocol in protocols
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
    protocols: Sequence[tuple[Action, PromptModule]],
) -> PromptBundle:
    """Build the immutable bundle; every supported action needs a protocol."""
    declared = {action for action, _ in protocols}
    missing = sorted(action.value for action in Action if action not in declared)
    if missing:
        raise ValueError(f"missing runtime protocol for: {', '.join(missing)}")
    modules = tuple(protocol for _, protocol in protocols)
    instructions = build_composed_instructions(core, catalog, protocols)
    fingerprint = hash_prompt_text(
        json.dumps(
            {
                "core": core.sha256,
                "catalog": catalog.sha256,
                "protocols": {protocol.name: protocol.sha256 for protocol in modules},
                "composition_orders": {
                    instruction.key: list(instruction.order) for instruction in instructions
                },
                "instructions": {
                    instruction.key: instruction.sha256 for instruction in instructions
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return PromptBundle(
        core=core,
        catalog=catalog,
        protocols=modules,
        instructions=instructions,
        fingerprint=fingerprint,
    )
