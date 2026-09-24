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

## Research checkpoint — Gemini prompt/caching

Fecha de consulta: 2026-09-24. Fuentes primarias Google/Google Cloud vigentes;
Context7 contrastado con las versiones bloqueadas (`google-genai==2.23.0`,
`langgraph==1.2.11`, `pydantic==2.13.5`).

Fuentes principales:

- Prompting strategies (Gemini API): https://ai.google.dev/gemini-api/docs/prompting-strategies
- Guía de prompting de Gemini 3 (Agent Platform): https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start/gemini-3-prompting-guide
- Ficha Gemini 3.5 Flash-Lite: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite
- Context cache overview / create / use: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/context-cache/context-cache-overview, `.../context-cache-create`, `.../context-cache-use`
- Few-shot examples (Vertex): https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/prompts/few-shot-examples
- Prompt design strategies (Vertex): https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/prompts/prompt-design-strategies

| Claim | Source | ¿Aplica a 3.5 Flash-Lite? | Implicación para CU013 | Acción |
|---|---|---|---|---|
| Gemini 3 responde mejor a instrucciones directas, concisas y bien estructuradas | Guía Gemini 3 (§prácticas recomendadas): "Be precise and direct... Avoid unnecessary or overly persuasive language" | Sí (familia Gemini 3) | `core.md` sin prosa persuasiva; reglas imperativas cortas | reescritura de core |
| Restricciones críticas/rol/formato deben ir en system instruction o al principio | Guía Gemini 3: "Place essential behavioral constraints, role definitions (persona), and output format requirements in the System Instruction or at the very beginning" | Sí | Mantener rol y semántica crítica al inicio del system instruction | orden de core |
| Matiz: restricciones negativas demasiado tempranas pueden perderse; en prompts complejos conviene cerrar con lo crítico | Guía Gemini 3 (§Organizing important information and constraints) | Sí | Negativas operativas (verdad, no inventar) al final del bloque de decisión | orden de core |
| Markdown/XML son delimitadores válidos si la estructura es consistente | Prompting strategies: "XML-style tags... or Markdown headings are effective. Choose one format and use it consistently" | Sí | Mantener Markdown consistente; few-shot con un único formato de ejemplo | consistencia |
| Para contexto extenso, el contexto precede a la tarea/pregunta, con ancla | Guía Gemini 3: "supply all the context first. Place your specific instructions or questions at the very end" | Sí | contents: estado → procedimiento → memoria → transcript (ya es el orden); ancla "Turno del llamante:" | sin cambio (verificado) |
| Few-shot mejora patrón/alcance/formato; demasiados ejemplos sobreajustan | Prompting strategies + Vertex few-shot: "if you include too many examples, the model may start to overfit" | Sí | micro-set 2–4 ejemplos contrastivos sólo para los dos defectos | few_shot v1 (4) |
| No es necesario pedir chain-of-thought/planificación textual | Prompt design strategies: "If you're using Thinking, try prompting without step-by-step instructions on how the model should reason" | Sí | No agregar CoT al prompt | no-action |
| `thinking_level=MINIMAL` es apropiado para clasificación/routing/JSON sensible a latencia | Ficha 3.5 Flash-Lite: "Usa thinking_level.MINIMAL para tareas de clasificación y extracción más simples o sensibles a la latencia... ideal para clasificación, enrutamiento o extracción de JSON" | Sí (default del modelo) | Mantener MINIMAL; no probar MEDIUM/HIGH | no-action |
| Temperatura/Top-K/Top-P no son palanca: no se admiten valores personalizados | Ficha 3.5 Flash-Lite: "No se admiten valores personalizados... Si estableces un valor personalizado... se ignorará" | Sí | No tocar parámetros de muestreo | no-action |
| Structured output soportado y suficiente para la estructura | Ficha 3.5 Flash-Lite: "Salidas estructuradas ... Admitido" | Sí | Mantener `response_schema`; no duplicar enums en el prompt | auditoría de core |
| Context caching implícito y explícito soportados | Ficha 3.5 Flash-Lite: "Almacenamiento de contexto implícito/explícito en caché / Admitido" | Sí | Evaluar elegibilidad; no asumir hits | Fases A/B/C |
| Mínimo real de tokens cacheables (Gemini 3): 4.096 (implícito y explícito) | Overview (§Límites): "Modelos de la familia Gemini 3: 4,096 tokens" | Sí (4096) | Prefijo cacheable debe alcanzar 4.096 por sí mismo; no rellenar | Fase A |
| Hits de caché se reportan en `cachedContentTokenCount` | Overview: "el campo cachedContentTokenCount en los metadatos de tu respuesta indica la cantidad de tokens en la parte almacenada en caché" | Sí | Capturar `cached_content_token_count` del SDK y reportarlo | instrumentación |
| Con `cached_content` no se puede reespecificar system_instruction/tools/tool_config en la request (400 INVALID_ARGUMENT) | Use page (§Restricciones) + error reportado: "Tool config, tools and system instruction should not be set in the request when using cached content" | Sí | Si se usara caché explícita, la instrucción debe vivir sólo en la caché; equivalente semántico obligatorio | Fase C / STOP |
| TTL por defecto 60 min; mínimo 1 min; sin máximo; almacenamiento con costo; borrado explícito | Create/Use pages | Sí | TTL de experimento 15 min si aplicara; borrar al cerrar | Fase C |
| Endpoint global soportado para caching; CMEK no soportado con global | Create page (§Compatibilidad de ubicación / claves) | Sí (global) | No usar CMEK | Fase C |
| `response_schema`/`thinking_config` con caché explícita | Sin mención en la documentación de caching | Indeterminado | Debe verificarse con probe; si no es seguro → NOT APPLICABLE | Fase C |

