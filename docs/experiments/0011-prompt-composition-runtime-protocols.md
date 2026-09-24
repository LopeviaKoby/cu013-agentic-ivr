# Experimento 0011: composición modular de prompts y protocolos runtime privados

- Status: Running
- Lifecycle: Planned → Running → Completed / Failed / Inconclusive
- Authority: evidencia experimental; no es una decisión arquitectónica ni una SPEC
- Date: 2026-09-24
- Rama: `exp/prompt-protocols` (aislada; no se integra a `dev` sin decisión explícita del owner)

## Pregunta e hipótesis

¿Puede CU013 mejorar la UX conversacional —velocidad, naturalidad, coherencia,
contextualización, continuidad y calidad semántica— reduciendo y ordenando el
prompt estático y componiendo dinámicamente sólo el protocolo de la capability
activa, sin convertir LangGraph/runtime en una FSM conversacional, sin
retrieval y sin una segunda llamada al modelo?

Hipótesis antes de implementar:

- un `core` de reglas generales estables más un `catalog` mínimo de
  capacidades más el protocolo privado de la capability activa produce
  instrucciones más cortas y pertinentes por turno;
- la composición por estado semántico durable (goal activo) es determinista y
  no requiere inspeccionar el transcript;
- el fix de ambigüedad RESET_PASSWORD vs UNLOCK_ACCOUNT se conserva como
  propiedad objetivo del experimento;
- los protocolos empresariales privados pueden vivir fuera de Git, cargarse
  una sola vez al startup desde mounts de Secret Manager y mantenerse en RAM.

## Planos explícitos

### LEGACY

No aplica a este experimento: no existen serializers/directives de
compatibilidad de prompts. El único carril legacy es el envelope HTTP sin
header, gobernado por [Boundary HTTP XCALLY↔CU013](../specs/xcally-boundary.md),
y no se toca aquí.

### BASELINE

- Comportamiento/candidato sintético vigente antes de este experimento.
- Referencia Git: `129c79397e8c7837db8367c0757bc0333e7d0c37`.
- Gemini 3.5 Flash-Lite / Vertex AI / model location `global` / `MINIMAL`.
- Structured output con clasificación procedimental obligatoria.
- Guards actuales del runtime, memoria reciente sintética de 3 pares y
  progreso procedimental.
- Prompt único estático (`SYSTEM_INSTRUCTIONS`) evaluado en el Experimento
  0009. Su texto exacto para el comparador vive en el fixture de evaluación
  [129c793-system.md](../../evals/conversation/baselines/129c793-system.md),
  marcado como no canónico.

### EXPERIMENTAL CANDIDATE

- Composición modular: `core.md` + `catalog.md` + protocolo privado de la
  capability activa.
- Protocolos privados montados desde Secret Manager (nunca versionados).
- Fix de ambigüedad RESET_PASSWORD vs UNLOCK_ACCOUNT.
- Evaluación sintética pareada y, si pasa el gate pre-voz, revisión Cloud Run
  DEV aislada para caller E2E desde XCALLY.

Este registro es evidencia; no es una segunda SPEC.

## Propiedad objetivo del fix de ambigüedad

Del seed anterior se conserva como **propiedad objetivo del experimento**, no
como aceptación final:

- ambigüedad entre dos acciones soportadas → sin goal materializado → LISTEN
  con una única aclaración breve;
- RESET directo → `RESET_PASSWORD` → captura de identidad;
- UNLOCK directo → `UNLOCK_ACCOUNT` → captura de identidad.

La desambiguación es semántica y pertenece al LLM; el runtime no inspecciona
texto natural ni mantiene reglas de keywords.

## Antecedente del seed de ambigüedad

Evidencia anterior registrada sólo como antecedente (micro-candidato subsumido
por este experimento):

```text
652 tests
smoke target 4/4
direct controls 2/2
targeted improvements = 1
targeted regressions = 0
critical violations = 0
comparator = NEEDS OWNER DECISION
```

## Candidato exacto

Pendiente de cierre: se registrarán aquí el SHA/diff, hashes de `core.md`,
`catalog.md` y protocolos privados, orden de composición, hashes de system
instruction por variante, hashes del renderer, fingerprint del bundle,
metodología, evaluaciones, latencia/tokens, revisión/tag Cloud Run, E2E y
limitaciones.