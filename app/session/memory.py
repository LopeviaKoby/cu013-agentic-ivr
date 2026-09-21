"""Conversational memory and guided-procedure progress (synthetic lane only).

SYNTHETIC-ONLY, OPT-IN EVALUATION LANE. None of this is Accepted product
behavior for real callers: the no-recent-memory baseline, the
procedure-progress-only variant, the recent-conversation-memory variant, the
window size, the byte caps, the procedure fields and any retained text are
evaluation variants with fingerprints. The active evaluated profile is:
recent conversation memory with a window of three completed caller/assistant
turn pairs plus guided procedure progress, mandatory structured procedure
classification, and the accepted precedence/criteria text. Do not treat this
module as product authority.

Variant and prompt-policy values are self-sufficient strings. Historic short
experiment labels appear only in preserved experiment evidence; no reader,
alias or migrator keeps them alive in active code.

Binding policy for this iteration (owner clarification):

- Only non-sensitive synthetic utterances may enter the window/procedure
  trial. Real-caller textual memory stays disabled.
- Raw DTMF, identity documents, dates of birth, passwords, credentials,
  temporary passwords, API keys/tokens and raw payloads holding them must
  never reach the LLM, logs, fixtures or this memory. No content scanner is
  provided here on purpose: an ad-hoc redactor is not a substitute for an
  accepted retention policy.
- Persistable semantic state only: authorization/validation outcome,
  timestamps, TTL data, counters, revisions, external-operation truth and
  the experimental procedure/window shapes below.

Design (attribution across memory shapes):

- no-memory: this module is never consulted; behavior is exactly the current
  Thin Firestore path.
- procedure-only: only guided procedure progress (no dialogue window).
- recent-memory: procedure progress plus a recent completed-turn-pair window
  (default three pairs).

The runtime never reads pair *text* to decide anything: text is rendered
for the model input only. Procedure legality (allowed steps, transitions,
suspension, invalidation) is owned by deterministic helpers here; the
model only proposes an observation vocabulary the runtime may reject.
"""

from __future__ import annotations

import hashlib
import inspect
import time
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.session.actions import Action

EXPERIMENT_ID = "exp0009"

NO_RECENT_MEMORY = "no_recent_memory"
PROCEDURE_PROGRESS_ONLY = "procedure_progress_only"
RECENT_CONVERSATION_MEMORY = "recent_conversation_memory"
MEMORY_VARIANTS: tuple[str, ...] = (
    PROCEDURE_PROGRESS_ONLY,
    RECENT_CONVERSATION_MEMORY,
)

MEMORY_WINDOW_N_DEFAULT = 3
MEMORY_WINDOW_N_MAX = 5
RECENT_TURN_PAIRS_DEFAULT = MEMORY_WINDOW_N_DEFAULT
RECENT_TURN_PAIRS_MAX = MEMORY_WINDOW_N_MAX
MEMORY_PAIR_BYTES = 1024
MEMORY_WINDOW_BYTES = 3072
SESSION_BYTES_GUARD = 8192

DEFAULT_PROMPT_POLICY = "default_prompt_policy"
CONCISE_PROMPT_POLICY = "concise_prompt_policy"
CONTRASTIVE_EXAMPLES_PROMPT_POLICY = "contrastive_examples_prompt_policy"
PRECEDENCE_PROMPT_POLICY = "precedence_prompt_policy"
PROMPT_POLICIES: tuple[str, ...] = (
    DEFAULT_PROMPT_POLICY,
    CONCISE_PROMPT_POLICY,
    CONTRASTIVE_EXAMPLES_PROMPT_POLICY,
    PRECEDENCE_PROMPT_POLICY,
)
# Active wording: precedence ordering plus the unchanged general criteria.
# Earlier diet/few-shot wordings and the bare criteria remain readable for
# historic replay but are not part of the active baseline.
ACTIVE_PROMPT_POLICY = PRECEDENCE_PROMPT_POLICY
ACTIVE_RECENT_TURN_PAIRS = 3


