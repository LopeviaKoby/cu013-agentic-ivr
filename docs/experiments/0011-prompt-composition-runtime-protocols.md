# Experimento 0011: composición modular de prompts y protocolos runtime privados

- Status: Completed (veredicto INCONCLUSIVE — OWNER DECISION REQUIRED)
- Lifecycle: Planned → Running → Completed / Failed / Inconclusive
- Authority: evidencia experimental; no es una decisión arquitectónica ni una SPEC
- Date: 2026-09-24
- Rama: `exp/prompt-protocols` (aislada; no se integró a `dev`)

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
y no se tocó.

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
  marcado como no canónico (`effective_prompt_hash` =
  `5ba5d494980c09e9...`).

### EXPERIMENTAL CANDIDATE

- Composición modular: `core.md` + `catalog.md` + protocolo privado de la
  capability activa.
- Protocolos privados cargados una vez al startup (fuera de Git), con
  validación de tamaño/UTF-8/NUL/vacío/identidad y hashes estables.
- Fix de ambigüedad RESET_PASSWORD vs UNLOCK_ACCOUNT.
- Evaluación sintética pareada sobre el corpus completo.

Este registro es evidencia; no es una segunda SPEC.

## Propiedad objetivo del fix de ambigüedad

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

Identidad Git del candidato medido:

```text
source_git_sha         5bc9cb4 (exp/prompt-protocols, worktree limpio)
working_tree_diff_hash clean
bundle_fingerprint     e21bc8052c088c25... (open, ver artefactos)
módulos                core.md + catalog.md + protocolos privados
protocolos             RESET_PASSWORD.runtime.md b0f15d03... (9715 B)
                       UNLOCK_ACCOUNT.runtime.md a8a0c61f... (3412 B)
orden de composición   base:  core.md, catalog.md
                       RESET: core.md, catalog.md, RESET_PASSWORD.runtime.md
                       UNLOCK: core.md, catalog.md, UNLOCK_ACCOUNT.runtime.md
renderer / loader      hash de archivo registrado en cada artefacto
modelo                 Gemini 3.5 Flash-Lite, Vertex global, MINIMAL,
                       structured output, procedure classification obligatoria
```

Los hashes completos, el fingerprint del bundle, los hashes de system
instruction por variante y los hashes de renderer/loader viven en la sección
`prompt_composition` de cada artefacto de run; los protocolos privados nunca
se copiaron a Git, fixtures, logs ni artefactos.

## Composición de tokens (post-run, fuera del camino temporizado)

`count_tokens` del proveedor, sólo números:

| Bucket | Baseline | Candidato |
|---|---:|---:|
| system_instruction:base | 1089 | 1292 |
| system_instruction:RESET_PASSWORD | – | 3518 |
| system_instruction:UNLOCK_ACCOUNT | – | 2073 |
| module:core | – | 1156 |
| module:catalog | – | 135 |
| module:RESET_PASSWORD.runtime.md | – | 2216 |
| module:UNLOCK_ACCOUNT.runtime.md | – | 770 |
| state_block:minimal / active_reset | 27 / 50 | 27 / 50 |
| procedure_progress_block | 397 | 397 |
| recent_memory_block | 384 | 384 |
| transcript_sample | 8 | 8 |

Lectura: el prompt base se reduce al dejar de contener procedimiento; con goal
activo la instrucción crece porque incluye el protocolo completo de esa
capability (pertinencia por turno, no minimización a cualquier costo). No se
fijó ningún target artificial de tokens y no se atribuye causalidad a la
diferencia de tokens.

## Metodología de evaluación

```text
corpus           evals/conversation/cases.yaml (49 casos / 41 familias)
lane             repository (save/reload por turno, servicio nuevo por turno)
memoria/progreso recent_conversation_memory, ventana 3, precedence_prompt_policy
repeticiones     3 válidas, 1 warmup fijo excluido
modelo/schema    idénticos en baseline y candidato
variable medida  prompt_composition (+ effective_prompt_hash)
familia objetivo ambiguous-reset-unlock
```

Runs (artefactos locales Git-ignored en `evals/results/`):

- baseline snapshot `conversation-eval-20260924T183725-h07c482c`
  (digest `h07c482cc0d30599`, 187 válidas / 2 INFRA).
- candidato `conversation-eval-20260924T184520-hb596639`
  (digest `hb596639f9ac9e44`, 186 válidas / 3 INFRA).
- reruns focalizados (INFRA y regresiones) fusionados sin borrar la evidencia
  original: baseline `185410`, `190031`, `190152`; candidato `185657`,
  `190214`. Comparación final: 189 pares válidos, 0 pares INFRA.
- comparación `conversation-eval-20260924T183725-h07c482c__conversation-eval-20260924T184520-hb596639.comparison.json`
  → **NEEDS OWNER DECISION**.

