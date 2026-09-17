# CU013 v0.2.0 — Contexto actual

## Propósito y alcance actual

CU013 reconstruye el backend conversacional de Mesa de Ayuda para XCALLY Motion y Cally Square. El repositorio contiene autoridad documental, estándares de ingeniería, configuración no sensible, herramientas operativas reproducibles para DEV y experimentación, y el núcleo productivo mínimo del Thin Session Repository integrado y committeado en `app/session`. El repositorio integra en `app/api` un baseline DEV provisional del boundary HTTP para Cally Square, en `app/conversation` el motor real Gemini 2.5 Flash-Lite detrás del seam con su prompt versionado en `app/conversation/prompts.py`, en `evals/` el benchmark de latencia, el probe de política conversacional y el runner eval-driven del corpus de conversación, y en `ops/gcp/` el tooling de Cloud Run. El servicio Cloud Run DEV ya existe desplegado; todavía no existe integración XCALLY/Cally Square real ni AD/TIVIT. El primer turno de voz XCALLY real fue diagnosticado read-only ([Experimento 0005](docs/experiments/0005-xcally-voice-turn-diagnosis.md)) y su corrección acotada de política conversacional está implementada, probada y committeada, pendiente de deploy y revalidación de voz.

La iteración anterior materializó como autoridad de producto las decisiones consolidadas aprobadas por el owner (la consolidación aprobada en sesión es la fuente usada; el planning numerado Q1–Q18 no existe como artefacto persistido): invariantes transversales en [system.md](docs/specs/system.md), comportamiento del primer slice en [account-actions.md](docs/specs/account-actions.md) (incluida la excepción owner a IOP-MDA-012), [ADR-0010](docs/decisions/0010-durable-semantic-plan-separate-from-authorization.md) con la separación plan/autorización/confirmación/verdad, la metodología eval-driven en [testing.md](docs/engineering/testing.md), el corpus versionado `evals/conversation/` con su runner baseline, y las skills `conversation-evaluation` y `xcally-voice-validation`.

Esta iteración materializó las nuevas owner decisions y el candidate semantic runtime: las peticiones no soportadas o fuera de alcance ya no implican handoff (ESCALATE no es fallback de clasificación ni de alcance), la petición explícita de persona escala en el primer intento sin cancelar el goal, el fallo técnico de identidad queda sin oráculo de ruta, una pregunta lateral no abre ni reabre el challenge HITL, un challenge invalidado nunca se reutiliza y la cancelación del goal se evalúa por efecto semántico. El runtime durable schema v2, la migración v1→v2 fail-closed y los guards de legalidad quedaron implementados, probados y committeados, con la evaluación real-model registrada en el [Experimento 0006](docs/experiments/0006-semantic-runtime-evaluation.md).

El primer corte de acciones de cuenta es `RESET_PASSWORD` + `UNLOCK_ACCOUNT`, sin prioridad obligatoria entre ambas.

## Pila y entorno

- Python 3.12, FastAPI, Pydantic 2, LangGraph y `google-genai`/Vertex AI.
- Firestore como único almacén durable aceptado.
- Cloud Run como cómputo DEV desplegado (`min=0` en reposo; `min=1` sólo en ventanas autorizadas de benchmark o de validación DEV de voz controlada).
- Docker, GitHub Actions, pytest, Ruff y MyPy.
- Proyecto GCP: `cu013-xcally-agentic`.
- Región primaria: `us-east1`.

## Infraestructura actual

Infraestructura GCP aprovisionada y confirmada por el propietario:

- APIs requeridas habilitadas;
- Firestore `(default)`, Native/Standard, `us-east1`;
- Artifact Registry `cu013-containers-dev`, `us-east1`;
- cuentas de servicio dedicadas para experimento, ejecución y despliegue;
- base IAM de siete asignaciones.

IAM y diseño de impersonación ADC configurados:

- identidad exclusiva `cu013-spike-firestore` para el experimento;
- acceso `roles/datastore.user`;
- autenticación local prevista mediante impersonación ADC, sin claves JSON de cuentas de servicio.

