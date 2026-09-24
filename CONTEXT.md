# CU013 v0.2.0 — Contexto actual

## Propósito y alcance actual

CU013 reconstruye el backend conversacional de Mesa de Ayuda para XCALLY Motion y Cally Square. El repositorio contiene autoridad documental, estándares de ingeniería, configuración no sensible, herramientas operativas reproducibles para DEV y experimentación, y el núcleo productivo mínimo del Thin Session Repository integrado y committeado en `app/session`. El repositorio integra en `app/api` un baseline DEV provisional del boundary HTTP para Cally Square, en `app/conversation` el motor activo Gemini 3.5 Flash-Lite detrás del seam (Vertex AI `global`, `MINIMAL`, clasificación procedimental obligatoria, memoria reciente de tres pares en carril sintético) con su prompt versionado en `app/conversation/prompts.py`, en `evals/` el benchmark de latencia, el laboratorio de evaluación conversacional (runner real-model, comparador pareado puro, corpus versionado de 47 casos / 39 familias, fingerprint calculado en runtime) y en `ops/gcp/` el tooling de Cloud Run. El servicio Cloud Run DEV ya existe desplegado; todavía no existe integración XCALLY/Cally Square real ni AD/TIVIT. El primer turno de voz XCALLY real fue diagnosticado read-only ([Experimento 0005](docs/experiments/0005-xcally-voice-turn-diagnosis.md)) y su corrección acotada de política conversacional está implementada, probada y committeada, pendiente de deploy y revalidación de voz.

La iteración anterior materializó como autoridad de producto las decisiones consolidadas aprobadas por el owner: invariantes transversales en [system.md](docs/specs/system.md), comportamiento del primer slice en [account-actions.md](docs/specs/account-actions.md) (incluida la excepción owner a IOP-MDA-012), [ADR-0010](docs/decisions/0010-durable-semantic-plan-separate-from-authorization.md) con la separación plan/autorización/confirmación/verdad, la metodología eval-driven en [testing.md](docs/engineering/testing.md), el corpus versionado `evals/conversation/` con su runner, y las skills `conversation-evaluation` y `xcally-call-evidence-analysis`.

Esta iteración materializó el **laboratorio de evaluación** y el **baseline conversacional activo** por el owner: el runner `evals/conversation_eval.py` con `scenario_kind` explícito (`independent_trial`/`sequence`), oráculos nulos como ausencia esperada y `NOT ORACLED` visible para campos ausentes, evidencia estructurada sanitizada por run/caso/repetición/turno, warmups fijos excluidos, INFRA por repetición, output estructurado inválido como fallo de modelo, fingerprint determinista de variante calculado desde `config.yaml` y código, y artefactos locales ignorados en `evals/results/`; el comparador pareado puro `evals/conversation_compare.py` con gate crítico duro, gates semántico y de eficiencia sin SLO inventado, fusión de reruns focalizados que no borra la evidencia original y plantilla de revisión manual de calidad hablada; el CI sin credenciales `.github/workflows/ci.yml`; y la skill `xcally-call-evidence-analysis` (post-hoc sobre una llamada ya ejecutada por el owner; nunca coloca llamadas ni monitoriza telefonía). La validación de harness quedó registrada en el [Experimento 0007](docs/experiments/0007-agent-evaluation-lab.md): 138 repeticiones válidas sin INFRA, 35/46 trials PASS, cero violaciones críticas y ningún cambio de comportamiento de producto. La selección del perfil activo vive en [ADR-0011](docs/decisions/0011-select-active-conversation-profile.md), el [Experimento 0009](docs/experiments/0009-conversational-memory-and-eight-callers.md) y Git; no existe manifiesto JSON canónico paralelo.