Context7 contrastado (versiones efectivas):

- `google-genai` 2.23.0 (instalada): `Client.caches.create/delete`,
  `CreateCachedContentConfig(contents, system_instruction, ttl, ...)`,
  `GenerateContentConfig.cached_content` y
  `usage_metadata.cached_content_token_count` existen en la versión bloqueada.
  Context7 (`/googleapis/python-genai`) documenta la misma forma de API
  (`caches.create`, `cached_content`, `cached_content_token_count`).
  No se requiere cambio de dependencia.
- `langgraph` 1.2.11: patrón StateGraph → nodo con estado tipado → updates
  parciales; `compile()` sin checkpointer es el uso soportado (sin thread_id,
  invocaciones aisladas). El refactor de prompts no agrega nodos: el rendering
  es responsabilidad del adapter, no del grafo.
- `pydantic` 2.13.5: `ConfigDict(extra="forbid", frozen=True)` y
  `model_json_schema()` incluyen `description` de `Field`, por lo que la
  semántica puede viajar en el schema sin duplicarse en el prompt.

Decisión de research: mantener `thinking_level=MINIMAL`, structured output y
un único system instruction compuesto; no introducir CoT ni ejemplos masivos;
reducir duplicación schema/prompt; tratar caching como medición, no como
supuesto.

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

## Candidato exacto (iteración previa, 851fe0b)

Identidad Git del candidato de la iteración anterior, preservada como
historia; la iteración descrita abajo mide `40042db`:

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

## Resultados de la iteración previa (851fe0b)

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

## Iteración de optimización — cambios de prompt y proyección

Candidato medido: `40042db` (worktree limpio, rama `exp/prompt-protocols`).

Cambios por archivo:

