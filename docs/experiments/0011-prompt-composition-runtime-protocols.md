# Experimento 0011: composición modular de prompts y protocolos runtime privados

- Status: Completed (Iteración A; veredicto INCONCLUSIVE — OWNER DECISION REQUIRED)
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

## Iteraci�n A � state projection + tombstone derivado + ablaci�n de few-shot

Hip�tesis: los fallos residuales no requieren m�s memoria ni m�s ejemplos; el
modelo necesita una proyecci�n transitoria y m�nima del estado que el
runtime ya conoce para no anticipar acciones ni confundir una cancelaci�n
previa con una nueva solicitud. Candidato medido: `f2421da` (worktree limpio).

### Research check (breve)

Context7 y documentaci�n instalada confirman: LangGraph 1.2.11 usa `StateGraph`
con estado tipado y updates parciales por nodo, sin reducers `Annotated` en
`GraphState` (reemplazo plano por campo: cancelar y re-proponer no revive
valores previos); `compile()` sin checkpointer es el uso soportado; el prompt
se renderiza por turno y no requiere persistir instrucciones din�micas;
`google-genai` 2.23.0 expone `GenerateContentConfig.system_instruction` y
structured output sin cambios. Por tanto: los hechos crudos viven en el estado
durable, la proyecci�n se deriva por turno y ninguna instrucci�n din�mica se
persiste.

### State projection (transitoria, no persistida)

`app/session/state_projection.py` define `ModelStateProjection` (frozen,
`extra=forbid`) y `project_model_state(...)`. Campos finales y fuente:

| Campo | Fuente | Derivaci�n |
|---|---|---|
| `active_goal` / `goal_revision` | `SessionRecord.goal` | valor directo |
| `identity_status` | `IdentityState` + `now` | precedencia HANDOFF_REQUIRED > MISSING > VALID > EXPIRED |
| `confirmation_pending` | `SessionRecord.confirmation` | `is not None` |
| `execution_confirmation_allowed` | goal + identidad + challenge + dispatch + operaci�n | espejo de las condiciones legales de `_maybe_open_challenge` |
| `external_action_allowed` | `SessionRecord.dispatch` | guard de despacho persistido |
| `external_success_claim_allowed` | `ExternalOperation.status` | `confirmed` |
| `external_operation_status` / `external_delivery_status` | `ExternalOperation` | valores cerrados |
| `procedure_id` / `procedure_current` | `ExperimentalProcedureState` | valor directo |

Se renderiza como bloque JSON compacto `<conversation_state>` al inicio de
contents, antes de progreso procedimental, memoria reciente y transcript. La
prosa anterior (`_state_block`) se retir� para no duplicar informaci�n. No se
persiste, no entra en `SessionRecord`, no contiene PII ni transcript.

### Tombstone sem�ntico (derivado)

Restricci�n de alcance: �2 proh�be tocar el modelo Firestore y
`SessionRepository`, as� que no se a�adi� ning�n campo durable de historial. El
hecho operativo que el modelo necesitaba se deriva en la proyecci�n:
`active_goal=null` + `confirmation_pending=false` +
`execution_confirmation_allowed=false` significan "no hay instancia activa ni
nada que confirmar"; el core a�ade que, sin goal activo, una confirmaci�n
verbal no reabre una instancia cancelada y una petici�n/confirmaci�n de una
capability registra REQUEST. Comportamiento durable verificado:

| Momento | goal | revision | confirmation | procedure | resultado |
|---|---|---|---|---|---|
| antes de cancelar | UNLOCK/RESET | N | challenge activo | paso vigente | instancia activa |
| tras CANCEL | null | � | null | null (y suspended null) | instancia limpia, sin reutilizar challenge |
| tras re-request expl�cito | capability | 1 (nueva instancia) | null hasta nueva apertura legal | nuevo o ninguno | REQUEST fresco |