La iteración de integración materializó los **contratos backend para el flujo destino `TEST_XCALLY_CU013_API_APPROACH`**: el patrón command/event (`EXECUTE_ACTION` + `command` opaco en `/turns` y boundary técnico `/integration-events` con eventos PII-safe de identidad, canal de voz, estado y error de la operación externa), la máquina durable de operación sin duplicar enums, la política anti-silencio experimental y la retirada del DTMF crudo del contrato activo. La evidencia local vive en [Experimento 0010](docs/experiments/0010-integration-events-contract.md) y el contrato en [Boundary HTTP XCALLY↔CU013](docs/specs/xcally-boundary.md). No se modificó ningún XML XCALLY, no se llamó a RD/AD y no hubo deploy ni commit; el diseño Cally Square, el deploy coordinado y los caller tests E2E quedan pendientes.

La iteración `next-step-v1` materializó el contrato común de respuesta para la ventana E2E: selector explícito por header, envelope `{message, next_step, operation_state, command}` en ambos endpoints con el legacy intacto sin header, continuidad post-identidad sin segunda llamada al modelo, secuencia de polling con dedupe por fingerprint y presupuesto de 9 observaciones, `IDENTITY_INPUT_FAILURE`, hechos de presentación de contraseña, feedback de espera contextual por composer estrecho, contrato durable v3 con planos `polling` y `password_presentation` y wording aceptado fecha de ingreso.

Las llamadas reales del 23-09-2026 contra la revisión etiquetada (`00028-6rb`) cerraron el diagnóstico: 409 por evento sin turno, 422 por body fuera del contrato, y 200 servido con el envelope **legacy** porque el flujo no seleccionó el header. El hallazgo fue `HEADER_MISMATCH` (el Switch de XCALLY esperaba `next_step` y su rama por defecto transfirió; no fue atención humana) más un gap de observabilidad (los INFO de aplicación no llegaban a Cloud Logging). La corrección vigente: header canónico `X-CU013-Response-Contract` sin alias, `next_step` derivado del estado consolidado (goal pendiente sin autorización exige `COLLECT_IDENTITY`), bootstrap pre-turno v1 con create condicional y contador durable de voice retry, schema v4, rejection reasons tipados, proyección segura de 422 y topología de logging `cu013` con eventos cerrados. La última llamada real completó el camino feliz hasta RD (POST/GET 200/NONE con `CALLERID(name)=${UNIQUEID}` consistente) y el único fallo fue la representación numérica del boundary; se añadió una compatibilidad numérica estrecha (whitelist cerrada, strings decimales canónicas, sólo en el adapter v1) manteniendo el dominio y el carril legacy estrictos. Evaluación económica (deterministas/contrato/replay), sin full paired por no cambiar la semántica de decisión del modelo.

Existe un **experimental candidate** en la rama aislada `exp/prompt-protocols` (último SHA medido `f2421da`): composición modular (`core.md` + `catalog.md` + few-shot + protocolo runtime privado), proyección determinista del paso guiado, **proyección transitoria del estado durable** (`ModelStateProjection`, no persistida: identidad, confirmación pendiente y permisos de ejecución), tombstone semántico derivado para cancelación/re-request, ablación de few-shot F4/F2/F1/F0 (seleccionada F4) y fix de ambigüedad. Evaluación pareada de la Iteración A: **INCONCLUSIVE — OWNER DECISION REQUIRED** ([Experimento 0011](docs/experiments/0011-prompt-composition-runtime-protocols.md)): 192 pares válidos, 0 INFRA, 0 críticos, 0 regresiones objetivo, 1 mejora objetivo, 5 regresiones no objetivo (antes 8); cancelación/re-request resuelto y confirmación prematura eliminada en petición directa; persiste un defecto reproducible de avance procedimental ante continuación genérica. Memoria sin cambios: **NO MEMORY BLOCKER EVIDENCED**. Caching no ejecutado (manual anterior: explicit NOT APPLICABLE). **NOT merged to dev**; no hubo deploy, secretos nuevos ni E2E XCALLY.

El primer corte de acciones de cuenta es `RESET_PASSWORD` + `UNLOCK_ACCOUNT`, sin prioridad obligatoria entre ambas.

## Pila y entorno

