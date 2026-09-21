# CU013 v0.2.0 — Boundary HTTP XCALLY ↔ CU013

## Estado y alcance

Status: PROVISIONAL — implemented DEV baseline

Este documento describe los dos contratos HTTP implementados y probados hoy sobre el Thin Firestore Session Repository:

1. el turno conversacional `POST /turns`;
2. el boundary técnico `POST /integration-events`, por el que XCALLY informa resultados de identidad, fallos del canal de voz y estados/errores de la operación externa autorizada.

El contrato de identidad deja de transportar DTMF crudo: Cally Square captura y valida dentro del flujo y CU013 sólo recibe un resultado PII-safe. El contrato de órdenes/resultados AD/TIVIT sigue siendo experimental en su semántica externa; lo materializado aquí es el contrato *local* backend↔TEST y sus reglas de correlación, no los shapes reales de RD/AD.

Puede evolucionar con evidencia obtenida al integrar el flujo Cally Square rediseñado y AD/TIVIT, mediante caller tests/logs PII-safe y mediciones reales de latencia. Mientras conserve el estado `PROVISIONAL`, son aceptables cambios incompatibles respaldados por esa evidencia. No se modifica por especulación.

Evidencia de origen: XML CU013/RD, `DOC_API_RD.pdf`, comportamiento confirmado por el propietario y el traspaso del flujo destino `TEST_XCALLY_CU013_API_APPROACH`. Los números de nodo de ese XML son evidencia de diseño, no contrato.

### Validación disponible

- Cloud Run DEV validó el boundary pre-XCALLY de punta a punta en el [Experimento 0004](../experiments/0004-cloud-run-latency.md): autenticación, contrato y turno real con Gemini.
- La latencia voice E2E (`end-of-speech → first useful audio`) sigue desconocida: no hay XCALLY, ASR ni TTS integrados.
- El contrato técnico de esta iteración se validó con tests deterministas y dobles; no hay todavía evidencia E2E de identidad real, RD real, polling real ni handoff real ([Experimento 0010](../experiments/0010-integration-events-contract.md)).

## Autenticación común

```text
Content-Type: application/json
X-API-Key: <secret>
X-Request-ID: <valor opaco de correlación>   (opcional)
```

- `X-API-Key` se valida contra un secreto leído únicamente del entorno (`CU013_API_KEY`), nunca de `config.yaml`, código, logs o fixtures, y se compara con `secrets.compare_digest`.
- Sin secreto configurado el servicio falla cerrado (`internal`, 500). Ausente o incorrecta producen la misma respuesta `authorization` (401), sin distinguir el caso.
- `X-Request-ID` es correlación HTTP, no una idempotency key del side effect, y no se registra.

## Turno conversacional — `POST /turns`

### Endpoint

```text
POST /api/v1/conversations/{conversation_id}/turns
```

- `conversation_id` es la identidad durable de la sesión (`UNIQUEID` observado en XCALLY).
- Cada request recibe un `turn_id` único generado internamente y devuelto en la respuesta para trazabilidad; XCALLY no está obligado a consumirlo.
- `X-Request-ID` no demuestra unicidad por request y no se usa como idempotency key.

### Request

Sólo transcript ASR; `transcript` es obligatorio y las variantes anteriores sin `asr_confidence` ni `channel` siguen siendo válidas:

```json
{
  "transcript": "{GOOGLE_ASR_TRANSCRIPT}",
  "asr_confidence": 0.0,
  "channel": "voice"
}
```

El modelo cierra el contrato con `extra="forbid"`: un campo desconocido no se acepta. Las formas crudas de identidad (`IDENTITY_DATA`, `document_id`, fecha de ingreso o cualquier DTMF) fueron retiradas del contrato activo y se rechazan como payload inválido: el backend no necesita documento ni fecha para conversar ni para conservar autorización. La captura y validación pertenecen a XCALLY; su resultado llega por `/integration-events`.

### Response

Éxito (200):

```json
{
  "message": "...",
  "route": "CONTINUE",
  "turn_id": "opaque-turn-id",
  "command": null
}
```

`message` y `route` son los campos que consume Cally Square. `command` es `null` salvo que la ruta sea `EXECUTE_ACTION`:

```json
{
  "message": "Voy a procesar la solicitud. Puede tardar unos segundos.",
  "route": "EXECUTE_ACTION",
  "turn_id": "opaque-turn-id",
  "command": {
    "operation_id": "opaque-operation-id",
    "action": "UNLOCK_ACCOUNT",
    "goal_revision": 2
  }
}
```

