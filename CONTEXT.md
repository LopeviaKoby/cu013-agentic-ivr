# CU013 v0.2.0 — Contexto actual

## Propósito y alcance actual

CU013 reconstruye el backend conversacional de Mesa de Ayuda para XCALLY Motion y Cally Square. El repositorio contiene autoridad documental, estándares de ingeniería, configuración no sensible, herramientas operativas reproducibles para DEV y experimentación, y el núcleo productivo mínimo del Thin Session Repository integrado y committeado en `app/session`. El worktree materializa en `app/api` un baseline DEV provisional del boundary HTTP para Cally Square, en `app/conversation` el motor real Gemini 2.5 Flash-Lite detrás del seam y en `evals/` el benchmark de latencia del camino backend completo. Todavía no existe servicio Cloud Run ni integración AD/TIVIT.

El primer corte de acciones de cuenta es `RESET_PASSWORD` + `UNLOCK_ACCOUNT`, sin prioridad obligatoria entre ambas.

## Pila y entorno

- Python 3.12, FastAPI, Pydantic 2, LangGraph y `google-genai`/Vertex AI.
- Firestore como único almacén durable aceptado.
- Cloud Run como destino futuro de cómputo.
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

Servicios habilitados pero aún no materializados:

- API de Cloud Run; ningún servicio desplegado;
- API de Secret Manager; ningún secreto creado;
- API de Vertex AI; el motor real y su benchmark DEV ya ejecutan, pero no existe evaluación comparativa de modelos ni servicio cloud.

## Estado arquitectónico actual

- v0.2.0 es una arquitectura nueva y un monolito modular.
- LangGraph es el marco aceptado para orquestación de turnos.
- Los IOP corporativos locales son la autoridad del procedimiento empresarial y tienen un [manifiesto versionado](docs/iop/README.md).
- `RESET_PASSWORD` permite autoservicio guiado y acción directa autorizada después de validar identidad.
- `UNLOCK_ACCOUNT` no tiene autoservicio; la acción directa autorizada usa XCALLY/Cally Square → Orchestrator/TIVIT/AD.
- CU013 no integra tickets ITSM; el registro en herramientas de gestión está fuera del límite técnico del backend.
- La validación de identidad comienza con documento y fecha de nacimiento por DTMF.
- Los valores DTMF crudos quedan fuera del LLM y de los registros, y se minimizan en persistencia.
- SendMail está Deferred. La secuencia aceptada es: experimento de persistencia → integración AD/TIVIT → depuración guiada por logs y pruebas con callers → SendMail. CU013 sólo recibirá el estado del envío.
- [ADR-0009](docs/decisions/0009-use-thin-firestore-session-repository.md) acepta Thin Firestore Session Repository: cargar un `SessionRecord` semántico, construir un `GraphState` efímero, ejecutar LangGraph sin persistent checkpointer, consolidar y guardar antes del HTTP response.
- La Opción A resultó viable experimentalmente, pero fue descartada para el voice path productivo por latencia, amplificación de escrituras, complejidad de persistencia/retención y acoplamiento a LangGraph.
- El security floor productivo está resuelto en `langgraph>=1.0.10` y `langgraph-checkpoint>=4.1.1`; el lock exacto está fijado en [requirements.lock](requirements.lock) con `langgraph==1.2.11`, `langgraph-checkpoint==4.2.0` y `google-cloud-firestore==2.30.0`.
- El núcleo productivo mínimo del Thin Session Repository está integrado y committeado en `app/session`: contrato durable cerrado, grafo LangGraph determinista sin persistent checkpointer y 1 load + 1 save por turno normal.
- El boundary HTTP XCALLY↔CU013 está implementado en el worktree como baseline DEV `PROVISIONAL` y tipado en [Boundary HTTP XCALLY↔CU013](docs/specs/xcally-boundary.md): `POST /api/v1/conversations/{conversation_id}/turns`, variantes transcript ASR e `IDENTITY_DATA`, autenticación `X-API-Key` sólo desde entorno, `turn_id` único por request y errores con taxonomía segura. No es el contrato integrado final.
- El transcript es efímero y no se persiste; el DTMF crudo queda contenido en el boundary (no se persiste, registra, devuelve ni alcanza al seam) y nunca marca `identity_validated=True`.
- El primer motor real es `GeminiTurnModel` (`app/conversation`): Vertex AI sobre ADC, `thinking_budget=0`, output estructurado tipado `ModelTurnDecision` (`message`, `route`, `action_requested`), una llamada y un attempt por turno normal, sin streaming ni tools. El grafo del turno es `START → run_model → advance_turn → END`; el modelo sugiere, el runtime decide.
- La validación positiva de identidad sigue sin integración; `IDENTITY_DATA` termina de forma segura con `dependency_unavailable`.
- El [Experimento 0003](docs/experiments/0003-gemini-baseline-latency.md) midió el camino real desde host DEV (30 requests secuenciales, 0 errores): handler p50 1 281 / p95 1 922 ms; load p50 219 / p95 421 ms; modelo p50 782 / p95 1 062 ms (máx 4 094 ms); save p50 234 / p95 266 ms. Es un baseline DEV, no un SLO: no incluye ASR/TTS/red XCALLY ni Cloud Run in-region.
- Gemini 2.5 Flash-Lite con razonamiento desactivado sigue como referencia temporal.
- No existen Terraform, Dockerfile ni servicio Cloud Run; el código de ejecución es el núcleo de sesión, el boundary HTTP y el motor real.