| Archivo | Cambio | Razón |
|---|---|---|
| `prompt_templates/core.md` | Reordenado (Rol → Conversación → Respuesta hablada → Decisión estructurada → Verdad del runtime); añadida evidencia de completitud explícita, cancelación que no prohíbe un request posterior, intención ≠ completitud; eliminadas repeticiones | defectos 5.1/5.2 y guía Gemini 3 (restricciones críticas temprano, negativas al final, definiciones compactas) |
| `prompt_templates/few_shot.md` (nuevo) | 4 ejemplos contrastivos: sí a pregunta de completitud → ADVANCE; continuación → NONE; pregunta lateral → NONE; re-request tras cancelación → REQUEST | pocos ejemplos dirigidos a los dos defectos; formato único |
| `prompt_renderer.py` | `system_instructions(goal, procedure_current)`; proyección determinista por secciones L3 en orden de documento; clave `ACCION@paso` | contexto mínimo necesario sin retrieval ni keywords sobre el transcript |
| `prompt_loader.py` | Lee `few_shot.md`; valida que el protocolo tenga exactamente los `###` de los pasos guiados y falla startup si no | contrato de proyección fail-closed |
| `gemini.py` / `turns.py` | El seam recibe `procedure_current` durable y registra `cached_content_token_count` | selección determinista + observabilidad de caché |
| `evals/context_cache_probe.py` (nuevo) | Fases A/B/C de caching, sólo medición | experimento de caching separado de la memoria |

## Resultados de la iteración

### Comparación B — aceptación contra baseline

`129c793` snapshot nuevo run `...T201137-h676ce61` vs candidato
`...T202107-he88d730` (+3 reruns focalizados):

```text
paired_valid=189  infra=0  incomplete=0
critical_gate=0   targeted_regressions=0   targeted_improvements=0
unrelated_regressions=8 → NEEDS OWNER DECISION
case summaries: baseline 52 PASS / 11 FAIL → candidato 53 PASS / 10 FAIL
reps válidas:   baseline 160 PASS / 29 FAIL → candidato 159 PASS / 24 FAIL
confirmation_state FAIL: 10 → 4
prompt tokens p50/p95: 2367/2504 → 3737/5143
model latency p50/p95 ms: 1485/1938 → 1438/2047 (sin causalidad)
```

Regresiones no objetivo persistentes (8), por familia:

1. `long-conversation-memory` (3 reps): cancelación en "mejor no por ahora"
   (ocurre también en el baseline) + recuperación inconsistente del goal.
2. `retroactive-step-correction` (2 reps) y `retroactive-step-correction-clarify`
   (1 rep): el modelo aún avanza el paso ante continuación/intención en algún
   muestreo ("ya voy a empezar", "continuemos").
3. `promise-capability-distinction` (2 reps): el candidato abre confirmación
   en el mismo turno en que registra el goal por una pregunta de capacidad.

### Comparación A — atribución contra el candidato 851fe0b

Artefacto `184520-hb596639` vs candidato nuevo (7 dimensiones declaradas):

```text
paired_valid=186  infra=3 (lado baseline histórico, sin rerun posible)
critical_gate=0   targeted_regressions=0   unrelated_regressions=11
```

Lectura: los dos defectos objetivo quedaron mayormente resueltos
(`pronoun-reference` 3/3→0/3 avances indebidos; `side-question-return`
2/3→aislado; `procedure-lost-step` limpio; `retroactive-step-correction-clarify`
con patrón correcto en 2/3), con deriva residual en continuación/intención y en
la apertura de confirmación.

### Diagnóstico de memoria

**NO MEMORY BLOCKER EVIDENCED**. La cancelación del caso
`long-conversation-memory` ocurre en el turno 7 y sigue dentro de la ventana
de 3 pares en el turno 8; el estado durable conserva goal/revisión y no hay
información expulsada. La falla es de clasificación semántica (CANCEL vs
NEGATIVE, re-REQUEST tras cancelar), no de memoria; inyectar más contexto no
la resolvería.

### Revisión hablada (manual, local)

Revisadas con `spoken_review_probe` (textos nunca persistidos):
`ambiguous-reset-unlock`, `direct-supported-request`,
`unlock-no-self-service`, `side-question-return`, `long-conversation-memory`,
con contraste baseline en las familias clave.

| Familia | Veredicto | Observación |
|---|---|---|
| ambiguous-reset-unlock | MEETS | una aclaración breve, una pregunta principal, sin goal |
| side-question-return | MEETS | responde el costo y retoma el paso sin avanzar |
| unlock-no-self-service | MEETS | no inventa autoservicio; ofrece la vía de Mesa de Servicio |
| direct-supported-request | CONCERN | reset pide confirmación antes de validar identidad (el runtime la bloquea; el wording promete de más) |
| promise-capability-distinction | CONCERN | misma apertura prematura con identidad vigente |
| long-conversation-memory | CONCERN | cancelación de "mejor no por ahora" y continuidad posterior irregular |