Rutas de la respuesta (enum cerrado `BoundaryRoute`): `CONTINUE`, `COLLECT_IDENTITY`, `COMPLETE`, `ESCALATE`, `EXECUTE_ACTION`.

El modelo sólo puede proponer las cuatro rutas conversacionales (`Route`); su contrato y esquema no incluyen `EXECUTE_ACTION`. La ruta `EXECUTE_ACTION` la produce exclusivamente el runtime cuando crea y persiste un guard de despacho legal, y entonces reemplaza el mensaje del modelo por el mensaje canónico de procesamiento.

### Invariantes del comando

`command` sólo puede existir con `route == EXECUTE_ACTION`, y `EXECUTE_ACTION` siempre lleva `command`. `action` es el enum cerrado `RESET_PASSWORD | UNLOCK_ACCOUNT`.

El runtime crea la orden sólo si:

1. el goal y su revisión están vigentes;
2. la identidad está válida y no expirada (TTL absoluto de 30 minutos);
3. existe confirmación verbal afirmativa ligada a esa acción y a esa revisión, con el mismo `validated_at`;
4. no existe otra operación externa activa;
5. los intentos de identidad del llamante no están agotados (al tercer fallo procede handoff, no despacho);
6. el save durable que persiste el guard completó antes del HTTP response.

La orden no contiene documento, fecha, teléfono, email, password, contraseña temporal, API key RD, URL RD, payload RD, `CALLERID(Name)`, `codigo` ni `callId`. `operation_id` pertenece a CU013 y viaja por TEST como variable opaca; `goal_revision` queda ligado al mismo guard.

Una acción desconocida nunca hace fallback a desbloqueo: el mapeo `RESET_PASSWORD → comando RD "reset"` y `UNLOCK_ACCOUNT → comando RD "desbloqueio"` pertenece a XCALLY, no al LLM ni al backend.

## Eventos técnicos — `POST /integration-events`

### Endpoint

```text
POST /api/v1/conversations/{conversation_id}/integration-events
```

Este endpoint:

- no acepta transcript;
- no llama al LLM en ningún caso;
- no acepta DTMF, documento, fecha de ingreso, password ni email (cerrado con `extra="forbid"`);
- modifica sólo estado técnico/empresarial autorizado del `SessionRecord`;
- devuelve instrucciones pequeñas para que TEST decida TTS, polling o retorno a la conversación.

Usa un discriminated union cerrado sobre `event`.

### Evento de identidad PII-safe

```json
{
  "event": "IDENTITY_VALIDATION_RESULT",
  "outcome": "VALID",
  "validation_reference": "opaque-reference"
}
```

`outcome` ∈ `VALID | INVALID | TECHNICAL_FAILURE`. `validation_reference` es opcional y sólo se acepta como correlación de transporte: el runtime no lo persiste ni lo registra, de modo que una referencia no acreditada como no sensible no puede filtrarse.

Dos dominios separados, que no deben confundirse ni atribuirse entre sí:

```text
External lookup state (validauser por documento):
    FOUND | NOT_FOUND | technical error

CU013/XCALLY identity outcome (lo que recibe el backend):
    VALID | INVALID | TECHNICAL_FAILURE
```

**FOUND != VALID.** `FOUND` sólo acredita que el lookup encontró un registro para el documento; puede existir antes de capturar la fecha de ingreso y no valida nada por sí solo. El contador de intentos pertenece al runtime CU013; `validauser` no lo conoce ni lo devuelve.

Comportamiento, con cero llamadas al modelo:

| `outcome` | Efecto durable | Directiva | Mensaje |
|---|---|---|---|
| `VALID` | marca `identity.validated_at = now` según TTL; invalida cualquier challenge anterior; no ejecuta acción | `RESUME_CONVERSATION` | sí |
| `INVALID` | incrementa sólo los fallos imputables al caller; bajo el máximo pide nueva captura; al tercer fallo aplica el handoff ya definido por la SPEC | `COLLECT_IDENTITY` / `ESCALATE` | sí |
| `TECHNICAL_FAILURE` | no consume intento, no autoriza y no inventa causa: la fase de identidad permanece abierta | `COLLECT_IDENTITY` | sí |

### Secuencia de identidad aceptada para el diseño E2E

