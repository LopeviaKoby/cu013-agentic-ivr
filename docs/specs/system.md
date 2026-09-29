# CU013 v0.2.0 — System Specification

## High-Level Goal

CU013 v0.2.0 debe construir un agente telefónico de Mesa de Ayuda natural, contextual y verificable. El LLM conduce la conversación; el runtime controla legalidad, verdad, autorización, estado y efectos externos.

La base GCP para DEV y SPIKE debe ser mínima, económica y reproducible. Debe permitir experimentar ahora y reproducir entornos con mayor fidelidad cuando exista evidencia, sin introducir infraestructura preventiva.

## Autoridad y clasificación

Esta SPEC contiene únicamente requisitos e invariantes transversales. El comportamiento del primer slice está en [Account Actions](account-actions.md).

- **ACCEPTED**: requisito aprobado que el sistema debe respetar.
- **IMPLEMENTED**: estado materializado y confirmado.
- **PROVISIONAL**: diseño sujeto a validación o decisión posterior.
- **UNKNOWN**: información faltante que no debe inventarse.

La precedencia completa está definida en [AGENTS.md](../../AGENTS.md).

## Alcance y stack

**ACCEPTED.** CU013 v0.2.0 es una reconstrucción arquitectónica nueva. El código anterior puede consultarse como evidencia, pero no define la arquitectura.

**ACCEPTED.** El stack objetivo es Python 3.12, FastAPI, Pydantic 2, LangGraph, `google-genai`, Vertex AI, Firestore, Cloud Run, Docker, GitHub Actions, pytest, Ruff y MyPy.

**ACCEPTED.** La arquitectura es un monolito modular por capacidades. LangGraph es el framework de orquestación y debe usarse sólo donde aporte las primitivas necesarias.

**ACCEPTED.** Firestore es el único store durable aceptado. El mecanismo vigente es un Thin Firestore Session Repository; el voice path no usa un persistent LangGraph checkpointer.

**ACCEPTED.** No se incorporarán una gran FSM conversacional, NLU por keywords/regex, RAG/vector DB, multi-agent, un orquestador propio ni infraestructura adicional sin evidencia.

## Responsabilidades

El LLM es responsable de comprensión del lenguaje, extracción multi-fact, aclaraciones, correcciones, continuidad contextual y formulación natural.

El runtime es responsable de contratos, validación, autorización, invariantes, persistencia, idempotencia, ejecución de efectos externos y verdad de resultados.

Una tool representa una capacidad externa. Persistir estado o modificar memoria interna no es una tool.

Un turno normal apunta a una sola solicitud al modelo. Si una interacción lógica requiere más de dos llamadas secuenciales al modelo, se debe hacer STOP & REPORT.

## Invariantes conversacionales transversales

**ACCEPTED.** Las siguientes invariantes rigen cualquier comportamiento conversacional de CU013. Su materialización de estado concreto es discreción de ingeniería mientras las respete; los detalles del primer slice están en [Account Actions](account-actions.md).

### Plan conversacional durable

- **ACCEPTED.** El estado durable conserva un plan conversacional pequeño y semántico de objetivos soportados, separado de cualquier autorización, confirmación u operación externa. La intención expresada por el caller puede existir como goal conversacional sin estar autorizada, confirmada, despachada ni completada.
- **ACCEPTED.** Las side questions, correcciones, cambios de objetivo, cancelaciones y continuidad multi-turno son parte del comportamiento normal. Atender la necesidad conversacional del momento no pierde el goal soportado vigente; una corrección o cancelación del caller actualiza el plan antes de cualquier autorización o despacho.
- **ACCEPTED.** El goal sólo se cancela o elimina si el caller lo solicita explícitamente, y en ese caso el agente comunica brevemente que la solicitud quedó cancelada. Una petición explícita de hablar con una persona no cancela, borra ni completa el goal vigente: nunca se infiere cancelación del goal a partir de un handoff.
- **ACCEPTED.** Una petición fuera del alcance soportado no implica handoff: el agente responde brevemente que todavía no puede ayudar con esa capacidad o redirige al ámbito de Mesa de Ayuda, sin escalar por ese solo motivo. ESCALATE no es fallback de clasificación ni de alcance y requiere una causa aceptada.

### Separación goal / autorización / confirmación / operación / resultado