Validación ADC y lectura Firestore desde el host real de OpenCode: aprobada por el propietario con Python 3.12.2, `.venv` en Python 3.12.2 y `GOOGLE_APPLICATION_CREDENTIALS` sin definir. La impersonación ADC, el refresh de ADC mediante `google-auth` y la lectura read-only de Firestore `(default)` fueron correctos; el documento de prueba no existía.

Desde el 16-09-2026 el ADC local impersona la identidad prevista de runtime `cu013-runtime-dev` (`roles/datastore.user` + `roles/aiplatform.user`) para la ejecución DEV del motor real; el propietario concedió `roles/iam.serviceAccountTokenCreator` sobre esa SA. `cu013-spike-firestore` sigue como identidad exclusiva de experimentos. Sin claves JSON de cuentas de servicio en ningún caso.

La ausencia de valores locales predeterminados como `compute/region` o `artifacts/location` sigue siendo una desviación menor de la estación de trabajo, no un bloqueo arquitectónico.

Servicios habilitados y materializados en DEV:

- Cloud Run `cu013-runtime-dev` desplegado en `us-east1`, con `min=0` en reposo y acceso sin IAM de caller (PROVISIONAL: la autenticación real del boundary sigue siendo `X-API-Key`);
- Secret Manager con el secreto DEV `cu013-api-key-dev` (versión activa 2; el valor nunca fue leído ni impreso por agentes);
- Vertex AI con el motor real Gemini 2.5 Flash-Lite y ambos benchmarks ejecutados; la evaluación comparativa de modelos sigue pendiente.

## Estado arquitectónico actual