```text
GetDigits captura DOCUMENTO
→ GET /validauser/TIVIT/{DOCUMENTO}
→ NOT_FOUND            → XCALLY genera IDENTITY_VALIDATION_RESULT: INVALID
→ FOUND                → solicitar FECHA DE INGRESO
→ GetDigits DDMMYYYY (8 dígitos)
→ comparar con resposta2 del registro recuperado
   → coincide          → IDENTITY_VALIDATION_RESULT: VALID
   → no coincide       → IDENTITY_VALIDATION_RESULT: INVALID
→ timeout / HTTP error / body inesperado
                       → IDENTITY_VALIDATION_RESULT: TECHNICAL_FAILURE
→ sólo tras VALID: CU013 retoma y corresponde la confirmación verbal
→ sólo tras confirmación válida: CU013 puede emitir EXECUTE_ACTION
```

El documento y la fecha de ingreso se capturan por DTMF en XCALLY y nunca llegan al backend.

**Gate de realidad.** La consulta por documento `GET https://urawps.tivit.com/prod-v2/api/v1/resetunlock/validauser/TIVIT/{DOCUMENTO}` y sus estados `FOUND`/`NOT_FOUND` están acreditados; el schema local se implementa y prueba con dobles. Falta demostrar E2E que XCALLY captura la fecha de ingreso, la compara correctamente con `resposta2`, genera el outcome local correcto y que CU013 sólo autoriza tras `VALID` (ID-001).

### Evento de fallo del canal de voz

```json
{
  "event": "VOICE_INPUT_FAILURE",
  "reason": "LOW_CONFIDENCE"
}
```

`reason` ∈ `NO_SPEECH | LOW_CONFIDENCE | TIMEOUT`. No se envía transcript parcial.

- Con challenge de confirmación pendiente: el intento no autoriza y el challenge queda invalidado (no se reutiliza; un challenge nuevo se creará ligado a la acción y revisión vigentes). La identidad válida permanece y no se consume intento de identidad. Directiva `RETRY_SPEECH` con re-prompt seguro.
- Sin challenge: no se inventa estado empresarial; directiva `RETRY_SPEECH` con re-prompt seguro.

El backend no impone un límite nuevo de reintentos de voz.

### Estado de la acción externa

```json
{
  "event": "ACCOUNT_ACTION_STATUS",
  "operation_id": "opaque-operation-id",
  "action": "UNLOCK_ACCOUNT",
  "goal_revision": 2,
  "status": "NONE"
}
```

`status` acepta cualquier literal y se interpreta contra los literales observados: `NONE`, `SUCESSO`, `CPF_NAO_ENCONTRADO`, `ERRO_NA_VALIDACAO`, `FALHA_AD`, `USUARIO_DESABILITADO`, `USUARIO_EXPIRADO`. Cualquier otro valor se trata como `UNRECOGNIZED` a nivel interno: se ACKea, no se muta estado y se conserva telemetría segura (un contador, nunca el valor).

El backend no necesita el body RD completo. Este evento no transporta password, identidad, email, documento, fecha, body RD, API key ni URL RD, y no hace obligatorios `codigo` ni `callId`: `operation_id` es la correlación primaria backend↔TEST.

### Error técnico

```json
{
  "event": "ACCOUNT_ACTION_ERROR",
  "operation_id": "opaque-operation-id",
  "action": "UNLOCK_ACCOUNT",
  "goal_revision": 2,
  "phase": "DISPATCH",
  "error_kind": "TIMEOUT",
  "http_status": null
}
```

Enums mínimos: `phase ∈ DISPATCH | POLL`; `error_kind ∈ TIMEOUT | HTTP_ERROR | INVALID_BODY | UNAVAILABLE`. No se devuelve ni persiste el body de error RD.

### Response

Respuesta plana para Cally Square:

```json
{
  "acknowledged": true,
  "operation_state": "PENDING",
  "directive": "POLL_RD",
  "message": null
}
```

- `directive` ∈ `NOOP | RETRY_SPEECH | COLLECT_IDENTITY | POLL_RD | RESUME_CONVERSATION | COMPLETE | ESCALATE`. No reutiliza el enum `route` conversacional.
- `operation_state` es la proyección de cable del estado durable canónico: `pending→PENDING`, `unknown→UNKNOWN`, `confirmed→SUCCEEDED`, `failed→FAILED`; es `null` cuando el evento no involucra una operación externa.
- `message` es `null` cuando TEST no debe sonar TTS; en caso contrario es una frase PII-safe del runtime.