- Python 3.12, FastAPI, Pydantic 2, LangGraph y `google-genai`/Vertex AI.
- Firestore como único almacén durable aceptado.
- Cloud Run como cómputo DEV desplegado (`min=0` en reposo; `min=1` sólo en ventanas autorizadas de benchmark o de validación DEV de voz controlada).
- Docker, GitHub Actions, pytest, Ruff y MyPy.
- Proyecto GCP: `cu013-xcally-agentic`.
- Región primaria: `us-east1`; ubicación del modelo: `global` (no confundir con infraestructura).

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
- Secret Manager con el secreto DEV `cu013-api-key-dev` (el valor nunca fue leído ni impreso por agentes);
- Vertex AI con el motor activo Gemini 3.5 Flash-Lite (ubicación de modelo `global`, `MINIMAL`); la selección se ejecutó en el carril sintético y su historia vive en ADR-0011, Experimento 0009 y Git.

## Estado arquitectónico actual

- v0.2.0 es una arquitectura nueva y un monolito modular.
- LangGraph es el marco aceptado para orquestación de turnos.
- Los IOP corporativos locales son la autoridad del procedimiento empresarial y tienen un [manifiesto versionado](docs/iop/README.md).
- `RESET_PASSWORD` permite autoservicio guiado y acción directa autorizada después de validar identidad.
- `UNLOCK_ACCOUNT` no tiene autoservicio; la acción directa autorizada usa XCALLY/Cally Square → Orchestrator/TIVIT/AD.
- CU013 no integra tickets ITSM; el registro en herramientas de gestión está fuera del límite técnico del backend.
- La validación de identidad comienza con la captura por DTMF del documento y el lookup externo por documento (`GET /validauser/TIVIT/{DOCUMENTO}`, `FOUND`/`NOT_FOUND`); tras `FOUND`, XCALLY captura la fecha de ingreso `DDMMYYYY` y la compara con `resposta2`. `FOUND` no equivale a identidad válida; el recorrido completo está pendiente de E2E (ID-001).
- Los valores DTMF crudos quedan fuera del LLM y de los registros, y se minimizan en persistencia.
- SendMail está Deferred. La secuencia aceptada es: baseline de voz XCALLY → integración AD/TIVIT → depuración guiada por logs y pruebas con callers → SendMail. CU013 sólo recibirá el estado del envío.
- [ADR-0009](docs/decisions/0009-use-thin-firestore-session-repository.md) acepta Thin Firestore Session Repository: cargar un `SessionRecord` semántico, construir un `GraphState` efímero, ejecutar LangGraph sin persistent checkpointer, consolidar y guardar antes del HTTP response.
- La Opción A resultó viable experimentalmente, pero fue descartada para el voice path productivo por latencia, amplificación de escrituras, complejidad de persistencia/retención y acoplamiento a LangGraph.
- El security floor productivo está resuelto en `langgraph>=1.0.10` y `langgraph-checkpoint>=4.1.1`; el lock exacto está fijado en [requirements.lock](requirements.lock) con `langgraph==1.2.11`, `langgraph-checkpoint==4.2.0` y `google-cloud-firestore==2.30.0`.
- El núcleo productivo mínimo del Thin Session Repository está integrado y committeado en `app/session`: contrato durable cerrado, grafo LangGraph determinista sin persistent checkpointer y 1 load + 1 save por turno normal.
- El `SessionRecord` schema v4 materializa [ADR-0010](docs/decisions/0010-durable-semantic-plan-separate-from-authorization.md): plan conversacional durable pre-auth, autorización de identidad con TTL absoluto de 30 minutos, challenge de confirmación por operación, guard de despacho durable y verdad de operación externa, más los planos separados `polling` (receipts de secuencia + fingerprint SHA-256, cadencia de feedback y hasta dos mensajes validados), `password_presentation` (voice, email solicitado, aceptación y entrega inicialmente `UNKNOWN`) y `voice_retry_count` (contador consecutivo PII-safe del bootstrap pre-turno), con whitelist cerrada y migración v1/v2/v3 fail-closed. Los guards deterministas rechazan rutas y claims ilegales sin segunda llamada al modelo, existe como máximo una operación externa activa y `UNKNOWN` no se redespacha automáticamente.
- El boundary HTTP XCALLY↔CU013 está implementado como baseline DEV `PROVISIONAL` y tipado en [Boundary HTTP XCALLY↔CU013](docs/specs/xcally-boundary.md): `POST /api/v1/conversations/{conversation_id}/turns` con transcript ASR y `POST /api/v1/conversations/{conversation_id}/integration-events` con eventos técnicos PII-safe, autenticación `X-API-Key` sólo desde entorno, `turn_id` único por request, `command` opaco sólo con `EXECUTE_ACTION` y errores con taxonomía segura. Un único dominio alimenta dos serializadores temporales: el legacy sin header y el envelope común `next-step-v1` seleccionado explícitamente. No es el contrato integrado final.
- El transcript es efímero y no se persiste; el DTMF crudo ya no existe en el contrato activo (Cally Square captura y valida), y nunca marca identidad validada.
- El primer motor activo es `GeminiTurnModel` (`app/conversation`): Vertex AI sobre ADC, ubicación de modelo `global`, `thinking_level=MINIMAL` sin `thinking_budget`, output estructurado tipado `ModelTurnDecision` (`message`, `route`, propuesta de plan, clasificación procedimental estructurada obligatoria, `confirmation_request`, observación de confirmación, causa de handoff y claims), una llamada y un attempt por turno normal, sin streaming ni tools. El prompt del sistema vive versionado en `app/conversation/prompts.py` (sin framework de prompts ni config dinámica) e incluye la política de petición previa, la precedencia de la necesidad inmediata, la preservación del goal ante una petición de persona, la redirección de alcance sin handoff y la clasificación de la confirmación HITL como principios generales. El grafo del turno es `START → run_model → advance_turn → END`; el modelo sugiere, el runtime decide, y el contrato del modelo no incluye `EXECUTE_ACTION`.
- La validación positiva de identidad sigue sin integración real; el contrato PII-safe `IDENTITY_VALIDATION_RESULT` está implementado y probado sólo con dobles (ID-001).
- El [Experimento 0003](docs/experiments/0003-gemini-baseline-latency.md) midió el camino real desde host DEV (30 requests secuenciales, 0 errores): handler p50 1 281 / p95 1 922 ms; load p50 219 / p95 421 ms; modelo p50 782 / p95 1 062 ms (máx 4 094 ms); save p50 234 / p95 266 ms. Es un baseline DEV, no un SLO: no incluye ASR/TTS/red XCALLY ni Cloud Run in-region.
- El [Experimento 0004](docs/experiments/0004-cloud-run-latency.md) midió el baseline in-region en Cloud Run `us-east1` con una instancia warm: 30/30 requests medidas con 0 errores; handler p50 657 / p95 920 ms; load p95 36 ms; modelo p50 595 ms; save p95 102 ms; round-trip HTTPS del cliente p50 878 / p95 1 145 ms. `min=0` restaurado y verificado read-only.
- Gemini 3.5 Flash-Lite con razonamiento `MINIMAL` es el perfil conversacional activo sintético. Su identidad se deriva de `config.yaml` y `app/conversation` y el harness calcula su fingerprint en runtime; la historia vive en ADR-0011, Experimento 0009 y Git.
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
- [Experimento semántico 0006](docs/experiments/0006-semantic-runtime-evaluation.md)
- [Experimento laboratorio de evaluación 0007](docs/experiments/0007-agent-evaluation-lab.md)
- [Experimento contrato de eventos técnicos 0010](docs/experiments/0010-integration-events-contract.md)
- [Experimento composición de prompts 0011](docs/experiments/0011-prompt-composition-runtime-protocols.md)
- [Runbook Cloud Run DEV benchmark](docs/runbooks/cloud-run-dev-benchmark.md)
- [Núcleo Thin Session](app/session/)
- [Benchmark de latencia DEV](evals/backend_latency.py)
- [Laboratorio de conversación: runner](evals/conversation_eval.py)
- [Comparador pareado puro](evals/conversation_compare.py)
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
- núcleo productivo mínimo del Thin Session Repository en `app/session` y runtime semántico durable schema v2 con guards deterministas de ruta, claims y despacho;
- laboratorio de evaluación conversacional en `evals/`: runner real-model `conversation_eval.py`, comparador pareado puro `conversation_compare.py`, fingerprint de variante calculado en runtime y artefactos locales en `evals/results/` (Git-ignored, no canónicos);
- suite determinista del laboratorio en `tests/evals/`, además de los tests Thin Session y los del boundary/modelo, con dobles en memoria y fakes; sin Gemini, XCALLY, AD/TIVIT ni credenciales;
- baseline DEV provisional del boundary HTTP XCALLY↔CU013 implementado bajo `app/api`, con contrato Pydantic 2, autenticación `X-API-Key` sólo desde entorno, `turn_id` por request, errores con taxonomía segura y OpenAPI coherente;
- seam `ConversationEngine` en `app/conversation` como único punto de extensión para el motor Gemini, sin NLU determinista ni respuestas semánticas falsas;
- política conversacional de petición previa en `app/conversation/prompts.py`;
- motor real `GeminiTurnModel` detrás del seam: Vertex AI con ADC, output estructurado tipado y errores del modelo traducidos a la taxonomía segura;
- benchmark real `evals/backend_latency.py` con segmentación por etapa y conteo de tokens, sin registrar transcript, DTMF ni texto generado;
- lock productivo exacto y reproducible en `requirements.lock`;
- contenedor productivo mínimo (`Dockerfile`, `.dockerignore`) con instalación runtime con el lock;
- tooling Cloud Run DEV versionado en `ops/gcp/` y runbook asociado;
- contratos backend de integración para `TEST_XCALLY_CU013_API_APPROACH`: `/turns` con `BoundaryRoute.EXECUTE_ACTION` y `command` opaco, `/integration-events` con union discriminada de eventos PII-safe, máquina durable de operación, directivas anti-silencio y retirada del DTMF crudo del contrato activo, con tests deterministas de autorización, duplicados, late results, JSON y canarios PII;
- gate determinista de repository readiness en `tests/repository/` que protege fuentes canónicas, baseline efectivo, higiene de artefactos, aliases experimentales, links y lock.