Tests deterministas: `tests/session/test_state_projection.py` (determinismo,
sin PII, estados de identidad, permisos, cancelaci�n/re-request) y
`goal-re-request-after-cancel` en el corpus (PASS 3/3 en todas las variantes).

### Ablaci�n de few-shot (focal, 14 familias, 3 repeticiones)

| Variante | ejemplos | PASS/FAIL | INFRA | cr�ticos | proc. FAIL | conf. FAIL | goalTr FAIL | prompt p50/p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| F4 | 4 | 48/6 | 3 | 0 | 3 | 2 | 6 | 3955 / 5286 |
| F2 | 2 | 49/6 | 2 | 0 | 8 | 0 | 6 | 3772 / 5135 |
| F1 | 1 | 50/6 | 1 | 0 | 5 | 0 | 6 | 3706 / 5065 |
| F0 | 0 | 48/6 | 3 | 0 | 5 | 2 | 6 | 3560 / 4959 |

Tie-breaker focal (side-question-return, retroactive-step-correction,
long-conversation-memory): F4 2 fallos de procedimiento y 2 de confirmaci�n;
F1 5 de procedimiento y 0 de confirmaci�n. El defecto de cancelaci�n/
re-request queda resuelto en todas las variantes, F0 incluido: la proyecci�n
es quien lo porta, no los ejemplos. Los 6 FAIL de repetici�n en todas las
variantes son dos casos preexistentes id�nticos
(`confirmation-affirmative-authorizes`, `confirmation-negation-no-dispatch`).

Selecci�n: **F4** (menor evidencia de regresi�n del defecto objetivo �
procedimiento sin evidencia � en ablaci�n y tie-breaker); F2 eliminada
(peor en procedimiento); F0/F1 quedan como alternativas de menor contexto con
ventaja de confirmaci�n no reproducible (F0 comparte el fallo del turn5).

### Full paired (F4)

Comparaci�n B � `129c793` snapshot vs candidato (mismo c�digo, 3 reps, 1
warmup, repository, memoria 3, precedence; reruns focalizados para INFRA):

```text
paired_valid=192  infra=0  incomplete=0
critical_gate=0   targeted_regressions=0   targeted_improvements=1 (ambig�edad, 1 rep)
unrelated_regressions=5 ? NEEDS OWNER DECISION
casos: baseline 53 PASS / 11 FAIL ? candidato 57 PASS / 7 FAIL
reps v�lidas: baseline 153 PASS / 26 FAIL ? candidato 169 PASS / 20 FAIL
confirmation_state FAIL: 8 ? 2
conversation_goal FAIL: 5 ? 3
procedure_current FAIL (turno): 11 ? 3
goal FAIL (turno): 3 ? 3
prompt tokens p50/p95: 2422/2558 ? 3884/5286
model latency p50/p95 ms: 1469/2094 ? 1468/1953
turn latency p50/p95 ms: 1484/2093 ? 1469/1968
```

Regresiones no objetivo persistentes (5): `side-question-return` turn2
`procedure_current` 3/3 (una continuaci�n gen�rica "listo, continuemos�" a�n
avanza el paso en algunos muestreos; apareci� tambi�n 2/3 en la ablaci�n F4 y
2/3 en el tie-breaker, y no apareci� en el probe hablado � es el defecto
residual), `long-conversation-memory` turn5 `confirmation`/`revision` en 2 reps
(la correcci�n de cuenta abre challenge; comportamiento compartido con la
variante F0 y parcialmente presente en el baseline).

Comparaci�n A � `a8df4b8` vs candidato (8 variables + `corpus` como
confounder por el caso nuevo): paired 189, incomplete 3, infra 0, cr�ticos 0,
regresiones objetivo 0, no objetivo 5; mejoras agregadas goal FAIL 9?3 y
confirmation_state FAIL 4?2.

### Spoken review (manual, local)