- v0.2.0 es una arquitectura nueva y un monolito modular.
- LangGraph es el marco aceptado para orquestación de turnos.
- Los IOP corporativos locales son la autoridad del procedimiento empresarial y tienen un [manifiesto versionado](docs/iop/README.md).
- `RESET_PASSWORD` permite autoservicio guiado y acción directa autorizada después de validar identidad.
- `UNLOCK_ACCOUNT` no tiene autoservicio; la acción directa autorizada usa XCALLY/Cally Square → Orchestrator/TIVIT/AD.
- CU013 no integra tickets ITSM; el registro en herramientas de gestión está fuera del límite técnico del backend.
- La validación de identidad comienza con documento y fecha de nacimiento por DTMF.
- Los valores DTMF crudos quedan fuera del LLM y de los registros, y se minimizan en persistencia.
- SendMail está Deferred. La secuencia aceptada es: baseline de voz XCALLY → integración AD/TIVIT → depuración guiada por logs y pruebas con callers → SendMail. CU013 sólo recibirá el estado del envío.
- [ADR-0009](docs/decisions/0009-use-thin-firestore-session-repository.md) acepta Thin Firestore Session Repository: cargar un `SessionRecord` semántico, construir un `GraphState` efímero, ejecutar LangGraph sin persistent checkpointer, consolidar y guardar antes del HTTP response.
- La Opción A resultó viable experimentalmente, pero fue descartada para el voice path productivo por latencia, amplificación de escrituras, complejidad de persistencia/retención y acoplamiento a LangGraph.
- El security floor productivo está resuelto en `langgraph>=1.0.10` y `langgraph-checkpoint>=4.1.1`; el lock exacto está fijado en [requirements.lock](requirements.lock) con `langgraph==1.2.11`, `langgraph-checkpoint==4.2.0` y `google-cloud-firestore==2.30.0`.
- El núcleo productivo mínimo del Thin Session Repository está integrado y committeado en `app/session`: contrato durable cerrado, grafo LangGraph determinista sin persistent checkpointer y 1 load + 1 save por turno normal.
- El `SessionRecord` schema v2 materializa [ADR-0010](docs/decisions/0010-durable-semantic-plan-separate-from-authorization.md): plan conversacional durable pre-auth, autorización de identidad con TTL absoluto de 30 minutos, challenge de confirmación por operación, guard de despacho durable y verdad de operación externa, en planos separados con whitelist cerrada y migración v1→v2 fail-closed. Los guards deterministas rechazan rutas y claims ilegales sin segunda llamada al modelo, existe como máximo una operación externa activa y `UNKNOWN` no se redespacha automáticamente.
- El boundary HTTP XCALLY↔CU013 está implementado en el worktree como baseline DEV `PROVISIONAL` y tipado en [Boundary HTTP XCALLY↔CU013](docs/specs/xcally-boundary.md): `POST /api/v1/conversations/{conversation_id}/turns`, variantes transcript ASR e `IDENTITY_DATA`, autenticación `X-API-Key` sólo desde entorno, `turn_id` único por request y errores con taxonomía segura. No es el contrato integrado final.
- El transcript es efímero y no se persiste; el DTMF crudo queda contenido en el boundary (no se persiste, registra, devuelve ni alcanza al seam) y nunca marca `identity_validated=True`.
- El primer motor real es `GeminiTurnModel` (`app/conversation`): Vertex AI sobre ADC, `thinking_budget=0`, output estructurado tipado `ModelTurnDecision` (`message`, `route`, propuesta de plan, `confirmation_request`, observación de confirmación, causa de handoff y claims), una llamada y un attempt por turno normal, sin streaming ni tools. El prompt del sistema vive versionado en `app/conversation/prompts.py` (sin framework de prompts ni config dinámica) e incluye la política de petición previa, la precedencia de la necesidad inmediata, la preservación del goal ante una petición de persona, la redirección de alcance sin handoff y la clasificación de la confirmación HITL como principios generales. El grafo del turno es `START → run_model → advance_turn → END`; el modelo sugiere, el runtime decide, y ningún nodo runtime reescribe `route`.
- La validación positiva de identidad sigue sin integración; `IDENTITY_DATA` termina de forma segura con `dependency_unavailable`.
- El [Experimento 0003](docs/experiments/0003-gemini-baseline-latency.md) midió el camino real desde host DEV (30 requests secuenciales, 0 errores): handler p50 1 281 / p95 1 922 ms; load p50 219 / p95 421 ms; modelo p50 782 / p95 1 062 ms (máx 4 094 ms); save p50 234 / p95 266 ms. Es un baseline DEV, no un SLO: no incluye ASR/TTS/red XCALLY ni Cloud Run in-region.
- El [Experimento 0004](docs/experiments/0004-cloud-run-latency.md) midió el baseline in-region en Cloud Run `us-east1` con una instancia warm (revisión `00006-hn4`, digest `sha256:6ca03e…`): 30/30 requests medidas con 0 errores; handler p50 657 / p95 920 ms; load p95 36 ms; modelo p50 595 ms; save p95 102 ms; round-trip HTTPS del cliente p50 878 / p95 1 145 ms. `min=0` restaurado y verificado read-only.
- Gemini 2.5 Flash-Lite con razonamiento desactivado sigue como referencia temporal.
- No existen Terraform ni infraestructura adicional; el contenedor (`Dockerfile`) y el servicio Cloud Run DEV existen con `min=0` en reposo. El código de ejecución es el núcleo de sesión, el boundary HTTP y el motor real.

## Puntos de entrada del repositorio

- [Especificación del sistema](docs/specs/system.md)
- [Especificación de acciones de cuenta](docs/specs/account-actions.md)
- [Boundary HTTP XCALLY ↔ CU013](docs/specs/xcally-boundary.md)
- [Decisiones arquitectónicas](docs/decisions/)
- [Gaps de implementación](docs/gaps.md)
- [Estándares de ingeniería](docs/engineering/)
- [Manifiesto de IOP locales](docs/iop/README.md)
- [Runbook de inicialización GCP](docs/runbooks/gcp-dev-bootstrap.md)
- [Corpus de evaluación conversacional](evals/conversation/README.md)
- [Experimento Firestore/LangGraph](docs/experiments/0001-firestore-langgraph-checkpointer.md)
- [Experimento Thin Session Repository](docs/experiments/0002-firestore-thin-session-repository.md)
- [Experimento Gemini baseline de latencia](docs/experiments/0003-gemini-baseline-latency.md)
- [Experimento Cloud Run baseline](docs/experiments/0004-cloud-run-latency.md)
- [Experimento diagnóstico de voz XCALLY](docs/experiments/0005-xcally-voice-turn-diagnosis.md)
- [Runbook Cloud Run DEV benchmark](docs/runbooks/cloud-run-dev-benchmark.md)
- [Núcleo Thin Session](app/session/)
- [Benchmark de latencia DEV](evals/backend_latency.py)
- [Runner baseline de conversación](evals/conversation_baseline_eval.py)
- [Cliente E2E Cloud Run](evals/cloud_run_latency.py)
- [Lock reproducible](requirements.lock)
- [`config.yaml`](config.yaml)