Validado localmente el 15-09-2026:

- integridad SHA-256 de los dos IOP y coincidencia exacta de nombres;
- PDF de IOP ignorados por Git y manifiesto versionable;
- Python 3.12.2 en `.venv` e instalación editable DEV correcta que expone `app` fuera del worktree;
- impersonación ADC, refresh `google-auth` y lectura read-only de Firestore validados desde el host real por el propietario;
- gates aprobados con el entorno fijado por el lock;
- advisory review con OSV sin hallazgos abiertos;
- limpieza Firestore documentada sin wildcards ni collection-group deletes;
- enlaces Markdown, límites documentales, ausencia de atajos TLS y consistencia de artefactos.

Validado el 16-09-2026 (iteración Gemini y benchmark):

- gates de la iteración Gemini sin regresión;
- ADC impersonación de `cu013-runtime-dev` verificada sin imprimir tokens; lectura read-only de Firestore y llamada mínima correctas;
- benchmark real completado con 0 errores y continuidad durable multi-turn verificada;
- benchmark in-region completado (Experimento 0004) con 0 errores/timeouts y `min=0` restaurado;
- diagnóstico read-only del primer turno de voz XCALLY real (Experimento 0005) y corrección de política con gates y probe real focalizado.

Validado el 17-09-2026 (owner decisions, runtime semántico y laboratorio):