- **ACCEPTED.** Estos estados son distintos y ninguno implica a otro:
  1. goal conversacional (`conversation goal`);
  2. identidad validada (`identity authorization`);
  3. confirmación HITL verbal por operación (`verbal confirmation`);
  4. autorización de despacho (`authorized dispatch`);
  5. operación externa pendiente (`pending external operation`);
  6. resultado externo confirmado (`confirmed external result`).
- **ACCEPTED.** Toda afirmación (`claim`) comunicada al caller debe estar respaldada por el estado runtime observable. El modelo no crea verdad; la verdad del sistema proviene del estado durable y de resultados externos confirmados.

### Continuidad tras una operación resuelta

- **ACCEPTED.** Una operación terminal (`confirmed`/`failed`) no cierra la conversación: el resultado se comunica con la verdad observada, se invita a continuar y el runtime escucha (`LISTEN`). `COMPLETE` se reserva al cierre conversacional explícito del caller.
- **ACCEPTED.** Al confirmarse un resultado terminal, el goal queda resuelto: se marca y se limpia para impedir un redespacho obsoleto. El resultado se conserva en `external_operation` para grounding. Una necesidad nueva crea un goal nuevo; una pregunta sobre lo recién resuelto se responde desde el historial de la operación sin reactivar el goal ni repetir el despacho.
- **ACCEPTED.** La autorización de despacho se consume al alcanzar el resultado terminal: `external_action_allowed=false`. El guard durable se conserva sólo como metadata de correlación (late results y presentación de contraseña) y nunca se reutiliza para un nuevo despacho; toda acción futura crea autorización/dispatch nuevos.
- **ACCEPTED.** Un turno lateral u off-topic no implica handoff, identidad ni acción: se responde brevemente y se redirige si corresponde, preservando el goal vigente para retomarlo cuando el caller lo avance de nuevo. El contrato del modelo distingue esa relación con el goal (`SIDE`) sin heurísticas ni una segunda llamada.

### Presentación de la contraseña temporal (RESET_PASSWORD)

- **ACCEPTED.** La entrega de la contraseña temporal es por **voz efímera**: XCALLY la mantiene en su ámbito call-local y la reenvía en cada turno de presentación; el backend la usa sólo durante ese request. SMS queda **DEFERRED** y email/SendMail queda **superseded** como vía de entrega ([ADR-0012](../decisions/0012-use-ephemeral-voice-for-temporary-password.md)).
- **ACCEPTED.** El resultado del reset, el playback de la presentación, el fin indicado por el llamante (`caller_finished`) y el ciclo conversacional son hechos separados y ninguno implica a otro. El boundary reporta el playback como `PLAYBACK_RETURNED` o `PRESENTATION_FAILED_BEFORE_PLAYBACK`; un fallo antes del playback no cambia el reset, no re-despacha y mantiene la presentación activa.
- **ACCEPTED.** El secreto es efímero: nunca entra a Firestore, `SessionRecord`, memoria durable o reciente, logs, métricas, artefactos de evaluación, fixtures, documentos, Git ni payloads de error. Puede transitar por el request `/turns`, los objetos transitorios, el `GraphState`, la entrada/salida de Gemini y el mensaje HTTP de ese turno.
- **ACCEPTED.** No existe caché de contraseña entre turnos y la primera vocalización no exige un `PasswordPresentation` previo: es elegible con el reset confirmado y la presentación no finalizada. Una sola llamada a Gemini por turno; sin motor de spelling productivo.
- **ACCEPTED.** Durante la presentación no se registra goal nuevo, no se abre challenge, no se autoriza despacho y no se re-despacha. La memoria reciente no se renderiza ni se anexa en turnos de presentación porque el transcript puede repetir el secreto.

### Modalidad de asistencia del reset