## Implementado, validado y pendiente

Implementado en el repositorio:

- especificaciones separadas y decisiones atómicas;
- semántica cerrada para reset, desbloqueo y límite de ticketing;
- gaps AD/TIVIT separados de la evidencia documental y centralizados en `docs/gaps.md`;
- manifiesto versionado para IOP locales de sólo lectura;
- estándares de Python, fiabilidad y pruebas;
- configuración ejecutable de Ruff, MyPy y pytest en `pyproject.toml`;
- descubrimiento explícito del paquete `app` en `pyproject.toml`, con instalación editable verificada en un entorno limpio;
- base GCP y decisión de inicialización documentadas;
- configuración no sensible;
- guion reproducible de inicialización y verificador de sólo lectura;
- Experimentos 0001 y 0002 preservados como evidencia histórica `Completed`;
- ADR-0009 Accepted y specs reconciliadas con `SessionRecord` durable, `GraphState` efímero y save antes del response;
- núcleo productivo mínimo del Thin Session Repository en `app/session`: `SessionRecord` semántico con whitelist cerrada, `pending_operation` durable, `GraphState` efímero, grafo LangGraph determinista de un nodo sin persistent checkpointer, repositorio async de Firestore con seam documental estrecho y servicio de turno con exactamente 1 load + 1 save antes de devolver control;
- runtime semántico durable schema v2 en `app/session`: plan conversacional pre-auth, autorización de identidad con TTL absoluto, challenge de confirmación por operación, guard de despacho y verdad de operación externa en planos separados; migración v1→v2 fail-closed; guards deterministas de ruta, claims y despacho (causas de handoff cerradas a solicitud del caller y fallo terminal); suite de legalidad determinista sin modelo ni credenciales;
- runner eval-driven del corpus con clasificación PASS/FAIL/NOT ORACLED/NOT REPRESENTABLE/INFRA, validación estática `--validate-only` sin ADC, semántica `UNSPECIFIED`/`not_valid`/`not_oracled` y medición de latencia y tokens por componente before-vs-after;
- suite determinista de 34 tests con doble en memoria y fake del cliente async; sin Gemini, XCALLY, AD/TIVIT ni credenciales;
- baseline DEV provisional del boundary HTTP XCALLY↔CU013 implementado en el worktree bajo `app/api`, con contrato Pydantic 2, autenticación `X-API-Key` sólo desde entorno, `turn_id` por request, errores con taxonomía segura y OpenAPI coherente con las respuestas reales;
- seam `ConversationEngine` en `app/conversation` como único punto de extensión para el motor Gemini, sin NLU determinista ni respuestas semánticas falsas;
- política conversacional de petición previa en `app/conversation/prompts.py`: el prompt salió de `gemini.py`, que queda centrado en provider/config/transporte/parsing; la regla responde la pregunta antepuesta con `CONTINUE` y sólo después procede a `COLLECT_IDENTITY`, sin keywords ni regex y sin cambiar modelo, schema ni número de llamadas;
- cobertura determinista de la política: el prompt documenta las rutas cerradas y los campos de la decisión, y la política precede a la regla de identidad; el boundary conserva la ruta `CONTINUE` del modelo y demuestra que una intención de acción previa a identidad permanece transitoria (blocker `CNV-001`);
- motor real `GeminiTurnModel` detrás del seam: Vertex AI con ADC, baseline reemplazable en un solo objeto (`project`, `location`, `model`, `api_version`, `thinking_budget=0`, `timeout_ms`, `attempts=1`), output estructurado tipado y errores del modelo traducidos a la taxonomía segura (`dependency_timeout` 504, `dependency_unavailable` 503, salida inválida → `internal` 500);
- seam `TurnMetrics` PII-safe (segmentos con nombres fijos y contadores sólo de tokens) y composition root DEV `app/main.py` con clientes async de Vertex y Firestore reutilizados y cerrados en el lifespan;
- benchmark real `evals/backend_latency.py`: 5 warmups + 30 requests secuenciales medidos a través del boundary FastAPI contra Firestore y Vertex reales, con segmentación por etapa y conteo de tokens, sin registrar transcript, DTMF ni texto generado;
- suite determinista del boundary: contrato cerrado y rutas fuera del enum rechazadas, API key válida/incorrecta/ausente/no configurada, `IDENTITY_DATA` sin fuga de DTMF, payloads inválidos sin eco de transcript ni DTMF, identidad de sesión desde la ruta, `turn_id` distinto por request, `X-Request-ID` no usado como idempotency key y errores internos traducidos a contrato seguro;
- lock productivo exacto y reproducible en `requirements.lock`, con revisión de advisories OSV sin hallazgos abiertos;
- contenedor productivo mínimo (`Dockerfile`, `.dockerignore`): Python 3.12 slim, un solo proceso uvicorn con entrypoint factory, usuario non-root, instalación runtime con el lock; `uvicorn` como dependencia runtime (lock regenerado, 70 pins, OSV limpio);
- tooling Cloud Run DEV versionado en `ops/gcp/`: deploy idempotente con tag = SHA limpio y secreto por versión numérica, stop que restaura `min=0`, verificación read-only, rotación segura de la clave de benchmark y runbook asociado;
- logging estructurado PII-safe del servicio (`StructuredLogTurnMetrics`) para recuperar la segmentación server-side desde Cloud Logging sin plataforma de observabilidad;
- ningún saver, harness, double, fixture, collection prefix o código runtime de los spikes integrado en `dev`;
- worktrees y ramas locales `spike/firestore-checkpointer` y `spike/firestore-thin-session-repository` retirados; no existían ramas remotas `spike/*`.