## Máquina de estado durable de la operación

Se reutiliza el enum canónico `OperationStatus` (`pending`, `unknown`, `confirmed`, `failed`); no existe un segundo enum durable. Estados conceptuales: autorizada-no-entregada y orden-entregada-a-XCALLY corresponden a `pending` (el guard y la operación se crean en el mismo turno que emite la orden); pendiente y resultado incierto son `pending` y `unknown`; éxito y fallo confirmados son `confirmed` y `failed`.

Transiciones:

| Evento | Desde | Hacia |
|---|---|---|
| guard durable persistido | — | `pending` (orden entregable en la respuesta `/turns`) |
| `ACCOUNT_ACTION_STATUS/NONE` | `pending` | `pending` (idempotente; puede emitir progreso) |
| `ACCOUNT_ACTION_STATUS/NONE` | `unknown` | `unknown` (un no-terminal no prueba entrega) |
| `ACCOUNT_ACTION_STATUS/SUCESSO` | `pending` o `unknown` | `confirmed` |
| status de fallo conocido | `pending` o `unknown` | `failed` |
| `ACCOUNT_ACTION_ERROR/DISPATCH` | `pending` | `unknown` |
| `ACCOUNT_ACTION_ERROR/DISPATCH` | `unknown` | `unknown` (idempotente) |
| `ACCOUNT_ACTION_ERROR/POLL` | cualquier estado activo | sin cambio de estado |
| terminal idéntico repetido | `confirmed`/`failed` | sin cambio (ACK idempotente) |
| terminal distinto o error de dispatch sobre terminal | `confirmed`/`failed` | rechazo `conflict_or_duplicate` (409), sin overwrite |
| late `NONE` o error de poll sobre terminal | `confirmed`/`failed` | sin cambio; directiva terminal sin TTS |

No se repite automáticamente el POST tras `UNKNOWN`; un terminal correlacionado posterior reconcilia la misma operación.

### Terminales

- `UNLOCK_ACCOUNT` + `SUCESSO`: se persiste `confirmed` y se devuelve `COMPLETE` con `"El desbloqueo fue confirmado correctamente."`. No se mencionan AD, RD, Orchestrator ni detalles internos.
- `RESET_PASSWORD` + `SUCESSO`: se persiste el reset confirmado, pero no se trata como entrega confirmada. SendMail sigue Deferred, la contraseña temporal nunca llega a CU013 y el reset no se declara completado al caller mientras el contrato de entrega siga abierto: directiva `RESUME_CONVERSATION` con un mensaje que sólo afirma el reset confirmado.
- Fallos RD conocidos: se persiste `failed` sin inventar semántica más específica que la evidencia. Baseline local: mensaje seguro grounded y `RESUME_CONVERSATION`, salvo que una regla Accepted obligue inequívocamente a `ESCALATE`. Mientras XC-006 siga abierto no se codifica una tabla irreversible status RD → escalamiento; el E2E decidirá el mapping final.

## Correlación, duplicados y late results

Antes de mutar estado por un evento de acción se comprueba: la sesión existe; la operación existe; la operación es la activa o reconciliable; `operation_id`, `action` y `goal_revision` coinciden con el guard durable; y el estado actual permite la transición. Cualquier incumplimiento produce `conflict_or_duplicate` (409) sin mutación.

- `NONE` repetido es idempotente; un terminal idéntico repetido es un ACK idempotente; un terminal distinto después de terminal es un conflicto seguro sin overwrite.
- Nunca se crea una operación a partir de un resultado recibido y nunca se re-despacha por recibir un evento.
- No se promete exactly-once. No se introducen transacciones Firestore globales por prevención: la entrada técnica sigue el mismo supuesto secuencial por `conversation_id` ya aceptado; si XCALLY llegara a solapar `/turns` y `/integration-events` para una misma conversación, la política de concurrencia Accepted debe reabrirse antes de producción.

## Anti-silencio

El backend controla los mensajes y TEST controla el polling; ni `/turns` ni `/integration-events` se sostienen abiertos durante los 20–80 s que puede durar RD, y no se usa WebSocket, streaming ni barge-in.