Revisadas: ambiguous request, direct RESET/UNLOCK, side question, retorno al
procedimiento, cancelaci�n, re-request, identidad pendiente, identidad v�lida,
confirmaci�n.

| Interacci�n | Veredicto | Observaci�n |
|---|---|---|
| ambiguous request | MEETS | una aclaraci�n breve con dos opciones; sin goal |
| direct UNLOCK | MEETS | pide validar identidad; sin confirmaci�n prematura |
| direct RESET | CONCERN | sin confirmaci�n prematura (mejora), pero el wording "�Me confirmas tu identidad?" es impreciso para captura por tonos |
| side question + retorno | MEETS | responde el costo y retoma el paso sin avanzar (en esta muestra) |
| cancelaci�n | MEETS | reconoce y comunica la cancelaci�n |
| re-request posterior | MEETS | "puedo ayudarte a desbloquear tu cuenta de nuevo" + identidad |
| identidad v�lida | MEETS | abre confirmaci�n s�lo cuando corresponde |
| confirmaci�n | CONCERN | "Tu cuenta ser� desbloqueada en breve" promete un futuro sin despacho confirmado (fallo preexistente del caso) |

Nota adicional: en 1 de 4 par�frasis ambiguas el modelo propuso `REQUEST` sin
acci�n (violaci�n capturada por el runtime, mensaje de fallback seguro);
el or�culo de estado la deja pasar porque el estado final es correcto.

### Tokens y latencia (componentes)

| Componente | Baseline | Candidato |
|---|---:|---:|
| system_instruction:base | 1089 | 1729 (core 1265 + catalog 135 + few-shot 327) |
| system_instruction:RESET completo | � | 3954 |
| RESET@microsoft_portal / tivit / service_desk | � | 3049 / 3248 / 2923 |
| system_instruction:UNLOCK | � | 2509 |
| state_projection:minimal / active_reset | 92 / 93 (prosa antigua 27/50) | 92 / 93 |
| procedure_progress_block | 397 | 397 |
| recent_memory_block | 384 | 384 |
| transcript de muestra | 8 | 8 |

La proyecci�n cuesta ~65 tokens m�s que la prosa que reemplaza pero porta los
permisos; con ella sola (F0) el prompt baja ~395 tokens p50. No se fij� ning�n
objetivo m�gico de tokens.

### Memoria

Mantener exactamente 3 pares + estado durable. **NO MEMORY BLOCKER EVIDENCED**:
`goal-re-request-after-cancel` pasa 3/3 en F4/F2/F1/F0; la cancelaci�n del
turno 7 de `long-conversation-memory` sigue dentro de la ventana de 3 pares en
el turno 8 y el estado durable est� �ntegro, as� que la correcci�n de estas
propiedades no vino de memoria textual.

### Caching

No se ejecut� caching en esta iteraci�n (resultado previo: explicit NOT
APPLICABLE, implicit sin beneficio sostenido). No se cre� ning�n recurso.

### Gates

```text
python -m pytest            705 passed
python -m ruff check .      All checks passed
python -m ruff format --check .  138 files already formatted
python -m mypy app          Success: no issues found in 30 source files
python -B evals/conversation_eval.py --validate-only  cases=50 problems=0
git diff --check            limpio
docker build                OK (digest sha256:104f572b…), templates core/f4/f2/f1
                            verificados dentro de la imagen y F0 sin módulo
```

### Veredicto de la Iteraci�n A

```text
INCONCLUSIVE � OWNER DECISION REQUIRED
NOT MERGED TO DEV
```

Grandes mejoras: cancelaci�n/re-request resuelto (corpus y estado), sin
confirmaci�n prematura en petici�n directa, `procedure_current` 11?3,
`confirmation_state` 8?2, casos FAIL 11?7, y solo 5 regresiones no objetivo
(antes 8). Persiste un defecto reproducible: una continuaci�n gen�rica
("listo, continuemos con X") puede avanzar el paso guiado
(`side-question-return` 3/3 en el full paired, 2/3 en ablaci�n/tie-breaker,
ausente en el probe hablado). El owner debe decidir entre una iteraci�n
acotada espec�ficamente a esa clase sem�ntica, aceptar con la desviaci�n
declarada, o rechazar. Cloud Run, secretos y XCALLY siguen sin tocarse.