## Puntos de entrada del repositorio

- [Especificación del sistema](docs/specs/system.md)
- [Especificación de acciones de cuenta](docs/specs/account-actions.md)
- [Boundary HTTP XCALLY ↔ CU013](docs/specs/xcally-boundary.md)
- [Decisiones arquitectónicas](docs/decisions/)
- [Gaps de implementación](docs/gaps.md)
- [Estándares de ingeniería](docs/engineering/)
- [Manifiesto de IOP locales](docs/iop/README.md)
- [Runbook de inicialización GCP](docs/runbooks/gcp-dev-bootstrap.md)
- [Experimento Firestore/LangGraph](docs/experiments/0001-firestore-langgraph-checkpointer.md)
- [Experimento Thin Session Repository](docs/experiments/0002-firestore-thin-session-repository.md)
- [Experimento Gemini baseline de latencia](docs/experiments/0003-gemini-baseline-latency.md)
- [Núcleo Thin Session](app/session/)
- [Benchmark de latencia DEV](evals/backend_latency.py)
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
- suite determinista de 34 tests con doble en memoria y fake del cliente async; sin Gemini, XCALLY, AD/TIVIT ni credenciales;
- baseline DEV provisional del boundary HTTP XCALLY↔CU013 implementado en el worktree bajo `app/api`, con contrato Pydantic 2, autenticación `X-API-Key` sólo desde entorno, `turn_id` por request, errores con taxonomía segura y OpenAPI coherente con las respuestas reales;
- seam `ConversationEngine` en `app/conversation` como único punto de extensión para el motor Gemini, sin NLU determinista ni respuestas semánticas falsas;
- motor real `GeminiTurnModel` detrás del seam: Vertex AI con ADC, baseline reemplazable en un solo objeto (`project`, `location`, `model`, `api_version`, `thinking_budget=0`, `timeout_ms`, `attempts=1`), output estructurado tipado y errores del modelo traducidos a la taxonomía segura (`dependency_timeout` 504, `dependency_unavailable` 503, salida inválida → `internal` 500);
- seam `TurnMetrics` PII-safe (segmentos con nombres fijos y contadores sólo de tokens) y composition root DEV `app/main.py` con clientes async de Vertex y Firestore reutilizados y cerrados en el lifespan;
- benchmark real `evals/backend_latency.py`: 5 warmups + 30 requests secuenciales medidos a través del boundary FastAPI contra Firestore y Vertex reales, con segmentación por etapa y conteo de tokens, sin registrar transcript, DTMF ni texto generado;
- suite determinista del boundary: contrato cerrado y rutas fuera del enum rechazadas, API key válida/incorrecta/ausente/no configurada, `IDENTITY_DATA` sin fuga de DTMF, payloads inválidos sin eco de transcript ni DTMF, identidad de sesión desde la ruta, `turn_id` distinto por request, `X-Request-ID` no usado como idempotency key y errores internos traducidos a contrato seguro;
- lock productivo exacto y reproducible en `requirements.lock`, con revisión de advisories OSV sin hallazgos abiertos;
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
- 54 documentos sintéticos de benchmark permanecen en `cu013dev_sessions` (2 corridas × 27); su borrado no fue autorizado y no se ejecutó.