1. El `/turns` que devuelve `EXECUTE_ACTION` incluye `"Voy a procesar la solicitud. Puede tardar unos segundos."`; TEST lo reproduce antes del POST RD.
2. TEST hace POST RD, GET inmediato y envía a CU013 un evento terminal o `NONE`; no reproduce un mensaje de espera antes de comprobar si ya existe resultado terminal.
3. Ante `NONE`, CU013 decide sin LLM si corresponde otro mensaje. Persiste sólo metadata técnica mínima (`last_progress_feedback_at`, `progress_feedback_index` del `external_operation`).
4. Intervalo experimental de progreso: 10 s iniciales, coherente con el `wait 10` observado. El valor final sólo se acepta tras E2E. El primer `GET` inmediato normalmente no produce segundo TTS.

Frases de progreso permitidas:

- `"Sigo procesando tu solicitud. Gracias por esperar."`
- `"La solicitud continúa en proceso. Te avisaré cuando tenga un resultado."`
- `"Todavía estoy esperando la confirmación. Gracias por permanecer en la llamada."`

Prohibidas mientras no exista terminal: `"Ya casi termina."`, `"AD está respondiendo."`, `"Tu cuenta ya fue encontrada."`, `"Está al 80%."`, `"El desbloqueo fue exitoso."`.

## Errores

Envelope estable; nunca se serializa detalle de Pydantic/FastAPI ni se ecoan transcript, DTMF o payloads:

```json
{
  "error": { "code": "<taxonomía>", "message": "<mensaje estático>" }
}
```

| `code` | HTTP | Condición |
|---|---|---|
| `validation` | 422 | Payload inválido o JSON malformado |
| `authorization` | 401 | `X-API-Key` ausente o incorrecta |
| `conflict_or_duplicate` | 409 | Evento técnico no correlacionable o transición ilegal |
| `dependency_unavailable` | 503 | Motor conversacional o servicio técnico no configurado; fallo/indisponibilidad del modelo; fallo durable al cargar/guardar |
| `dependency_timeout` | 504 | La llamada al modelo excedió su deadline |
| `internal` | 500 | Fallo no esperado, salida del modelo fuera del contrato tipado o API key no configurada |

El shape exacto de errores que Cally Square interpreta sigue pendiente de evidencia integrada (XC-005, XC-006).

## PII y privacidad

- El DTMF crudo ya no existe en el contrato activo: no hay modelo transitorio que lo contenga y ningún payload lo acepta.
- `/integration-events` no acepta documento, fecha de ingreso, email, password ni secretos; sus dobles usan canarios sintéticos generados en test.
- `validation_reference` se acepta y se descarta: no se persiste, no se registra, no se devuelve.
- Nunca se persiste el body RD, la contraseña temporal ni un payload de error RD; la telemetría de un status desconocido es sólo un contador.
- Los errores de validación no registran el payload; sólo se registra la ruta, el tipo de evento y el hecho del fallo.

## Persistencia

- Reutiliza el Thin Firestore Session Repository de [ADR-0009](../decisions/0009-use-thin-firestore-session-repository.md): un load, el modelo dentro del grafo LangGraph en RAM sin persistent checkpointer y un save antes del HTTP response.
- El grafo del turno es `START → run_model → advance_turn → END`; la consolidación durable excluye transcript y decisión del modelo.
- `/integration-events` no usa el grafo ni el modelo: un load y, sólo si el evento muta estado, un save. No incrementa `turn_count` ni `revision`.
- `external_operation` añade la metadata técnica mínima de anti-silencio (`last_progress_feedback_at`, `progress_feedback_index`). Los documentos v2 previos sin esos campos siguen validando por default.

## Abierto

- Resultado positivo de validación de identidad y su integración con AD/TIVIT (ID-001).
- Correlación, idempotencia, polling, reintentos y resultados tardíos de XCALLY (XC-002 a XC-004).
- Shape real de responses/errors y mapeo de estados externos (XC-005, XC-006).
- Deadline explícito de Firestore (FS-002).
- Mapeo final status RD → experiencia/handoff y validación E2E de anti-silencia y terminales.

## Trazabilidad

- [Especificación del sistema](system.md)
- [Especificación de acciones de cuenta](account-actions.md)
- [Gaps de implementación](../gaps.md)
- [Experimento 0010 — Contrato de eventos técnicos](../experiments/0010-integration-events-contract.md)
- [Boundary XCALLY / Orchestrator / TIVIT](account-actions.md#boundary-xcally--orchestrator--tivit)