## Iteración final pre-voz — robustez + A/B de harness + migración DEV

Objetivo: cerrar el gate semántico/UX pre-voz con capas de robustez, un A/B
controlado español/inglés y la migración del entorno DEV a `tivit-cu013-prd`.
Todo local; sin deploy, sin secretos, sin XCALLY y **sin push** (los commits
quedan sólo en la rama local).

### Migración DEV (tivit-cu013-prd)

`config.yaml`, el fallback de proyecto en `gemini.py`, los runbooks y los ocho
scripts de `ops/gcp` apuntan ahora a `tivit-cu013-prd` con la runtime SA
`cu013-cloud-run-sa@tivit-cu013-prd.iam.gserviceaccount.com`, sin
impersonation, con el guard de rama como allow-list cerrada
(`-AllowedBranches`) y tiers intactos (cpu 1, 512Mi, concurrency 1, max 1,
min 0, benchmark min 1, billing request, región us-east1, modelo global).
`bootstrap-dev.ps1` y `verify-dev.ps1` se reescribieron como herramientas
TIVIT mínimas e idempotentes (sin crear SAs; dry-run por defecto en el
bootstrap). Lectura read-only: proyecto 731118338507, Firestore `(default)`
Native us-east1 vacío, APIs requeridas habilitadas, sin AR/secreto/servicio
todavía; ADC es `pedro.lopez@tivit.com` sin impersonation y Vertex respondió
(count_tokens OK). Aprovisionamiento **preparado, no ejecutado**; riesgo DRS
documentado en el deploy. Tests de acreditación en
`tests/test_dev_environment_migration.py`.

### Semántica

- Regla de evidencia de progreso al inicio del core (pregunta lateral,
  explicación o continuación genérica no completan el paso; sólo evidencia
  semántica o respuesta inequívoca a una pregunta directa).
- Grounding externo: con `external_success_claim_allowed=false` no se afirma
  éxito presente ni se promete éxito futuro; FAILED = fracaso confirmado con
  escalamiento; UNKNOWN = resultado no confirmable con escalamiento, sin
  inventar causa técnica ni agrupar con FAILED; sin "alternativa disponible"
  inventada.
- Identidad: puente verbal sin pedir el número ni duplicar el audio DTMF.
- Discovery §15/§16: entre `GET validauser = FOUND` y la fecha DTMF **no
  existe** hoy una llamada a CU013/Gemini (vive en el bloque XCALLY) y el
  retry pertenece al mismo bloque DTMF/XCALLY; por tanto no se añadió
  inferencia Gemini ni evento nuevo (ownership actual reportado al owner).

### Ablación de contenido F4

| Variante | reps P/F | INFRA | procF | confF | tok p50 |
|---|---:|---:|---:|---:|---:|
| F4 | 18/3 | 0 | 4 | 1 | 4228 |
| F4-e1 (positivo ADVANCE) | 20/0 | 1 | 4 | 2 | 4142 |
| F4-e2 (continuación) | 21/0 | 0 | 5 | 1 | 4157 |
| F4-e3 (lateral) | 20/1 | 0 | 5 | 1 | 4152 |
| F4-e4 (cancelación) | 21/0 | 0 | 3 | 2 | 4162 |

Ninguna remoción elimina la deriva de `side-question-return` (3/3 en todas) ?
el defecto residual no es de few-shot. El ejemplo de cancelación es redundante
(la propiedad re-request pasa también en F0). Se adopta `few_shot_min.md`
(ejemplos 1–3) como default y se conserva F4 como referencia de ablación.

### A/B de harness español vs inglés