- **ACCEPTED.** `RESET_PASSWORD` tiene una dimensión semántica durable `assistance_mode` (`UNDECIDED | GUIDED | AUTONOMOUS`) que pertenece al goal activo, no es autorización ni efecto externo y se limpia con el goal. `UNLOCK_ACCOUNT` no la usa.
- **ACCEPTED.** `UNDECIDED` registra el goal y ofrece brevemente GUIDED/AUTONOMOUS sin capturar identidad, sin challenge y sin despacho. `GUIDED` guía el autoservicio y nunca abre challenge ni despacha. `AUTONOMOUS` exige identidad válida y una confirmación verbal específica de RESET antes del despacho.
- **ACCEPTED.** Reutilizar identidad no reutiliza confirmación: una confirmación de UNLOCK no autoriza RESET. Un cambio de modalidad invalida cualquier challenge pendiente; el runtime — no el prompt — impone que sólo `AUTONOMOUS` abra challenge.
- **ACCEPTED.** Un resultado externo terminal sólo acredita la acción que ese resultado identifica, y lo que dice el llamante no es verdad de operación. La proyección expone `external_operation_action` junto a `external_operation_status` para que el modelo nunca aplique un resultado histórico a un goal de otra acción.
- **ACCEPTED.** Una afirmación sin challenge vigente (por ejemplo tras un fallo de captura que invalidó el challenge) no autoriza nada: si la acción sigue siendo elegible, el runtime **re-establece** un challenge nuevo ligado a la acción y la identidad vigentes y vuelve a pedir la confirmación específica con una frase determinista; si no es elegible, registra la violación y responde con el fallback seguro. Nunca anuncia ejecución y no consume intentos de identidad.
- **ACCEPTED.** La modalidad de un RESET establecida por el llamante es persistente: `UNDECIDED` sólo existe al crear el goal, y una propuesta `UNDECIDED` sobre un goal `GUIDED`/`AUTONOMOUS` se ignora (no degrada la modalidad ni invalida el challenge). Sólo un cambio explícito `GUIDED`/`AUTONOMOUS` la modifica.
- **ACCEPTED.** `COMPLETE` es un cierre conversacional: el runtime pronuncia un cierre canónico sin pregunta abierta, de modo que el mensaje siempre corresponde al `next_step`.

### Identidad

- **ACCEPTED.** La identidad validada está limitada a la llamada actual y expira con un TTL absoluto de 30 minutos desde su validación, sea cual sea la actividad de la conversación. Sin identidad vigente no existe autorización de despacho.

### Confirmación HITL verbal

- **ACCEPTED.** Toda operación sensible exige una confirmación verbal específica por operación, después de identidad válida:
  1. identidad válida;
  2. el sistema presenta verbalmente la acción concreta a confirmar;
  3. sólo una aceptación afirmativa e inequívoca por voz del caller autoriza esa acción concreta;
  4. el runtime valida que la confirmación corresponde al challenge vigente y a la revisión vigente del objetivo;
  5. sólo entonces puede existir autorización de despacho.
- **ACCEPTED.** Un challenge de confirmación queda invalidado por: timeout o silencio, ASR insuficiente o no concluyente, o revisión del objetivo tras emitir el challenge. Un challenge invalidado no se reutiliza: si corresponde volver a preguntar, se crea un challenge nuevo ligado a la acción y a la revisión vigentes del objetivo; el anterior no revive. Una pregunta lateral del caller no abre ni reabre por sí sola un challenge, aunque la identidad esté validada: el caller debe avanzar semánticamente la operación antes de iniciar o reiniciar la fase HITL.
- **ACCEPTED.** El timeout, el silencio o el ASR insuficiente de una confirmación: no autorizan, no despachan, no infieren negación ni cancelación; invalidan ese intento de confirmación y obligan a repetir la solicitud verbal. Un re-prompt de confirmación no invalida la identidad ya validada y no consume intentos de validación de identidad. No existe máximo aceptado de reintentos de confirmación verbal.
- **ACCEPTED.** No se reutiliza una afirmación anterior para otra acción ni para otra revisión del plan. Una negación explícita no autoriza el despacho. Una cancelación explícita antes del despacho cancela la acción.

### Side effects

- **ACCEPTED.** Los side effects externos sólo se ejecutan después de un guard durable persistido en Firestore y de una autorización válida (identidad vigente + confirmación verbal vigente + operación soportada). Existe como máximo una sola operación externa activa por conversación.
- **ACCEPTED.** La incertidumbre tras un despacho externo se representa como un estado desconocido (`UNKNOWN`) que se reconcilia con el resultado real cuando llega; nunca se declara éxito ni fracaso sin confirmación, y un resultado tardío se reconcilia con la operación existente sin crear una operación nueva ni repetir el side effect.
- **ACCEPTED (temporary fail-safe).** Hasta que exista correlación externa acreditada rige `ONE MUTATING AD ACTION PER CALL`: una vez despachada una acción mutable de AD (`UNLOCK_ACCOUNT`, `RESET_PASSWORD`), cualquier intento posterior de despachar otra mutación AD produce 0 nuevo POST, 0 nueva operación mutable y `TRANSFER` con mensaje determinista seguro. El detalle vive en [Account Actions](account-actions.md). No es "una sola acción por llamada": guidance conversacional (VPN/VDI futura, side questions) queda fuera del presupuesto.