Validado localmente el 15-09-2026:

- integridad SHA-256 de los dos IOP y coincidencia exacta de nombres;
- PDF de IOP ignorados por Git y manifiesto versionable;
- Python 3.12.2 en `.venv` e instalación editable DEV correcta que expone `app` fuera del worktree;
- impersonación ADC, refresh `google-auth` y lectura read-only de Firestore validados desde el host real por el propietario;
- gates aprobados con el entorno fijado por el lock: 34 tests deterministas, Ruff 0.16.7 check/format y MyPy 1.20.2 strict sobre `app`;
- pytest 9.1.1 y pytest-asyncio 1.4.0 con `asyncio_mode = "auto"`;
- `requirements.lock` reproducido en un `.venv` limpio: 68 pins exactos, sin desviaciones ni extras, y gates repetidos allí;
- advisory review con OSV querybatch sobre los 68 pins: sin advisories abiertos; `langgraph==1.2.11` y `langgraph-checkpoint==4.2.0` por encima del security floor;
- limpieza Firestore: inventario read-only de 21 root collections `cu013spike_meas_*`, 111 documentos borrados documento a documento con allowlist exacta y verificación posterior de 0 documentos; sin wildcards, collection-group deletes ni TLS deshabilitado;
- sintaxis PowerShell y estructura YAML de la iteración anterior;
- enlaces Markdown, límites documentales, ausencia de atajos TLS y consistencia de artefactos;
- Option A medida contra Firestore real: ~29 RPC, 28 escrituras, ~17,6 KB y run p50 4,738 s / p95 4,805 s por turno trivial.
- Option B medida contra Firestore real: 2 RPC, 1 lectura + 1 escritura, ~630 bytes y run p50 485,5 ms / p95 941,6 ms; continuidad, interrupción antes del save, `pending_operation` sintética y last-writer-wins validados sin retries, `ABORTED` o 429.
- gates del boundary HTTP: 66 tests deterministas, Ruff 0.16.7 check/format y MyPy 1.20.2 strict sobre `app` (13 archivos), sin regresión de los 34 tests Thin Session;
- contrato OpenAPI del endpoint coherente con las respuestas reales (401/422/500/503 con `ErrorResponse`);
- closeout documental: enlaces locales válidos, diff check y escaneo de secretos limpios.