Misma suite focal (9 familias), 3 reps, dos muestras independientes por
lenguaje; protocolos, valores de estado y schema sin traducir; salida hablada
forzada a español.

| Muestra | reps P/F | INFRA | críticos | procF | confF | goalTrF | tok p50/p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| ES-1 | 40/0 | 2 | 0 | 6 | 2 | 6 | 4205/5540 |
| ES-2 | 40/1 | 1 | 0 | 5 | 2 | 6 | 4206/5540 |
| EN-1 | 42/0 | 0 | 0 | 1 | 2 | 6 | 3913/5244 |
| EN-2 | 42/0 | 0 | 0 | 3 | 1 | 6 | 3912/5244 |

El inglés es reproduciblemente mejor en `procedure_current` (1–3 vs 5–6) y
~7% más barato en tokens, con confirmación/goal equivalentes y 0 FAIL de caso
en 2/2 muestras. El probe en inglés confirmó salida en español. **Ganador A/B:
EN**, pero **no se adopta en esta iteración** porque el held-out congelado y
el full paired corresponden al candidato ES; adoptarlo exigiría un held-out
nuevo (regla §24). Se eleva como recomendación para el siguiente ciclo.

### Capas de robustez

- **Golden**: full paired del candidato ES (191 pares válidos tras reruns,
  0 INFRA en la comparación final, 0 críticos, 0 regresiones objetivo, 9 no
  objetivo, `confirmation_state` FAIL 8?1, `procedure_current` 11?13) ?
  NEEDS OWNER DECISION.
- **Metamórfica**: 7 transformaciones invariantes (filler, frustración,
  repetición, autocorrección, contexto irrelevante, cierre coloquial, pregunta
  de duración) sobre 6 familias fuente; **invariance 1.0 (0 divergencias de
  47 comparadas)**; los 15 FAIL absolutos coinciden con los FAIL preexistentes
  de sus casos fuente.
- **Sintética (dev)**: generador del Implementer (bancos de enunciados y
  tabla de composición deterministas), 43 casos: ES 37 PASS/5 FAIL/1 INFRA y
  EN 36 PASS/5 FAIL/2 INFRA; defectos generales reproducidos: apertura
  prematura de challenge ante pregunta lateral (3–4 casos) y cancelación ante
  negativa de confirmación (1 caso). 0 críticos.
- **Held-out (una sola ejecución)**: 35 casos congelados (seed
  `syn-2026-09-25`, hashes de protocolos/módulos, `sha256 4bd84550…`):
  31 PASS/4 FAIL. Dos fallos son defecto de oráculo del generador (route
  esperada COLLECT_IDENTITY con identidad ya válida en re-request) y dos son
  los defectos residuales reales (challenge prematuro, cancelación por
  negativa). Sin críticos.

### LLM judge (rúbrica corta, modelo del Implementer)

Muestra de 15 mensajes del probe ES: **9 MEETS / 2 CONCERN / 0 FAIL**.
CONCERN: avance de progreso en "listo, continuemos" (defecto residual) y una
promesa futura en el turno de confirmación (el runtime sustituye el mensaje
por PROCESSING_MESSAGE). Español correcto, sin formato visual, sin
confirmación prematura en petición directa. Calibración humana pendiente
(el judge no se calibró contra revisión humana a escala).

### Spike de frameworks