- gates deterministas, validación estática del corpus sin ADC ni modelo y evaluación real-model de los Experimentos 0006 y 0007 sin regresiones críticas;
- latencia/tokens medidos sin SLO nuevo; secuencia larga con prompt por llamada plano.

Validado el 19-09-2026 (reconciliación del baseline, sin commit):

- runtime/harness/docs reconciliados con lenguaje descriptivo; scaffolding multi-proveedor retirado del path activo; historia en ADR-0011, Experimento 0009 y Git;
- perfil activo derivable de `config.yaml` y código con fingerprint en runtime; sin manifiestos JSON canónicos paralelos;
- gates deterministas y corpus validados; sin evaluación focal nueva;
- cloud read-only verificado sin mutación; cleanup pendiente separado y sin freeze declarado hasta cerrar readiness.

Validado el 21-09-2026 (contratos backend del flujo TEST, sin commit):

- `/turns` sólo transcript, `EXECUTE_ACTION` + `command` opaco y `/integration-events` con union discriminada de eventos PII-safe implementados y probados con dobles; cero llamadas al modelo por polling;
- máquina durable de operación con ACK idempotente, conflicto seguro, late results y sin re-dispatch; canarios PII ausentes de modelo, Firestore, logs, respuesta y artefactos versionados;
- aliases experimentales eliminados de código/harness/tests/docs activos y bloqueados por el gate de readiness; oráculo `confirmation-affirmative-authorizes` reconciliado a `not_eligible` tras despacho legal;
- gates deterministas, corpus y mypy en verde; sin XML XCALLY modificado, sin llamada RD/AD, sin deploy ni commit.