Validado localmente el 16-09-2026:

- gates de la iteración Gemini: 99 tests deterministas (34 Thin Session + 32 boundary + 33 modelo/sesión nuevos), Ruff 0.16.7 check/format y MyPy 1.20.2 strict sobre `app` (17 archivos);
- ADC impersonación de `cu013-runtime-dev` verificada sin imprimir tokens; lectura read-only de Firestore y llamada mínima a `gemini-2.5-flash-lite` con `thinking_budget=0` correctas (`FinishReason.STOP`);
- benchmark real completado: 5 warmups + 30 requests medidos secuenciales (13 RESET + 13 UNLOCK + secuencia multi-turn de 4), 0 errores, segmentación p50/p95 por etapa, conteos de tokens y continuidad durable multi-turn verificada (`turn_count=4`, un solo documento);
- bloqueo de auth registrado y resuelto por el propietario: ADC `cu013-spike-firestore` sin `aiplatform.endpoints.predict` y falta de `iam.serviceAccounts.getAccessToken` sobre `cu013-runtime-dev`; sin cambios de IAM realizados por el agente;
- benchmark in-region completado (Experimento 0004): 30/30 requests por HTTPS real con 0 errores/timeouts (p50 handler in-region ≈657 ms; p50 cliente ≈878 ms) y tag == HEAD, digest y secreto (`cu013-api-key-dev:2`, sólo nombre/versión) verificados read-only;
- ventana warm cerrada: `min=0` restaurado con el script de stop y verificado read-only; inventario de `cu013dev_sessions`: 97 documentos (33 de la corrida Cloud Run + 1 audit + 63 de las corridas locales), sin borrados, con la corrección 54→63 anotada en el Experimento 0003.
- diagnóstico read-only del primer turno de voz XCALLY real (Experimento 0005): revisión `00008-7gz` servida == `2a37b2a`, idéntica a HEAD en `app/`; logs PII-safe correlacionados en ventana estrecha con única request; métricas OBSERVED/DERIVED/NOT AVAILABLE; `SessionRecord` read-only con `turn_count=1`, `identity_validated=False` y sin acción pendiente; origen de `COLLECT_IDENTITY` demostrado en la regla de prompt y ausencia de NLU por keywords/regex;
- corrección de política conversacional con gates: 112 tests deterministas, Ruff 0.16.7 check/format y MyPy 1.20.2 strict sobre `app` (18 archivos); probe real focalizado (fuera de CI), 5/5 `CONTINUE` en el caso compuesto, control directo hacia `COLLECT_IDENTITY` y pregunta previa aislada con `CONTINUE`.

Validado el 16-09-2026 (iteración de materialización de política y harness):

- gates: 112 tests deterministas, Ruff check/format y MyPy strict sobre `app` sin regresión;
- baseline real-model del corpus (manual, fuera de CI, `gemini-2.5-flash-lite`, `thinking_budget=0`): familias OK en direct-supported-request, side-question-before-action (3/3 en el caso 0005 con controles), side-question-during-plan, goal-cancellation, caller-asks-human, caller-does-not-ask-human, identity-unvalidated/expired, confirmation-negation/silence/ambiguous/stale, late-result, unknown-dispatch-result, multi-turn-continuity y asr-paraphrase-noise; mismatches de ruta esperados en goal-switch/correction, multiple-goals, unsupported-request, identity-validated/technical/three-failures, pending-operation, confirmed-success/failure, duplicate-replay y reset-delivery: todos en propiedades que el contrato actual del modelo no puede expresar (`NOT REPRESENTABLE IN CURRENT CONTRACT`) o que requieren el estado durable de [ADR-0010](docs/decisions/0010-durable-semantic-plan-separate-from-authorization.md); ningún mismatch invalida la política aceptada;
- el runner del corpus usa PyYAML, ya presente en el lock; sin cambios de dependencias.