Las siete dimensiones quedan a juicio del owner; no se introdujo LLM judge.

### Tamaño de contexto (tokens, provider count_tokens)

| Componente | Baseline | Candidato |
|---|---:|---:|
| core | – (prompt único 1089) | 1177 |
| catalog | – | 135 |
| few-shot | – | 327 |
| protocolo RESET completo | – | 2216 |
| system_instruction:base | 1089 | 1641 |
| system_instruction:RESET completo | – | 3866 |
| system_instruction:RESET@microsoft_portal | – | 2961 |
| system_instruction:RESET@tivit_portal | – | 3160 |
| system_instruction:RESET@service_desk | – | 2835 |
| system_instruction:UNLOCK | – | 2421 |
| procedure_progress_block | 397 | 397 |
| recent_memory_block | 384 | 384 |
| state_block mínimo/activo | 27 / 50 | 27 / 50 |
| transcript de muestra | 8 | 8 |

La proyección retira ~905–1031 tokens por turno guiado de RESET respecto al
protocolo completo; no se persiguió una cifra arbitraria.

### Context caching

Fase A (mínimo vigente Gemini 3 = 4096 tokens, documentado): ninguna variante
alcanza el piso — base 1630, UNLOCK 2410, RESET@service_desk 2835,
RESET@microsoft_portal 2950, RESET@tivit_portal 3149, RESET completo 3855.

Fase B (2 warmups + 10 llamadas medidas por variante, prefijo idéntico):

| Variante | prompt p50 | cached p50 | hit | latencia p50/p95 |
|---|---:|---:|---|---:|
| base | 2384 | 0 | no | 1422 / 2297 |
| RESET completo | 4618 | 3972 | sí | 1515 / 1735 |
| RESET@microsoft_portal | 4111 | 3958 | sí | 1609 / 1938 |
| RESET@tivit_portal | 4317 | 3964 | sí | 1578 / 2437 |
| UNLOCK | 3174 | 0 | no | 1422 / 1625 |

Los hits aparecen sólo cuando el prefijo repetido completo supera 4096; en
turnos reales el contexto dinámico cambia, por lo que la instrucción de
sistema (≤3866) queda por debajo del piso: no se proyectan hits reales. La
latencia no muestra mejora sostenida; no se atribuye causalidad.

Fase C: **EXPLICIT CACHE NOT APPLICABLE**. Ningún prefijo alcanza 4096 y no se
rellena el prompt; no se creó ni borró ningún recurso `cachedContents` y no
hubo retención experimental remota. La API existe en `google-genai==2.23.0`,
pero además una request cached no puede reespecificar
`system_instruction`/`tools`, así que no se diseñó workaround.

### Gates

```text
python -m pytest            694 passed
python -m ruff check .      All checks passed
python -m ruff format --check .  133 files already formatted
python -m mypy app          Success: no issues found in 29 source files
python -B evals/conversation_eval.py --validate-only  cases=49 problems=0
git diff --check            limpio
```

## Veredicto

```text
INCONCLUSIVE — OWNER DECISION REQUIRED
NOT MERGED TO DEV
```

Sin violaciones críticas, sin regresiones objetivo y sin pares INFRA tras los
reruns, con mejoras agregadas (confirmation_state 10→4 FAIL, casos 11→10) y
los dos defectos objetivo mayormente corregidos, pero con 8 regresiones no
objetivo persistentes en tres propiedades: apertura prematura de confirmación
ante preguntas de capacidad/petición directa sin identidad, deriva residual de
avance por continuación/intención y continuidad tras cancelación. El owner
debe decidir entre una iteración acotada de semántica de confirmación y
completitud, aceptar con desviaciones declaradas para el gate de voz, o
rechazar. Cloud Run, secretos y XCALLY siguen sin tocarse.