Validado el 23-09-2026 (next-step-v1, evaluación económica y deploy E2E):

- selector explícito, envelope común, continuidad post-identidad, secuencia/dedupe/presupuesto de polling, `IDENTITY_INPUT_FAILURE`, presentación de contraseña y composer de feedback implementados y cubiertos por tests deterministas de contrato, estado, máquina de polling, normalización, canarios PII y wording;
- contrato durable v3 con migración v1/v2 fail-closed y fingerprints PII-safe; sin persistir transcript, body RD, status desconocido crudo, documento, fecha, email ni contraseña;
- gates deterministas en verde: `pytest` 548 pasando (dos fallos de entorno preexistentes por `google-cloud-firestore` 2.28.1 instalado frente al pin 2.30.0 del lock), Ruff, `ruff format --check`, MyPy y corpus `--validate-only` (47 casos, 0 problemas);
- sin full paired por cambio de wording: la semántica de decisión del modelo conversacional no cambia; smoke real acotado contra la revisión etiquetada y deploy E2E con 0% de tráfico, `min=1` de revisión y tag `e2e-4b72dfa` reasignado.

Validado el 23-09-2026 (compatibilidad numérica XCALLY):

- la llamada `Ivr02-1790205174.363975` completó `UNLOCK_ACCOUNT → COLLECT_IDENTITY → VALID → confirmación → EXECUTE_ACTION → POST RD 200/NONE → GET RD 200/NONE`, con `CALLERID(name)=${UNIQUEID}` consistente y RAW bodies entrecomillados sin AGI 510; el único fallo fue `poll_sequence:int_type`;
- implementada la compatibilidad numérica estrecha del boundary v1 (whitelist cerrada, sólo strings decimales canónicas, antes del schema estricto); el dominio y el carril legacy no cambian;
- gates deterministas en verde con la cobertura nueva de helper, boundary, dominio, legacy sin coerción y logs PII-safe.

Validado el 23-09-2026 (diagnóstico E2E y corrección de contrato):

- cuatro llamadas reales contra `00028-6rb` con evidencia PII-safe: 409 por evento sin turno, dos 422 por body fuera del contrato y un 200 servido con envelope legacy; diagnóstico cerrado `HEADER_MISMATCH` (el Switch esperaba `next_step` y su rama por defecto transfirió; no fue atención humana);
- gap de observabilidad confirmado: los INFO de aplicación no llegaban a Cloud Logging; se corrigió con la topología `cu013` y eventos cerrados;
- implementados header canónico `X-CU013-Response-Contract` sin alias, `next_step` derivado del estado (goal pendiente sin autorización exige `COLLECT_IDENTITY`), bootstrap pre-turno v1 con create condicional y contador durable, schema v4, rejection reasons tipados y proyección segura de 422;
- gates deterministas en verde con cobertura nueva de repositorio, migración, bootstrap, gating, routing, contrato y observabilidad; sin full paired por no cambiar la semántica de decisión del modelo.