Validado el 17-09-2026 (iteración de owner decisions y semantic runtime):

- gates: 193 tests deterministas, Ruff 0.16.7 check/format (80 archivos) y MyPy 1.20.2 strict sobre `app` (18 archivos), `git diff --check` limpio y validación estática del corpus (34 casos, 0 problemas) sin ADC ni modelo;
- evaluación real-model del [Experimento 0006](docs/experiments/0006-semantic-runtime-evaluation.md) (manual, fuera de CI, `gemini-2.5-flash-lite`, `thinking_budget=0`): 34 casos / 30 familias × 3 repeticiones, con clasificación PASS/FAIL/NOT ORACLED/NOT REPRESENTABLE/INFRA; 21/30 familias sin fallo en la corrida canónica y los casos de owner decisions (unsupported sin handoff, cancelación semántica, fallo técnico de identidad sin ruta oraculada, side question sin challenge, challenge invalidado reemplazado) verificados; sin regresiones críticas (ningún despacho no autorizado, duplicado, resultado inventado, PII ni handoff ilegal en ninguna repetición);
- latencia/tokens before-vs-after medidos con el mismo runner y host DEV: el runtime semántico p95 ≈ 0 ms (máx 16 ms), prompt +≈287 tokens por llamada (+25 %) y completion sin cambio; multi-turn acumulado +≈24 %; sin regresión material de latencia y sin threshold nuevo;
- el Experimento 0006 registra las debilidades residuales del modelo (clasificación `AFFIRMATIVE`/`NEGATIVE`/`CORRECT`, preservación del goal en la petición de persona, precedencia de la necesidad inmediata y continuidad multi-turno) que pasan a la validación de voz DEV.

Pendiente:

- revalidar en voz DEV el prompt y el runtime semántico ya committeados (requiere autorización del owner para deploy; la revisión desplegada todavía contiene el prompt anterior y no el runtime v2);
- cerrar FS-002 con el reparto del presupuesto completo de voz (XCALLY/ASR/TTS); el rango in-region indicado es de centenas bajas de milisegundos por llamada;
- integrar la validación positiva de identidad (ID-001);
- evaluar Gemini 2.5 Flash-Lite y una alternativa antes del 16-10-2026, considerando las debilidades residuales de clasificación registradas en el Experimento 0006;
- validar los contratos externos aún abiertos antes de acciones de cuenta productivas;
- decidir el cleanup de los 97 documentos sintéticos de benchmark (requiere autorización explícita; sin wildcards ni collection-group deletes).

## Control operativo previo al experimento

El propietario confirmó desde el host real la cadena completa `ADC impersonation → google-auth refresh → Firestore read-only` con `cu013-spike-firestore` sobre el proyecto `cu013-xcally-agentic` y la base `(default)`. El control previo al experimento está aprobado.

El benchmark real de latencia del 16-09-2026 fue autorizado por el propietario y se ejecutó con ADC impersonando `cu013-runtime-dev`; las corridas locales y la corrida Cloud Run dejaron 97 documentos sintéticos bajo `cu013dev_sessions` que no fueron borrados. El despliegue y la ventana warm las ejecutó el propietario con el tooling versionado; el agente sólo hizo verificación y lecturas read-only. Nunca deshabilitar TLS ni la verificación de certificados para sortear el problema.

## Bloqueos y preguntas abiertas

- XC-001 abierto: existe un baseline HTTP provisional del turno, pero faltan la validación y el contrato integrado con el flujo Cally Square real y AD/TIVIT.
- Correlación, idempotencia, polling, reintentos y resultados tardíos (XC-002 a XC-004).
- Esquema completo de resultados XCALLY/Orchestrator/TIVIT/AD (XC-005) y mapeo exacto de estados externos a respuesta o escalamiento (XC-006).
- Resultado positivo de validación de identidad sin integración AD/TIVIT (ID-001).
- FS-002 abierto con evidencia local e in-region: load p95 421 ms (local) / 36 ms (Cloud Run) y save p95 266 ms (local) / 102 ms (Cloud Run); el rango indicado es de centenas bajas de milisegundos por llamada, pero falta el reparto del presupuesto completo de voz (XCALLY/ASR/TTS) para fijar el valor.
- La validación de TTL requiere permisos no concedidos a la cuenta de servicio del experimento.
- Debilidades residuales del modelo registradas en el [Experimento 0006](docs/experiments/0006-semantic-runtime-evaluation.md) (clasificación de la confirmación, preservación del goal ante una petición de persona, precedencia de la necesidad inmediata y continuidad multi-turno): no son fallos de legalidad del runtime y pasan a la validación de voz DEV.