| Framework | Multi-turn | Datasets/versionado | Sintético | Metamórfico | Judge | Evaluadores propios | Local | Egress/privacidad | Integración GCP/LangGraph | Coste/esfuerzo | Lock-in | Decisión |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Vertex Gen AI Eval (Agent Platform) | Sí (métricas multi-turn por rúbrica) | Dataset en GCS/BigQuery | No nativo | No nativo | Sí (rúbricas) | Sí (custom code metric remoto/local) | SDK Python | Datos en el proyecto GCP | Natural en Vertex; agnóstico del grafo | Medio | GCP | **DEFER** como complemento (requiere dependencia `google-cloud-aiplatform`) |
| Promptfoo | Parcial (conversation-relevance) | Configs YAML | No | No | Sí (llm-rubric, multi-judge) | Sí (python/js) | Sí, self-hosted (SQLite, 1 réplica) | Datos fuera salvo self-host | Ninguna nativa | Bajo | MIT/Node | **DEFER** (complemento CI si aparece la brecha) |
| DeepEval | Turn-by-turn | No en OSS | No | No | Sí | Sí (pytest) | Sí | Local | Ninguna | Bajo | Apache-2.0 | **REJECT** (no cubre multi-turn ni oráculos duros mejor que el harness) |
| LangSmith | Sí | Sí (hosted) | No | No | Sí | Sí | Parcial | Servicio externo por defecto | LangChain/LangGraph | Medio | Alto | **REJECT** (egress y lock-in; no aporta sobre el harness actual) |

Decisión: **KEEP CURRENT HARNESS**. Ningún framework cubre mejor los oráculos
deterministas, la privacidad y el corpus congelado; adoptar uno obligaría a
dependencia nueva y a duplicar capas sin resolver una brecha material. La
opción complementaria propuesta para un ciclo futuro es Vertex Gen AI
Evaluation con métricas de código custom (dev-only).

### Coste de la campaña

~900 llamadas a `gemini-3.5-flash-lite` (ablación 225, A/B 260, sintética
dev 90, held-out 35, metamórfica 86, probes/judge 40, full paired y reruns
~160), ~3.6M tokens de entrada y ~0.1M de salida. Con precios públicos
aproximados de Flash-Lite (0,075/0,30 USD por millón) el coste estimado es
**< US$0,50**, dentro del presupuesto de US$5. No se consultó la tarifa
vigente en esta sesión: es una estimación.

### Gates

```text
python -m pytest            715 passed
python -m ruff check .      All checks passed
python -m ruff format --check .  144 files already formatted
python -m mypy app          Success: no issues found in 30 source files
python -B evals/conversation_eval.py --validate-only  cases=50 problems=0
git diff --check            limpio
docker build                OK (digest sha256:104f572b… re-verificado con los
                            templates del harness y el módulo few_shot_min)
```

### Veredicto de la iteración final pre-voz

```text
INCONCLUSIVE — OWNER DECISION REQUIRED
NOT MERGED TO DEV / NOT PUSHED
```

Gate §35: 0 críticos ?; 0 confirmación prematura reproducible ? (persiste en
sintética/held-out y en el caso golden `promise-capability-distinction` de
algunas muestras); 0 stale cancel/re-request reproducible ? (corpus y capas
sintéticas pasan; la cancelación por negativa es el defecto restante);
**0 avance procedimental por side question reproducible ?** (persiste
`side-question-return` 2–3/3 en cada variante y en ambos idiomas); 0 promesa
futura no respaldada reproducible ? (canon aplicado; el único CONCERN del
judge es un turno sustituido por el runtime). El owner debe decidir entre una
iteración acotada a la clase "continuación genérica + confirmación prematura",
aceptar con las desviaciones declaradas, o rechazar. Cloud Run, secretos,
XCALLY y caching siguen sin tocarse.

## Cierre pre-E2E — cobertura XCALLY, aprovisionamiento TIVIT y validación EN

XML autoritativo: `CU013_HelpDesk_IVR_Agents.xml` (Downloads, 55 377 bytes,
sha256 `f2859230…`), 81 bloques; es el que contiene `Switch_NEXT_STEP`,
`GetDigits_DOCUMENTO` y `GetDigits_START_DATE` con `retry="3"`. El defecto de
rama combinada está confirmado: la arista 837 de `Switch_NEXT_STEP` tiene valor
`"TRANSFER, COMPLETE"` (target `Clear_EXIT_DOCUMENTO`), con `-` ? default ?
`Set_LOCAL_TRANSFER`; `GoToIf_EXIT_COMPLETE` ya existe y ramifica
true ? `Hangup_COMPLETE`, false ? `GoTo_HELPDESK`. Los 11 bloques CU013
(`Rest_TURN`, `Rest_VOICE_FAILURE_*`, `Rest_EVENT_*`) apuntan a la tag
`e2e-4b72dfa` y ya llevan `X-Request-ID: {UNIQUEID}` y
`X-CU013-Response-Contract: next-step-v1`.