Pendiente:

- despliegue de la revisión con compatibilidad numérica (header canónico, routing por estado, bootstrap, logging y whitelist numérica) con 0% de tráfico, `min=1` de revisión y tag `e2e-4b72dfa` reasignado, y nueva llamada real del owner;
- la política de voice retry quedó cerrada por el owner: hasta cuatro fallos consecutivos (tres reintentos), el cuarto transfiere y un `/turns` válido reinicia el contador; la apertura proactiva de challenge en la precedencia de estado queda descartada explícitamente (se conserva la invariante de side questions);
- aceptación del owner de los contratos backend implementados y del [Experimento 0010](docs/experiments/0010-integration-events-contract.md);
- diseñar en Cally Square el flujo `TEST_XCALLY_CU013_API_APPROACH` (rama `EXECUTE_ACTION`, captura/validación de identidad, `VOICE_INPUT_FAILURE`, adaptación de bloques RD y polling sin LLM) y desplegar de forma coordinada, porque el contrato nuevo reemplaza `IDENTITY_DATA`;
- caller tests E2E y análisis con `xcally-call-evidence-analysis` antes de declarar integrados identidad, RD, polling, ASR/TTS, latencia o handoff;
- revalidar en voz DEV el prompt y el runtime semántico ya committeados (requiere autorización del owner para deploy; la revisión desplegada todavía contiene el prompt anterior y no el runtime v2);
- cerrar FS-002 con el reparto del presupuesto completo de voz (XCALLY/ASR/TTS); el rango in-region indicado es de centenas bajas de milisegundos por llamada;
- integrar la validación positiva de identidad (ID-001);
- validar los contratos externos aún abiertos antes de acciones de cuenta productivas;
- decidir el cleanup de los 97 documentos sintéticos de benchmark (requiere autorización explícita; sin wildcards ni collection-group deletes).

## Control operativo previo al experimento

El propietario confirmó desde el host real la cadena completa `ADC impersonation → google-auth refresh → Firestore read-only` con `cu013-spike-firestore` sobre el proyecto `cu013-xcally-agentic` y la base `(default)`. El control previo al experimento está aprobado.

El benchmark real de latencia del 16-09-2026 fue autorizado por el propietario y se ejecutó con ADC impersonando `cu013-runtime-dev`; las corridas locales y la corrida Cloud Run dejaron 97 documentos sintéticos bajo `cu013dev_sessions` que no fueron borrados. El despliegue y la ventana warm las ejecutó el propietario con el tooling versionado; el agente sólo hizo verificación y lecturas read-only. Nunca deshabilitar TLS ni la verificación de certificados para sortear el problema.

## Bloqueos y preguntas abiertas

- XC-001 abierto: existe un baseline HTTP provisional del turno y un contrato técnico local de órdenes/resultados, pero faltan la validación y el contrato integrado con el flujo Cally Square real y AD/TIVIT.
- Correlación, idempotencia, polling, reintentos y resultados tardíos (XC-002 a XC-004): contrato local candidate, sin evidencia E2E.
- Esquema completo de resultados XCALLY/Orchestrator/TIVIT/AD (XC-005) y mapeo exacto de estados externos a respuesta o escalamiento (XC-006).
- Resultado positivo de validación de identidad sin integración AD/TIVIT (ID-001).
- FS-002 abierto con evidencia local e in-region: load p95 421 ms (local) / 36 ms (Cloud Run) y save p95 266 ms (local) / 102 ms (Cloud Run); el rango indicado es de centenas bajas de milisegundos por llamada, pero falta el reparto del presupuesto completo de voz (XCALLY/ASR/TTS) para fijar el valor.
- La validación de TTL requiere permisos no concedidos a la cuenta de servicio del experimento.
- Debilidades residuales del modelo registradas en el [Experimento 0006](docs/experiments/0006-semantic-runtime-evaluation.md): no son fallos de legalidad del runtime y pasan a la validación de voz DEV.