SendMail permanece Deferred y fuera del alcance inmediato. Los valores predeterminados ausentes de la configuración local no son bloqueos arquitectónicos.

## Estado operativo y próximo gate

| Componente | Estado |
|---|---|
| Thin Session Repository | accepted + implemented |
| Boundary HTTP/XCALLY | implemented, PROVISIONAL |
| Gemini baseline | integrated |
| Cloud Run DEV | implemented; estado de reposo `min=0` |
| Experimento 0004 | completed |
| Experimento 0005 | completed (corrección de prompt committeada, pendiente deploy y revalidación de voz) |
| Experimento 0006 | completed (runtime semántico candidato, sin regresiones críticas; validación de voz DEV pendiente) |
| FS-002 | open |
| CNV-001 | resolved (schema v2 durable pre-auth + continuidad + correcciones/cancelación implementados y verificados; eliminado de `docs/gaps.md`) |
| Corpus conversacional y runner | 34 casos / 30 familias; clasificación PASS/FAIL/NOT ORACLED/NOT REPRESENTABLE/INFRA, validación estática sin ADC y medición de latencia/tokens before-vs-after |
| Próximo gate | validación de voz DEV del runtime semántico y del prompt committeados, tras commit y deploy autorizados |
| AD/TIVIT | después del baseline de voz XCALLY aislado |

El próximo objetivo de medición es el camino completo de voz, todavía no medido:

```text
caller
→ XCALLY/Cally Square
→ ASR
→ Cloud Run
→ Firestore
→ Gemini
→ Firestore
→ XCALLY
→ TTS
→ caller
```

La métrica objetivo de ese gate es `end-of-speech → first useful audio`. No añadir trabajo especulativo ni inventar contratos; AD/TIVIT no se integra antes de ese baseline de voz XCALLY aislado.

## Ciclo de vida

```text
iteración
→ implementación y pruebas
→ aceptación
→ actualizar CONTEXT
→ integrar/commit
```

No añadir a esta instantánea trabajo especulativo o no aceptado.

## Hitos anteriores

- Owner decisions y semantic runtime (esta iteración): peticiones no soportadas o fuera de alcance sin handoff automático, petición explícita de persona sin cancelar el goal, fallo técnico de identidad sin oráculo de ruta, side question sin challenge HITL, challenge invalidado nunca reutilizado y cancelación semántica; schema v2 durable, migración v1→v2 fail-closed, guards de legalidad, 193 tests deterministas y evaluación real-model registrada en el Experimento 0006; `CNV-001` resuelto.
- Política de producto materializada: invariantes transversales, HITL verbal con timeout/re-prompt, TTL de 30 minutos, excepción IOP-MDA-012, ADR-0010, corpus conversacional con runner y skills `conversation-evaluation`/`xcally-voice-validation`.
- Primer turno de voz XCALLY real diagnosticado read-only (Experimento 0005): revisión servida confirmada contra `app/`, logs correlacionados en ventana estrecha, `COLLECT_IDENTITY` originado en la regla de prompt, corrección acotada implementada y probada contra el modelo real, blocker `CNV-001` registrado y ya resuelto.
- Cloud Run DEV warm baseline medido (Experimento 0004): servicio desplegado con tag == SHA limpio, 30/30 requests por HTTPS real, in-region ≈mitad de la latencia local, `min=0` restaurado y verificado.
- Thin Session Repository (ADR-0009) y baseline DEV provisional del boundary HTTP XCALLY↔CU013 aceptados e implementados, con contención de DTMF y autenticación `X-API-Key`.