### Matriz de cobertura (extracto por clase)

| Ruta/estado XML | Clasificación | Capa de cobertura | Gap |
|---|---|---|---|
| WELCOME, ASR_LISTEN, TTS, cleanup, hangup | XCALLY-MECHANICAL | E2E only | ninguno |
| NO_SPEECH / LOW_CONFIDENCE (`Rest_VOICE_FAILURE_*`) | EXTERNAL-INTEGRATION | tests de voice-retry + E2E | E2E |
| Rest_TURN HTTP failure / message playback | RUNTIME-DETERMINISTIC + XCALLY-MECHANICAL | taxonomía de errores + E2E | E2E |
| LISTEN (side questions, ambigüedad) | MODEL-SEMANTIC | golden + metamorphic + synthetic + fresh | defecto residual conocido |
| COLLECT_IDENTITY | MODEL-SEMANTIC + RUNTIME-DETERMINISTIC | golden + synthetic + held-out + fresh | ninguno |
| EXECUTE_ACTION, dispatch/poll HTTP error | RUNTIME-DETERMINISTIC | guards + polling tests | E2E RD |
| POLL_RD, ACCOUNT_ACTION_STATUS, pending/terminal/unknown, budget | RUNTIME-DETERMINISTIC + EXTERNAL-INTEGRATION | tests de máquina de operación + integration-events | E2E RD |
| DELIVER_PASSWORD, password/email present/usable, PRESENTATION_RESULT | EXTERNAL-INTEGRATION | tests de presentación + E2E | E2E SendMail |
| TRANSFER / COMPLETE / default | XCALLY-MECHANICAL | fix manual del owner | owner |
| GetDigits retries, date mismatch, FOUND/NOT_FOUND | XCALLY-MECHANICAL / EXTERNAL-INTEGRATION | events tests + E2E | E2E |
| identity VALID/INVALID/TECHNICAL_FAILURE/exhausted | RUNTIME-DETERMINISTIC + MODEL-SEMANTIC | golden identity + synthetic | ninguno |

Ningún gap **MODEL-SEMANTIC** nuevo: los dos defectos residuales ya están
cubiertos por golden/synthetic/held-out/fresh.

### Procedencia de los datasets (auditoría)

- **Golden**: corpus versionado escrito a mano (familias semánticas), ampliado
  con casos de ambigüedad y re-request; independiente de bugs históricos.
- **Metamórfica**: generada por transformación determinista de 6 familias
  golden (filler, frustración, repetición, autocorrección, contexto
  irrelevante, cierre coloquial, duración); no es LLM-generated.
- **Synthetic dev / held-out**: bancos de enunciados y tabla de composición
  **autorados por el modelo Implementer** con composición determinista; no
  combinatoria pura (fases, ruido y capacidades) ni variantes de bugs.
- **Fresh robustness (nuevo, congelado antes de Gemini)**: 59 escenarios
  autorados por el Implementer con bancos nuevos (cooperativo, poco claro,
  mínima respuesta, confusión reset/unlock, frustración, autocorrección,
  retomar tras explicación, dato necesario, qué sigue, humano, otra
  capability, cancel/re-request, procedimiento guiado), `seed
  fresh-2026-09-25`, sha256 `09a44e71…`.
- **Judge**: modelo Implementer con rúbrica corta; no Gemini.

### Aprovisionamiento y validación