### Restricciones reales del media path

- **ACCEPTED.** CU013 no usa ni asume Dialogflow, barge-in, full-duplex, streaming de tokens, WebSocket de audio ni interrupción del TTS controlada por backend. El camino real es caller → XCALLY/Cally Square → Google ASR → transcript final → CU013 REST → Gemini/runtime → message completo → Google TTS desde XCALLY → caller (cascada half-duplex).
- **ACCEPTED.** Queda prohibido declarar como capability actual que el caller puede interrumpir al agente mientras habla, que el modelo adapta una respuesta durante la reproducción o que la síntesis empieza antes de terminar la generación.

### Simplicidad arquitectónica

- **ACCEPTED.** Antes de añadir estado durable, FSM, modelo, segunda inferencia, router, motor fonético, reglas por frase o framework, preguntar si una estructura semántica pequeña, una función pura, un renderer estrecho o una instrucción de modelo existente resuelve el problema. Preferir el mecanismo mínimo que preserve verdad, seguridad, naturalidad, latencia y testabilidad. Más determinista no equivale a más limpio.

### Voz: brevedad, foco y confirmación

- **ACCEPTED.** Toda respuesta audible expresa primero contexto mínimo y deja para el final la información principal o pregunta que exige respuesta; evita preámbulos, repeticiones y más de una pregunta principal (END_FOCUS, BREVITY, ONE_PRIMARY_QUESTION).
- **ACCEPTED.** Confirmación implícita por defecto para hechos ordinarios (el agente incorpora y avanza; el caller corrige naturalmente). Explícita sólo cuando la invariante lo exige: `RESET_PASSWORD` y `UNLOCK_ACCOUNT` mutables mantienen confirmación HITL verbal explícita y específica.
- **ACCEPTED.** Sin barge-in, la tolerancia a interrupción es aceptar correcciones y cambios de tema en el siguiente turno ASR, conservar contexto y no penalizar ni obligar a reiniciar. `NO_SPEECH`, `LOW_CONFIDENCE` y `TIMEOUT` conservan su semántica propia; el silencio nunca es negación, cancelación ni fallo de identidad.
- **ACCEPTED.** Gemini puede modular brevedad, directitud, empatía y ritmo textual ante señales explícitas (urgencia, frustración, petición de ritmo pausado) sin clasificación emocional durable ni subsistema de emotion detection. La adaptación nunca cambia legalidad, next_step, autorización, challenge, verdad ni side effects.
- **ACCEPTED.** Flattening: apertura y recuperación favorecen preguntas abiertas ("¿En qué te puedo ayudar?"), sin menús jerárquicos. Una elección binaria contextual es válida cuando es decisión semántica del goal (RESET GUIDED vs AUTONOMOUS).
- **ACCEPTED.** Graceful degradation: preservar lo comprendido, pedir sólo lo faltante y reducir el espacio de respuesta si la ambigüedad persiste. No inventar estado, no revivir challenges inválidos, no repetir fases resueltas.
- **ACCEPTED.** Todo mensaje de espera/transición comunica sólo hechos demostrables. Con reset confirmado y `temporary_password` presente se comienza la presentación sin mensaje intermedio; con secreto ausente no se afirma causa ni estado de generación no observado.

## Persistencia de sesión

**ACCEPTED.** Cada request debe cargar desde Firestore un `SessionRecord` pequeño, semántico y con campos permitidos explícitamente; construir un `GraphState` efímero en RAM; ejecutar LangGraph sin checkpointer persistente; consolidar el siguiente `SessionRecord`; y persistirlo antes de emitir el HTTP response.

El `GraphState` no es un contrato durable. No se persisten tools, schemas de tools, SDK clients, objetos internos de LangGraph, checkpoints ni estado arbitrario del grafo.

