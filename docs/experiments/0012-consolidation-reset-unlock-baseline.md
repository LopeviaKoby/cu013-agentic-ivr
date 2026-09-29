# Experimento 0012 — Consolidación RESET/UNLOCK (traza mínima)

- Status: Completed
- Fecha: 2026-09-29
- Rama de consolidación: `consolidation/cu013-reset-unlock` desde `dev`
- Base: Gemini 3.5 Flash-Lite, Vertex `us`, `MINIMAL`, `attempts=1`,
  `timeout=30000 ms`, `max_output_tokens=256`, P1 semantic_obligation,
  immediate challenge window, next-step-v1, password efímera por voz.

Esta es traza mínima aceptada, sin datasets crudos, passwords, PII, logs
Asterisk, bodies RD, tokens ni JSONL/CSV extensos.

## 1. T1 attribution: MODEL × CONTEXT

El mistag de mode-selection/confirmación se redujo con señal semántica
derivada mínima, sin memoria textual y sin cambiar comportamiento productivo
por defecto. Brazos P0 (production-exact), P1 (minimal semantic obligation,
una línea JSON cerrada), P2 (P1 + último acto) y P3 (control historial) con
modelo, schema, prompts, estado y harness constantes. Resultado: P1 aporta el
contexto mínimo suficiente; P2/P3 no justifican complejidad. Detalle de
brazos y drivers one-off excluidos de dev por decisión (no son producto).

## 2. P1 result: minimal semantic context supported

`SemanticObligationProjection` (`ASSISTANCE_MODE_CHOICE | ACTION_CONFIRMATION
| NONE`) derivada pre-turn sólo de estado runtime, efímera, nunca durable ni
autoritativa, renderizada tras la proyección de estado y antes de memoria
experimental. Productivo siempre activo en `SessionConversationEngine`;
evaluación puede optar-out por seam. Propiedad: sin challenge consumible no
hay autorización desde mode selection; unseen/stale challenge nunca autoriza.

## 3. LOW_CONFIDENCE renderer: rejected

Composer estrecho para `LOW_CONFIDENCE` (misma disciplina que
`PollingFeedbackComposer`: runtime posee policy, composer sólo redacta
`{"message"}` con hechos PII-safe cerrados, validación determinista o fallback
al literal) no demostró beneficio que justifique segunda inferencia,
latencia ni superficie. Veredicto: REJECTED. Se conservan los literales
deterministas distintos `NO_SPEECH / LOW_CONFIDENCE / TIMEOUT` sin cambiar
thresholds.

## 4. Challenge/outcome coherence: accepted

Ventana inmediata de challenge (un `NONE` no resolutivo expira el challenge),
primera confirmación workflow-owned con mensaje determinista runtime-owned y
gate atómico outcome-coherente (un challenge staged sobrevive sólo si el
outcome caller-facing presenta su confirmación coincidente en acción,
revisión e identidad, sin parsear texto). Propiedades: unseen challenge no
queda consumible, stale no autoriza, exactamente un dispatch local, sin
redispatch en presentación.

## 5. RD correlation: unresolved; fail-safe temporal

`callId` = candidato empírico observado, semántica oficial NOT DOCUMENTED.
E2E aislada de un solo RESET (`POST/polls mismo callId`, `NONE → NONE →
SUCESSO`) es evidencia positiva para una sola operación y NO resuelve
correlación secuencial. Hasta correlación acreditada rige `ONE MUTATING AD
ACTION PER CALL` ([ADR-0013](../decisions/0013-one-mutating-ad-action-per-call.md)):
segunda mutación AD produce 0 POST, 0 operación y `TRANSFER` determinista;
guidance (incluido `RESET GUIDED/UNDECIDED`, VPN/VDI futura) queda fuera.

## 6. Final isolated RESET E2E: single coherent, sequential unresolved

Un RESET aislado resulta coherente de punta a punta en el contrato local;
no se infiere de ahí correlación secuencial, concurrencia ni late results
múltiples. `SessionRecord v7`, binding `callId` A+B y receipt wiring quedan
como plan de experimento/gap, no implementados aquí.

## Artefactos permanentes vs excluidos

Permanentes en dev: producto (`semantic_obligation`, `us/MINIMAL/256`,
coherencia, presentación efímera, polling acotado, next-step-v1), tests de
propiedades, harness reusable (provenance, obligation pre-turn, acto
post-turn, coherencia, paired, rerun, INFRA, spoken review) y este documento.
Excluidos: `audit/*`, drivers de atribución one-off, runner
`LOW_CONFIDENCE`, ledgers temporales, datasets crudos y secretos.