Pendiente de ejecución al cierre de esta sección; se registrarán recursos,
hashes, digest, revisión, DRS, focal/full/robustez EN, latencia y handoff.

### Ejecucion pre-E2E (resultados)

- **Aprovisionamiento TIVIT**: Artifact Registry `cu013-containers-dev`
  creado; secretos `cu013-api-key-dev` (v2 valida; v1 con salto de linea,
  deshabilitada), `cu013-protocol-reset-password-dev:1` y
  `cu013-protocol-unlock-account-dev:1` (hashes verificados byte a byte);
  `secretAccessor` solo a `cu013-cloud-run-sa`; imagen del SHA `e8f77ac`
  (`sha256:7f3352ff...`); revisiones `00002-dll` (fallo de arranque por la
  ruta de montaje, corregida), `00003-4lp` (sana, API key v2) y `00004-zld`
  (min=1, tag `e2e-en`); URL de tag
  `https://e2e-en---cu013-runtime-dev-ziubw4l2pq-ue.a.run.app`; trafico
  estable 100% en la ultima revision; `--allow-unauthenticated` aceptado (sin
  DRS). Montaje: cada protocolo en su propio arbol (Cloud Run rechaza dos
  secretos en el mismo directorio) con variables `CU013_PROTOCOL_*_FILE`.
- **Verificacion**: `verify-dev-benchmark.ps1 -ExpectedMinInstances 0` todo
  PASS; `/turns` sin API key 401 (fail-closed, sin Gemini); OpenAPI 200; sin
  warnings en logs.
- **Focal EN**: 58 repeticiones validas, 0 criticos, cancel/re-request y
  promesas limpias; fallos de clases preexistentes (vocabulario de
  confirmation_state, oraculo de ruta afirmativa, escalamiento por fallo).
- **Full paired EN** (129c793 baseline vs EN congelado): 189 pares validos,
  0 INFRA, 0 criticos, 0 regresiones objetivo, 3 no objetivo
  (`long-conversation-memory` turn5), 3 pares incompletos (caso nuevo del
  corpus ausente en el artefacto baseline, declarado como confounder);
  `procedure_current` FAIL 18 a 6, `confirmation_state` 10 a 3; latencia
  modelo p50 -110 ms / p95 -235 ms en la muestra (sin causalidad); tokens de
  prompt +1469 p50. Veredicto del comparador: NEEDS OWNER DECISION por los
  pares incompletos y las 3 regresiones del turn5.
- **Robustez EN**: metamorfica invariance 1.0 (39 casos, 0 divergencias);
  sintetica dev 39/3/1 de 43; held-out 31/4 de 35 (2 defectos de oraculo del
  generador + 2 reales); fresh 48/10/1 de 59 (2 defectos de oraculo + 8 reales:
  6 aperturas prematuras de challenge ante respuesta minima/lateral y 2
  re-requests con wording debil que no recrean el goal).
- **Judge EN**: ~10 MEETS / 2 CONCERN / 0 FAIL; salida estable en espanol.
- **Latencia Cloud Run**: 30/30 peticiones, 0 errores; round-trip p50 1031 ms
  / p95 1438 ms (total de cliente, incluye red y modelo).

### Veredicto pre-E2E

```text
INCONCLUSIVE — OWNER DECISION REQUIRED
```

El entorno TIVIT esta aprovisionado, desplegado, verificado y con tag
caliente `e2e-en`; EN tiene 0 criticos, 0 regresiones objetivo, sin promesas
no respaldadas y salida estable en espanol, con `procedure_current` y
`confirmation_state` mejores que el baseline. No alcanza el gate estricto de
§25: persisten (a) apertura prematura de challenge ante respuestas minimas o
laterales y (b) re-request con wording debil que no recrea el goal (casos
fresh); ambas sin efecto lateral ni critical. El owner decide si ejecuta el
E2E aceptando estos defectos conocidos o pide una iteracion acotada.