Pendiente:

- integrar la validación positiva de identidad (ID-001) y cerrar FS-002 con latencia in-region de Cloud Run y el reparto del presupuesto completo de voz (ASR/TTS/XCALLY);
- evaluar Gemini 2.5 Flash-Lite y una alternativa antes del 16-10-2026;
- validar los contratos externos aún abiertos antes de acciones de cuenta productivas.

## Control operativo previo al experimento

El propietario confirmó desde el host real la cadena completa `ADC impersonation → google-auth refresh → Firestore read-only` con `cu013-spike-firestore` sobre el proyecto `cu013-xcally-agentic` y la base `(default)`. El control previo al experimento está aprobado.

El benchmark real de latencia del 16-09-2026 fue autorizado por el propietario y se ejecutó con ADC impersonando `cu013-runtime-dev`; creó 54 documentos sintéticos bajo `cu013dev_sessions` que no fueron borrados. Nunca deshabilitar TLS ni la verificación de certificados para sortear el problema.

## Bloqueos y preguntas abiertas

- XC-001 abierto: existe un baseline HTTP provisional del turno, pero faltan la validación y el contrato integrado con el flujo Cally Square real y AD/TIVIT.
- Correlación, idempotencia, polling, reintentos y resultados tardíos (XC-002 a XC-004).
- Esquema completo de resultados XCALLY/Orchestrator/TIVIT/AD (XC-005) y mapeo exacto de estados externos a respuesta o escalamiento (XC-006).
- Resultado positivo de validación de identidad sin integración AD/TIVIT (ID-001).
- FS-002 abierto con evidencia nueva: load p50 219 / p95 421 ms y save p50 234 / p95 266 ms desde host DEV; falta latencia in-region de Cloud Run y el reparto del presupuesto completo de voz (ASR/TTS/red XCALLY), con la cola del modelo dominando la varianza.
- La validación de TTL requiere permisos no concedidos a la cuenta de servicio del experimento.

SendMail permanece Deferred y fuera del alcance inmediato. Los valores predeterminados ausentes de la configuración local no son bloqueos arquitectónicos.

## Próximo incremento

La evidencia de latencia del backend real ya existe y es un baseline DEV (p50 ≈1,3 s, p95 ≈1,9 s sin ASR/TTS/red). El siguiente incremento requiere decisión del propietario entre: integración AD/TIVIT (ID-001 y XC-001 a XC-006) con la medición integrada del flujo Cally Square, o despliegue Cloud Run para medir latencia in-region y fijar FS-002. Sin esa decisión no se avanza; no añadir trabajo especulativo ni inventar contratos.

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

- Gemini 2.5 Flash-Lite integrado como primer motor real dentro del turno (1 llamada, 1 load, 1 save) con output estructurado tipado y benchmark DEV del camino completo medido (Experimento 0003, 30/30 requests, p50 handler 1 281 ms).
- Baseline DEV provisional del boundary HTTP XCALLY↔CU013 implementado sobre Thin Session: contrato tipado, autenticación `X-API-Key`, contención de DTMF, transcript efímero y seam `ConversationEngine` para Gemini, sin motor falso.
- Thin Session Repository aceptado en ADR-0009, implementado como núcleo productivo mínimo con lock reproducible y con la limpieza Firestore experimental completada; Option A descartada, ambos experimentos preservados y worktrees/ramas locales retirados.