SendMail permanece Deferred y fuera del alcance inmediato. Los valores predeterminados ausentes de la configuración local no son bloqueos arquitectónicos.

## Estado operativo y próximo gate

| Componente | Estado |
|---|---|
| Thin Session Repository | accepted + implemented |
| Boundary HTTP/XCALLY | implemented, PROVISIONAL (`/turns` + `/integration-events`, legacy + `next-step-v1`) |
| Contrato durable | schema v4 (`polling` + `password_presentation` + `voice_retry_count`; migración v1/v2/v3 fail-closed) |
| Gemini baseline | integrated (Gemini 3.5 Flash-Lite, `global`, `MINIMAL`, sintético; no voz-validado) |
| Cloud Run DEV | implemented; estado de reposo `min=0` |
| Experimento 0004 | completed |
| Experimento 0005 | completed (corrección de prompt committeada, pendiente deploy y revalidación de voz) |
| Experimento 0006 | completed (runtime semántico candidato, sin regresiones críticas; validación de voz DEV pendiente) |
| Experimento 0007 | completed (laboratorio de evaluación materializado y validado; sin comparación de candidato todavía) |
| Experimento 0010 | running (contratos backend de integración y `next-step-v1` implementados y probados localmente; revisión E2E etiquetada con 0% de tráfico y `min=1` de revisión; caller tests pendientes) |
| Experimento 0011 | completed (INCONCLUSIVE — OWNER DECISION REQUIRED; rama `exp/prompt-protocols` aislada, NOT merged to dev; sin deploy ni E2E) |
| Baseline conversacional activo | Gemini 3.5 Flash-Lite, Vertex `global`, `MINIMAL`, sintético; no voz-validado ni producción |
| FS-002 | open |
| CNV-001 | resolved (schema v2 durable pre-auth + continuidad + correcciones/cancelación implementados y verificados; eliminado de `docs/gaps.md`) |
| Laboratorio de evaluación | `conversation_eval.py` + `conversation_compare.py` + corpus de 47 casos / 39 familias; `scenario_kind`, oráculos nulos/ausentes, evidencia por run/caso/turno, INFRA por repetición, reruns focalizados y CI sin credenciales |
| Próximo gate | caller tests E2E del owner contra la tag `e2e-4b72dfa` y análisis con `xcally-call-evidence-analysis`; cierre de la ventana E2E con autorización posterior |
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

La métrica objetivo de ese gate es `end-of-speech → first useful audio`. No añadir trabajo especulativo ni inventar contratos; RD/AD real no se integra antes de ese baseline de voz XCALLY aislado (los contratos backend locales del Experimento 0010 preparan el flujo TEST sin integrar RD/AD).

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

- Camino feliz E2E hasta RD y compatibilidad numérica: `UNLOCK_ACCOUNT → COLLECT_IDENTITY → VALID → confirmación → EXECUTE_ACTION → POST/GET RD 200/NONE` con `CALLERID(name)` consistente; whitelist numérica estrecha en el adapter v1 (`"1" → 1`) con dominio y legacy estrictos.
- Diagnóstico E2E y corrección de contrato: cuatro llamadas reales analizadas (409 sin turno, 422 de body, 200 legacy), `HEADER_MISMATCH` cerrado, header canónico `X-CU013-Response-Contract`, `next_step` derivado del estado, bootstrap pre-turno v1, schema v4, rejection reasons tipados y logging `cu013` con eventos cerrados.
- `next-step-v1`: contrato común de respuesta con selector explícito, continuidad post-identidad, polling secuenciado/deduplicado/acotado, presentación de contraseña, composer de feedback estrecho, schema v3 y wording fecha de ingreso; evaluación económica y revisión E2E etiquetada con 0% de tráfico y `min=1` de revisión.
- Contratos backend del flujo `TEST_XCALLY_CU013_API_APPROACH`: command/event (`EXECUTE_ACTION` + `command` opaco, `/integration-events` con eventos PII-safe), máquina durable de operación, anti-silencio experimental y retirada del DTMF crudo; Experimento 0010 en curso y readiness de aliases/oráculo reconciliada.