def _precedence_prefix() -> str:
    """Minimal precedence ordering prepended to the unchanged base criteria.

    Lets the model rank a lateral question below an explicit execution
    request and a progress retraction below a goal change, without new
    fields, examples, or runtime NLU.
    """
    return (
        "Orden de precedencia (aplica antes que todo lo siguiente): "
        "1) Pregunta lateral —pregunta, duda, comentario o pedido de "
        "repetición sobre el trámite en curso—: responde, conserva objetivo "
        "y progreso, y NO abras ni reabras confirmación, NO pidas identidad "
        "y NO autorices nada por esa pregunta. "
        "2) Ejecución explícita de una acción soportada: sólo entonces avanza "
        "la confirmación según el estado vigente. "
        "3) Persona explícita: es handoff, no pregunta lateral. "
        "Progreso con el mismo objetivo: si dice que NO terminó el paso "
        "→ REGRESS con goal NONE (nunca CORRECT); si afirma que lo completó "
        "→ ADVANCE; pregunta, duda o repetición → KEEP."
    )


# Guided RESET steps derived from docs/specs/account-actions.md (RESET
# guided self-service bullets: Microsoft security-info portal including
# composition guidance; TIVIT access portal subject to corporate
# network/VPN; escalation to Service Desk when neither path works, for VDI
# permissions or when an unlock is required). UNLOCK_ACCOUNT has no guided
# self-service, so no procedure ever opens for it.
GUIDED_PROCEDURE_ID = "RESET_PASSWORD_GUIDED"
GUIDED_STEPS: tuple[str, ...] = ("microsoft_portal", "tivit_portal", "service_desk")

# Minimal actionable descriptions, one clause per accepted step, drawn only
# from the SPEC bullets above. They let the model verbalize the stored step
# without a second model call and without the full IOP in every prompt.
GUIDED_STEP_DESCRIPTIONS: dict[str, str] = {
    "microsoft_portal": (
        "portal de información de seguridad de Microsoft, incluidos los "
        "requisitos de composición de contraseña"
    ),
    "tivit_portal": (
        "portal de accesos TIVIT, informando la condición de conexión a la red corporativa o VPN"
    ),
    "service_desk": (
        "escalamiento a Service Desk cuando ninguna vía funciona, hay "
        "permisos VDI o se requiere desbloqueo"
    ),
}

OVERSIZE_CALLER_MARKER = "[omisión: entrada sobredimensionada]"
OVERSIZE_ASSISTANT_MARKER = "[omitido]"


class ProcedureObservation(StrEnum):
    """Model-proposed procedure cue; the runtime validates or ignores it."""

    NONE = "NONE"
    ADVANCE = "ADVANCE"
    REGRESS = "REGRESS"
    PAUSE = "PAUSE"
    RESUME = "RESUME"


class ExperimentalTurnPair(BaseModel):
    """One completed caller/assistant turn pair (synthetic text only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    caller_text: str = Field(min_length=1)
    assistant_text: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    goal_revision: int | None = Field(default=None, ge=0)
    omitted: bool = False

    @model_validator(mode="after")
    def _check_pair_bytes(self) -> ExperimentalTurnPair:
        size = len((self.caller_text + self.assistant_text).encode("utf-8"))
        if size > MEMORY_PAIR_BYTES:
            raise ValueError("experimental pair exceeds the per-pair byte cap")
        return self

    def byte_size(self) -> int:
        """UTF-8 bytes of both utterances; the experimental per-pair guard."""
        return len((self.caller_text + self.assistant_text).encode("utf-8"))


class ExperimentalSuspendedProcedure(BaseModel):
    """At most one explicitly suspended procedure for a temporary switch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    procedure_id: str = Field(min_length=1)
    action: Action
    goal_revision: int = Field(ge=0)
    current_step: str | None = None
    last_completed_step: str | None = None