Las INFRA fueron `ModelUnavailableError` (cuota Vertex agotada durante la
batería de runs del día); los reruns las reemplazaron.

## Resultados

Gate crítico:

```text
new critical violations = 0 (baseline y candidato sin violaciones ejecutadas)
targeted regressions    = 0
targeted improvements   = 0 (la ambigüedad pasa también en el baseline)
```

Semántica (reps válidas fusionadas):

| Propiedad | Baseline FAIL | Candidato FAIL |
|---|---:|---:|
| case confirmation_state | 8 | 2 |
| case conversation_goal | 5 | 3 |
| case route | 15 | 13 |
| turn procedure_current | 15 | 10 |
| turn goal / goal_transition | 7 / 7 | 3 / 6 |
| turn route | 12 | 12 |

Casos por clasificación: baseline 52 PASS / 11 FAIL; candidato 55 PASS / 8 FAIL.

Regresiones no objetivo persistentes (candidato FAIL donde baseline PASS, tras
reruns): 7, concentradas en tres propiedades:

1. `pronoun-reference` turn3 `procedure_current` 3/3 — con el protocolo RESET
   activo, una continuación genérica ("bueno, sigamos con el cambio") hace que
   el modelo proponga `ADVANCE` y el runtime avance el paso guiado; la línea
   aceptada dice que una continuación no completa el paso. Carril sintético de
   progreso (los procedimientos no existen en el caller real).
2. `side-question-return` turn2 `procedure_current` 1/3 — mismo patrón con
   "listo, continuemos con el restablecimiento".
3. `long-conversation-memory` goal/confirmación — tras una cancelación
   explícita, un "confirmo el desbloqueo" posterior no vuelve a registrar el
   goal en 2/3 reps (el baseline sí lo re-registra). El caso es ruidoso (sus
   oráculos de cancelación ya fallan en ambos brazos), pero la diferencia de
   recuperación del goal es del candidato.

Latencia y tokens (sin SLO y sin causalidad):

```text
model latency p50/p95 ms   baseline 1484 / 1859   candidato 1562 / 2547
turn  latency p50/p95 ms   baseline 1485 / 1859   candidato 1562 / 2547
prompt tokens p50/p95      baseline 2367 / 2506   candidato 3423 / 4931
completion tokens p50      baseline 110           candidato 107
```

## Revisión hablada (owner)

Herramienta local `evals/spoken_review_probe.py` (imprime caller/asistente por
case ID; nunca escribe artefactos compartidos). La primera pasada alcanzó a
cubrir `ambiguous-reset-unlock`, `direct-supported-request`,
`unlock-no-self-service`, `pronoun-reference` y `side-question-return` antes
de que Vertex devolviera 429 de cuota. Muestras observadas: la aclaración de
ambigüedad es breve y con una sola pregunta; la respuesta lateral de costo es
natural y orienta; en la continuación genérica el mensaje pide abrir el portal
mientras el runtime ya avanzó el paso (incoherencia ya descrita).

Las siete dimensiones de `spoken_quality_review` quedan **NOT EVIDENCED**
hasta que el owner ejecute la revisión completa con cuota disponible; no se
introdujo LLM judge.

## Cloud Run y E2E

No ejecutados. La sección 22 de la instrucción autoriza secretos y deploy sólo
después de un gate pre-voz aceptado; el gate quedó `NEEDS OWNER DECISION`, por
lo que no se provisionaron secretos, no se desplegó ninguna revisión
experimental, no se creó la tag `e2e-prompt`, no se tocó XCALLY y no hubo
ninguna llamada real ni side effect. No se creó capacidad idle experimental.

## Limitaciones

- La varianza estocástica del modelo hace que regresiones de par único no
  equivalgan a regresión sistemática; se distinguieron por repetición
  (3/3, 2/3) y se re-ejecutaron.
- `long-conversation-memory` arrastra oráculos de cancelación que ya fallan en
  ambos brazos; su señal de goal final es la única diferencia atribuible al
  candidato.
- La cuota Vertex se agotó durante la batería; la revisión hablada completa y
  cualquier extensión deben ejecutarse cuando la cuota esté disponible.
- El carril sintético es el único que activa procedimiento guiado; las
  regresiones de `procedure_current` no describen por sí solas el caller real.

## Veredicto

```text
INCONCLUSIVE — OWNER DECISION REQUIRED
NOT MERGED TO DEV
```

Candidato sin violaciones críticas, sin regresiones objetivo, con mejoras
agregadas en confirmación/goal/route y con dos desviaciones sistemáticas
identificadas en el carril sintético (avance de paso por continuación
genérica; re-registro del goal tras cancelación). El owner debe elegir entre
iterar la redacción general de `core.md` y repetir el pareado, aceptar el
candidato con esas desviaciones declaradas para continuar a voz, o rechazarlo.