LangGraph orquesta el turno técnico y el LLM conserva la responsabilidad conversacional. Una futura `pending_operation` durable puede exigir escrituras adicionales antes o después de un side effect empresarial; no se introducen escrituras por super-step o por internals de LangGraph.

Ante un crash a mitad del turno, el siguiente request reinicia desde la última sesión durable. Last-writer-wins por documento se acepta mientras XCALLY ejecute secuencialmente por `conversation_id`; evidencia de concurrencia real del mismo conversation obliga a reabrir optimistic locking o transacciones.

## Boundary HTTP

**PROVISIONAL — implemented DEV baseline.** CU013 materializa un boundary HTTP mínimo para DEV. El contrato implementado, sus restricciones y su evolución basada en evidencia viven en [Boundary HTTP XCALLY ↔ CU013](xcally-boundary.md); no constituye todavía el contrato integrado final con Cally Square ni define órdenes/resultados AD/TIVIT.

**PROVISIONAL — two temporary serializers.** Un único dominio de transición alimenta el envelope legacy y el envelope común `next-step-v1` seleccionado por el header canónico `X-CU013-Response-Contract`. El runtime decide `next_step` a partir del estado consolidado; el modelo no puede decidirlo. El contrato del modelo expone una señal semántica cerrada de relación con el goal (`goal_focus`: `PROGRESS | SIDE | NONE`): con un goal soportado pendiente, sin autorización y un turno que lo avanza (`PROGRESS`), el runtime exige la captura de identidad aunque el modelo haya propuesto `CONTINUE`; un turno lateral u off-topic (`SIDE`) responde y escucha preservando el goal, sin forzar identidad, acción ni handoff. La rotación fija de frases de progreso sobrevive sólo en el carril legacy y el feedback contextual v1 puede delegar una única redacción estrecha sin cambiar estado empresarial.

## Entorno GCP actual

**IMPLEMENTED AND VERIFIED BY OWNER.**

```yaml
gcp:
  project_id: tivit-cu013-prd
  organization: ylopevia-org
  primary_region: us-east1
```

Recursos actuales:

- Firestore `(default)`, Native mode, Standard edition, `us-east1`.
- Artifact Registry `cu013-containers-dev`, formato Docker, `us-east1`.
- Cloud Run `cu013-runtime-dev` desplegado en `us-east1` como entorno DEV PROVISIONAL; estado de reposo `min instances = 0` y `min = 1` sólo durante ventanas autorizadas de benchmark o de validación DEV de voz controlada.
- Vertex AI habilitado; el motor real ejecuta el baseline conversacional
  activo (ubicación de modelo `us`; infraestructura en `us-east1`) y la
  selección productiva sigue pendiente de validación de voz.
- Secret Manager contiene el secreto DEV `cu013-api-key-dev`; Cloud Run lo consume por referencia con versión numérica, nunca por valor en el repositorio.

APIs habilitadas:

- `aiplatform.googleapis.com`
- `artifactregistry.googleapis.com`
- `firestore.googleapis.com`
- `iam.googleapis.com`
- `iamcredentials.googleapis.com`
- `run.googleapis.com`
- `secretmanager.googleapis.com`

## Estrategia de entornos efímeros

### Nivel 1 — actual y económico

El nivel actual usa el mismo proyecto GCP, Firestore `(default)`, colecciones SPIKE aisladas y una service account específica. No duplica recursos sin necesidad.

Su objetivo es experimentación barata, contenida y auditable.

### Nivel 2 — futuro y de alta fidelidad

Un nivel futuro puede usar un proyecto GCP efímero completo, recursos equivalentes al entorno objetivo, IAM reproducible y lifecycle explícito.

Este nivel no está implementado. Su necesidad recurrente es un trigger para reconsiderar Terraform.

## Identidades

- `cu013-cloud-run-sa@tivit-cu013-prd.iam.gserviceaccount.com`: identidad de menor privilegio del servicio Cloud Run DEV (en uso). Tiene `roles/datastore.user` y `roles/aiplatform.user`, y sólo accede a los secretos DEV por binding a nivel de secreto. No se usa impersonation.
- Las identidades `cu013-spike-firestore`, `cu013-runtime-dev` y `cu013-deployer-dev` pertenecen al proyecto anterior `cu013-xcally-agentic` y se conservan como historia.