class ExperimentalProcedureState(BaseModel):
    """Active guided-procedure progress bound to one goal revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    procedure_id: str = Field(min_length=1)
    current_step: str | None = None
    last_completed_step: str | None = None
    awaiting_caller: bool = False
    goal_revision: int = Field(ge=0)
    opened_at: AwareDatetime

    @model_validator(mode="after")
    def _check_steps(self) -> ExperimentalProcedureState:
        if self.procedure_id != GUIDED_PROCEDURE_ID:
            raise ValueError("unknown experimental procedure")
        for step in (self.current_step, self.last_completed_step):
            if step is not None and step not in GUIDED_STEPS:
                raise ValueError("procedure step outside the accepted guided slice")
        if self.current_step is not None and self.last_completed_step is not None:
            if _step_index(self.last_completed_step) >= _step_index(self.current_step):
                raise ValueError("last completed step must precede the current step")
        if self.current_step is None and self.last_completed_step not in (None, GUIDED_STEPS[-1]):
            raise ValueError("a finished procedure must complete the last guided step")
        return self


@dataclass(frozen=True)
class ExperimentalMemoryConfig:
    """Ephemeral opt-in for one turn; never durable, never for real callers."""

    variant: str = RECENT_CONVERSATION_MEMORY
    window_n: int = MEMORY_WINDOW_N_DEFAULT
    strategy: str = DEFAULT_PROMPT_POLICY

    def __post_init__(self) -> None:
        if self.variant not in MEMORY_VARIANTS:
            raise ValueError(
                "experimental variant must be procedure_progress_only or recent_conversation_memory"
            )
        if not 1 <= self.window_n <= MEMORY_WINDOW_N_MAX:
            raise ValueError("experimental window N outside 1..5")
        if self.strategy not in PROMPT_POLICIES:
            raise ValueError("unknown experimental prompt policy")

    @property
    def with_window(self) -> bool:
        """Procedure-only carries no window; recent-memory adds it."""
        return self.variant == RECENT_CONVERSATION_MEMORY


@dataclass(frozen=True)
class ExperimentalTurnMetrics:
    """PII-safe per-turn memory measurements; scalars only, never text."""

    session_bytes: int
    session_bytes_over_guard: bool
    memory_pairs: int
    memory_bytes: int
    memory_omitted: int
    encode_ms: float
    decode_ms: float
    render_ms: float | None


def _step_index(step: str) -> int:
    return GUIDED_STEPS.index(step)


def _previous_step(step: str | None) -> str | None:
    if step is None:
        return None
    index = _step_index(step)
    return GUIDED_STEPS[index - 1] if index > 0 else None


def open_procedure(
    action: Action | None, *, goal_revision: int, now: datetime
) -> ExperimentalProcedureState | None:
    """Open guided progress for a fresh RESET goal; UNLOCK never opens one."""
    if action is not Action.RESET_PASSWORD:
        return None
    return ExperimentalProcedureState(
        procedure_id=GUIDED_PROCEDURE_ID,
        current_step=GUIDED_STEPS[0],
        last_completed_step=None,
        awaiting_caller=False,
        goal_revision=goal_revision,
        opened_at=now,
    )


def apply_goal_lifecycle(
    procedure: ExperimentalProcedureState | None,
    suspended: ExperimentalSuspendedProcedure | None,
    *,
    previous_action: Action | None,
    current_action: Action | None,
    current_revision: int,
    now: datetime,
) -> tuple[ExperimentalProcedureState | None, ExperimentalSuspendedProcedure | None]:
    """Evolve procedure state across a goal transition.

    - Canceled goal: clear active and suspended; nothing is restorable.
    - Action change: suspend the active guided procedure into the single
      bounded slot, then restore it on explicit return (rebound to the new
      revision) or open fresh; confirmation/challenge state is never
      restored from memory (owned by the existing challenge logic).
    - Same-action correction (revision bump): rebind the revision and keep
      the portal progress. Deviation from the strictest reading of Exp 0009
      recorded in the experiment: a detail correction is not a procedure
      restart, while challenges still invalidate through the existing
      runtime path and are never revived from dialogue text.
    """
    if current_action is None:
        return None, None
    if previous_action is not None and previous_action is not current_action:
        if procedure is not None:
            suspended = ExperimentalSuspendedProcedure(
                procedure_id=procedure.procedure_id,
                action=previous_action,
                goal_revision=procedure.goal_revision,
                current_step=procedure.current_step,
                last_completed_step=procedure.last_completed_step,
            )
        else:
            suspended = suspended
        procedure = None
        if (
            suspended is not None
            and suspended.action is current_action
            and suspended.procedure_id == GUIDED_PROCEDURE_ID
        ):
            procedure = ExperimentalProcedureState(
                procedure_id=suspended.procedure_id,
                current_step=suspended.current_step,
                last_completed_step=suspended.last_completed_step,
                awaiting_caller=False,
                goal_revision=current_revision,
                opened_at=now,
            )
            suspended = None
        elif procedure is None:
            procedure = open_procedure(current_action, goal_revision=current_revision, now=now)
        return procedure, suspended
    if procedure is None:
        if current_action is Action.RESET_PASSWORD:
            return open_procedure(
                current_action, goal_revision=current_revision, now=now
            ), suspended
        return None, suspended
    if procedure.goal_revision != current_revision:
        procedure = procedure.model_copy(update={"goal_revision": current_revision})
    return procedure, suspended


def apply_procedure_observation(
    procedure: ExperimentalProcedureState | None,
    observation: ProcedureObservation | None,
) -> ExperimentalProcedureState | None:
    """Apply one model cue when legal; illegal cues leave state untouched."""
    if procedure is None or observation is None or observation is ProcedureObservation.NONE:
        return procedure
    if observation is ProcedureObservation.PAUSE:
        return procedure.model_copy(update={"awaiting_caller": True})
    if observation is ProcedureObservation.RESUME:
        return procedure.model_copy(update={"awaiting_caller": False})
    if observation is ProcedureObservation.ADVANCE:
        if procedure.current_step is None:
            return procedure
        advanced_from = procedure.current_step
        index = _step_index(advanced_from)
        nxt: str | None = GUIDED_STEPS[index + 1] if index + 1 < len(GUIDED_STEPS) else None
        return procedure.model_copy(
            update={"current_step": nxt, "last_completed_step": advanced_from}
        )
    if observation is ProcedureObservation.REGRESS:
        # Move back only to a legal guided point; the prior completed claim
        # is superseded and never revived from dialogue text.
        regressed_to: str | None
        regressed_last: str | None
        if procedure.current_step is None:
            regressed_to = procedure.last_completed_step
            regressed_last = _previous_step(procedure.last_completed_step)
        elif procedure.last_completed_step is not None:
            regressed_to = procedure.last_completed_step
            regressed_last = _previous_step(regressed_to)
        else:
            return procedure
        return procedure.model_copy(
            update={"current_step": regressed_to, "last_completed_step": regressed_last}
        )
    return procedure


def make_pair(
    caller_text: str,
    assistant_text: str,
    *,
    sequence: int,
    goal_revision: int | None,
) -> ExperimentalTurnPair:
    """Build a pair, or an explicit omission marker when oversize.

    Oversize input is never silently cut: the original words are dropped and
    a marker pair records the omission.
    """
    try:
        return ExperimentalTurnPair(
            caller_text=caller_text,
            assistant_text=assistant_text,
            sequence=sequence,
            goal_revision=goal_revision,
        )
    except ValueError:
        return ExperimentalTurnPair(
            caller_text=OVERSIZE_CALLER_MARKER,
            assistant_text=OVERSIZE_ASSISTANT_MARKER,
            sequence=sequence,
            goal_revision=goal_revision,
            omitted=True,
        )


def window_bytes(pairs: tuple[ExperimentalTurnPair, ...]) -> int:
    """Total UTF-8 bytes of the window; the experimental window guard input."""
    return sum(pair.byte_size() for pair in pairs)


def append_pair(
    pairs: tuple[ExperimentalTurnPair, ...],
    candidate: ExperimentalTurnPair,
    *,
    window_n: int,
) -> tuple[tuple[ExperimentalTurnPair, ...], float]:
    """Append one completed pair and trim oldest whole pairs in one pass."""
    start = time.monotonic()
    grown = (*pairs, candidate)
    while len(grown) > window_n or window_bytes(grown) > MEMORY_WINDOW_BYTES:
        grown = grown[1:]
        if not grown:
            break
    return grown, (time.monotonic() - start) * 1000.0


def decode_experimental(
    procedure: ExperimentalProcedureState | None,
    suspended: ExperimentalSuspendedProcedure | None,
    pairs: tuple[ExperimentalTurnPair, ...],
) -> tuple[
    ExperimentalProcedureState | None,
    ExperimentalSuspendedProcedure | None,
    tuple[ExperimentalTurnPair, ...],
    float,
]:
    """Timed passthrough for the durable-to-ephemeral conversion segment."""
    start = time.monotonic()
    return procedure, suspended, pairs, (time.monotonic() - start) * 1000.0


def _default_criteria() -> str:
    """Base criteria exactly as evaluated; wording is frozen."""
    return (
        "Criterio general de procedure_observation (tu propuesta; el runtime "
        "valida la legalidad): "
        "ADVANCE sólo cuando el llamante afirma que ya hizo o completó el paso "
        "actual. Una continuación, una pregunta lateral, pedir que repitan el "
        "paso, una duda o el silencio NO completan el paso: usa NONE y conserva "
        "el progreso. "
        "REGRESS cuando el llamante dice que NO terminó o NO hizo el paso "
        "actual: el objetivo no cambia, así que usa goal NONE (no CORRECT) y "
        "REGRESS; el progreso retrocede un paso legal. "
        "goal CORRECT es para precisar o cambiar QUÉ quiere el llamante, no "
        "para retroceder el progreso. "
        "Si el llamante pregunta en qué paso va o qué sigue, responde con el "
        "nombre y la instrucción del paso actual (NONE), sin avanzar, "
        "reiniciar ni inventar. "
        f"Nunca inventes pasos fuera de: {', '.join(GUIDED_STEPS)}. "
        "UNLOCK_ACCOUNT no tiene procedimiento guiado. "
        "Grounding: usa SÓLO los pasos, descripciones y estado de este bloque "
        "y del estado del sistema. Si un dato no está aquí (horarios, tiempos, "
        "detalles no listados), dilo brevemente sin inventarlo. "
        "Tiempo verbal según el estado: capacidad (puedo ayudarte), pendiente "
        "de identidad o confirmación (podré solicitarlo cuando confirmes), en "
        "proceso (sólo con operación pendiente o desconocida), resultado "
        "(sólo con estado confirmado). Nunca prometas ejecución sin la "
        "autorización y el estado que la respalden."
    )


def _concise_criteria() -> str:
    """Prompt diet: same properties, condensed, decision line placed last."""
    return (
        "Línea de decisión (el runtime valida; ante duda usa NONE y conserva "
        "el estado): el objetivo es QUÉ quiere el llamante; el progreso es "
        "CUÁNTO hizo. No confundirlos. "
        "ADVANCE: sólo si afirma que ya completó el paso actual. "
        "REGRESS: si dice que no lo terminó; el objetivo no cambia. "
        "KEEP (NONE): continuación, pregunta lateral, duda, repetición o "
        "silencio. "
        "Paso perdido: responde nombre + instrucción del paso actual, sin "
        "avanzar ni reiniciar. "
        f"Pasos válidos: {', '.join(GUIDED_STEPS)}. "
        "UNLOCK sin procedimiento. "
        "Grounding: sólo hechos de este bloque y del estado; lo ausente se "
        "dice sin inventar. "
        "Tiempos: puedo (capacidad) / podré si confirmas (pre-auth) / en "
        "proceso (sólo si pendiente) / hecho (sólo si confirmado)."
    )


def _contrastive_examples() -> str:
    """Two contrastive synthetic examples: decision boundaries, not answers.

    Wording is original to this prompt and copies no corpus utterance. Each
    example shows the state, the turn shape and the resulting structured
    decision — never a literal reply to memorize.
    """
    return (
        "<EJEMPLO 1> Estado: objetivo RESET_PASSWORD, paso actual "
        "tivit_portal, último microsoft_portal. Turno: el llamante dice que "
        "en realidad no terminó lo del portal. Decisión: goal NONE (el "
        "objetivo no cambió) + REGRESS (no terminó el paso actual). Mensaje: "
        "breve, nombra el paso a repetir. </EJEMPLO 1> "
        "<EJEMPLO 2> Estado: objetivo RESET_PASSWORD, paso actual "
        "microsoft_portal. Turno A (ya completó lo del portal): ADVANCE. "
        "Turno B (pide que repitan el paso): NONE y repite la instrucción, "
        "sin avanzar. Si preguntan un dato ausente (horarios, tiempos): "
        "decirlo sin inventar. </EJEMPLO 2>"
    )


def render_memory_block(
    pairs: tuple[ExperimentalTurnPair, ...],
    procedure: ExperimentalProcedureState | None,
    suspended: ExperimentalSuspendedProcedure | None,
    *,
    window_n: int,
    strategy: str = DEFAULT_PROMPT_POLICY,
) -> tuple[str, float]:
    """Render the synthetic window/procedure block for the model input.

    Text flows only toward the model call of an experimental synthetic turn.
    The runtime never parses this block back.
    """
    start = time.monotonic()
    lines = [
        "[Memoria experimental sintética — Exp0009; "
        f"ventana N={window_n}; sólo turnos sintéticos no sensibles]"
    ]
    if pairs:
        lines.append("Pares recientes (llamante → asistente):")
        for position, pair in enumerate(pairs, start=1):
            if pair.omitted:
                lines.append(f"{position}. [par omitido por tamaño]")
            else:
                lines.append(f"{position}. llamante: {pair.caller_text}")
                lines.append(f"   asistente: {pair.assistant_text}")
    else:
        lines.append("Pares recientes: ninguno.")
    if procedure is not None:
        current = procedure.current_step if procedure.current_step is not None else "completado"
        current_desc = (
            GUIDED_STEP_DESCRIPTIONS.get(procedure.current_step, "")
            if procedure.current_step is not None
            else ""
        )
        last = (
            procedure.last_completed_step
            if procedure.last_completed_step is not None
            else "ninguno"
        )
        current_part = f"paso actual: {current}"
        if current_desc:
            current_part += f" — {current_desc}"
        lines.append(
            f"Procedimiento guiado: {procedure.procedure_id} | {current_part} | "
            f"último completado: {last} | rev objetivo: {procedure.goal_revision} | "
            f"en pausa: {'sí' if procedure.awaiting_caller else 'no'}"
        )
    else:
        lines.append("Procedimiento guiado: ninguno.")
    if suspended is not None:
        lines.append(f"Procedimiento en espera: {suspended.procedure_id}.")
    if strategy == DEFAULT_PROMPT_POLICY:
        lines.append(_default_criteria())
    elif strategy == CONCISE_PROMPT_POLICY:
        lines.append(_concise_criteria())
    elif strategy == CONTRASTIVE_EXAMPLES_PROMPT_POLICY:
        lines.append(_concise_criteria() + " " + _contrastive_examples())
    elif strategy == PRECEDENCE_PROMPT_POLICY:
        lines.append(_precedence_prefix() + " " + _default_criteria())
    else:
        raise ValueError("unknown experimental prompt policy")
    return "\n".join(lines), (time.monotonic() - start) * 1000.0


def session_document_bytes(document: object) -> int:
    """UTF-8 bytes of the canonical serialized document; the session guard."""
    import json as _json

    canonical = _json.dumps(document, sort_keys=True, separators=(",", ":"), default=str)
    return len(canonical.encode("utf-8"))


def procedure_schema_identity() -> dict[str, object]:
    """Attributable identity of the experimental procedure contract."""
    payload = {
        "experiment": EXPERIMENT_ID,
        "procedure_id": GUIDED_PROCEDURE_ID,
        "steps": list(GUIDED_STEPS),
        "step_descriptions": dict(GUIDED_STEP_DESCRIPTIONS),
        "window_n_default": MEMORY_WINDOW_N_DEFAULT,
        "window_n_max": MEMORY_WINDOW_N_MAX,
        "pair_bytes": MEMORY_PAIR_BYTES,
        "window_bytes": MEMORY_WINDOW_BYTES,
        "session_bytes_guard": SESSION_BYTES_GUARD,
    }
    digest = hashlib.sha256(
        repr(sorted(payload.items())).encode("utf-8"),
    ).hexdigest()
    return {"schema": payload, "procedure_schema_hash": digest}


def memory_renderer_hash(strategy: str = DEFAULT_PROMPT_POLICY) -> str:
    """Hash of the exact renderer source; the memory prompt-diff fingerprint."""
    return hashlib.sha256(inspect.getsource(render_memory_block).encode("utf-8")).hexdigest()


def prompt_strategy_hash(strategy: str) -> str:
    """Hash of the exact prompt-policy text; distinguishes prompt wordings."""
    if strategy == DEFAULT_PROMPT_POLICY:
        text = _default_criteria()
    elif strategy == CONCISE_PROMPT_POLICY:
        text = _concise_criteria()
    elif strategy == CONTRASTIVE_EXAMPLES_PROMPT_POLICY:
        text = _concise_criteria() + " " + _contrastive_examples()
    elif strategy == PRECEDENCE_PROMPT_POLICY:
        text = _precedence_prefix() + " " + _default_criteria()
    else:
        raise ValueError("unknown experimental prompt policy")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def memory_variant_identity(
    variant: str, window_n: int, strategy: str = DEFAULT_PROMPT_POLICY
) -> dict[str, object]:
    """Attributable memory identity for run artifacts."""
    identity = procedure_schema_identity()
    return {
        "experiment": EXPERIMENT_ID,
        "memory_variant": variant,
        "memory_n": window_n,
        "prompt_strategy": strategy,
        "memory_pair_bytes": MEMORY_PAIR_BYTES,
        "memory_window_bytes": MEMORY_WINDOW_BYTES,
        "session_bytes_guard": SESSION_BYTES_GUARD,
        "procedure_schema_hash": identity["procedure_schema_hash"],
        "memory_renderer_hash": memory_renderer_hash(),
        "prompt_strategy_hash": prompt_strategy_hash(strategy),
    }