**INVARIANT.** No se permiten long-lived service-account keys.

## Configuración y secretos

```text
config.yaml
→ configuración no sensible y versionable

.env
→ local-only, gitignored, valores sensibles o provisionales para DEV/SPIKE

Secret Manager
→ secretos reales inyectados en servicios cloud cuando existan
```

Configuración operacional y secretos son categorías distintas. En DEV existe `cu013-api-key-dev`, consumido por Cloud Run por referencia; los accesos son bindings a nivel de secreto, nunca valores versionados.

## Disciplina de costos

- PoC/DEV está orientado a bajo costo.
- Cloud Run DEV opera con `min instances = 0` y `max instances = 1`; `min = 1` existe sólo durante una ventana autorizada de benchmark o de validación DEV de voz controlada y se restaura a 0 al terminar, pase o falle.
- No se crearán recursos always-on innecesarios ni una segunda base Firestore por defecto.
- No se añadirán VPC, Cloud SQL, Redis, Kubernetes u observabilidad pesada sin evidencia.
- El presupuesto y alerta económica se gestionan externamente; no son un hard cap técnico.

## Región

`us-east1` es la región primaria actual. No demuestra ser la región óptima.

`southamerica-east1` permanece como alternativa futura a benchmarkear, especialmente por cercanía con AD/TIVIT en Brasil. No es failover ni región secundaria activa.

## Terraform

**Status: DEFERRED.** No debe crearse `infra/terraform/` en esta etapa.

Reconsiderar Terraform cuando ocurra al menos uno de estos triggers:

- topología DEV estable;
- staging o producción;
- recreación frecuente;
- proyectos efímeros repetibles;
- drift manual significativo;
- necesidad de plan/review declarativo;
- IAM o infraestructura demasiado complejos para scripts `gcloud` auditables.

## Modelo

El baseline conversacional activo es Gemini 3.5 Flash-Lite sobre Vertex AI
(Vertex AI, location `us`, thinking `MINIMAL`, attempts `1`, timeout
`30000 ms`, `ModelTurnDecision` max_output_tokens `256`), P1
semantic_obligation, confirmación HITL runtime-owned, ventana inmediata de
challenge, Thin Firestore session repository, una llamada de modelo por
transcript normal, next-step-v1 y password efímera por voz. La
infraestructura (Cloud Run, Firestore) sigue en `us-east1`: no confundir la
ubicación del modelo con la región de infraestructura.

**IMPLEMENTED (baseline sintético, no validado en voz ni producción).**
El motor real está integrado detrás del seam conversacional sobre Vertex AI
con ADC, sin streaming ni tools, con output estructurado tipado y un solo
attempt por turno. La identidad efectiva del baseline se deriva de
`config.yaml` y `app/conversation`; el harness calcula su fingerprint en
runtime sobre prompt, schemas, renderer, procedimiento, runtime, lock,
corpus, runner, comparador y gate crítico. No existe manifiesto JSON
canónico paralelo. La historia de selección vive en la ADR de selección
vigente, el Experimento 0009 y Git. Las métricas futuras usan nombres
observables completos y cada gate declara qué mide, qué casos incluye,
numerador, denominador, tratamiento de INFRA y criterio de aceptación.

## Seguridad y observabilidad

Los logs deben ser estructurados y PII-safe. Nunca deben contener credenciales, contraseñas, tokens, transcripciones completas ni datos personales crudos.

La observabilidad mínima debe permitir correlacionar conversación, turno, ruta, latencia, cantidad de llamadas al modelo, tool y clase de error sin exponer datos sensibles. Los nombres concretos del schema siguen TBD.

## Entrega y validación

GitHub Actions es la plataforma CI/CD aceptada. `dev` es la rama normal de trabajo y `main` representa releases aceptados.

Los cambios conversacionales aceptados requieren validación de voz en DEV. Los tests locales no sustituyen ASR/TTS ni la llamada real.

Antes de integrar una iteración aceptada se actualiza [CONTEXT.md](../../CONTEXT.md). El agente no debe hacer commit o push sin autorización explícita.

Las convenciones de implementación subordinadas a esta SPEC y a los ADR Accepted están en [Python](../engineering/python.md), [fiabilidad](../engineering/reliability.md) y [testing](../engineering/testing.md).
