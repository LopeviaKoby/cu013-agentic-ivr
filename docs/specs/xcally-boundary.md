# CU013 v0.2.0 — Boundary HTTP XCALLY ↔ CU013

## Estado y alcance

Status: PROVISIONAL — implemented DEV baseline

Este documento describe los dos contratos HTTP implementados y probados hoy sobre el Thin Firestore Session Repository:

1. el turno conversacional `POST /turns`;
2. el boundary técnico `POST /integration-events`, por el que XCALLY informa resultados de identidad, fallos del canal de voz y estados/errores de la operación externa autorizada.

El contrato de identidad deja de transportar DTMF crudo: Cally Square captura y valida dentro del flujo y CU013 sólo recibe un resultado PII-safe. El contrato de órdenes/resultados AD/TIVIT sigue siendo experimental en su semántica externa; lo materializado aquí es el contrato *local* backend↔TEST y sus reglas de correlación, no los shapes reales de RD/AD.

Un único dominio de transición alimenta dos adaptadores HTTP temporales. Sin el header selector, la respuesta legacy permanece byte-compatible; con `CU013-Response-Contract: next-step-v1` ambos endpoints devuelven un envelope común cuyo `next_step` decide el runtime. Los vocabularios legacy `route` y `directive` quedan confinados a su adaptador; el contrato nuevo no los reutiliza. La rotación fija de frases de progreso sólo sobrevive en el carril legacy.

Puede evolucionar con evidencia obtenida al integrar el flujo Cally Square rediseñado y AD/TIVIT, mediante caller tests/logs PII-safe y mediciones reales de latencia. Mientras conserve el estado `PROVISIONAL`, son aceptables cambios incompatibles respaldados por esa evidencia. No se modifica por especulación.

Evidencia de origen: XML CU013/RD, `DOC_API_RD.pdf`, comportamiento confirmado por el propietario y el traspaso del flujo destino `TEST_XCALLY_CU013_API_APPROACH`. Los números de nodo de ese XML son evidencia de diseño, no contrato.

### Validación disponible

- Cloud Run DEV validó el boundary pre-XCALLY de punta a punta en el [Experimento 0004](../experiments/0004-cloud-run-latency.md): autenticación, contrato y turno real con Gemini.
- La latencia voice E2E (`end-of-speech → first useful audio`) sigue desconocida: no hay XCALLY, ASR ni TTS integrados.
- El contrato técnico de esta iteración se validó con tests deterministas y dobles; no hay todavía evidencia E2E de identidad real, RD real, polling real ni handoff real ([Experimento 0010](../experiments/0010-integration-events-contract.md)).
- El contrato `next-step-v1`, la secuencia de polling, la presentación de contraseña, el fallo de captura y el composer de feedback están implementados y cubiertos por tests deterministas; su semántica externa sigue sujeta a la evidencia E2E.

## Autenticación común

```text
Content-Type: application/json
X-API-Key: <secret>
X-Request-ID: <valor opaco de correlación>   (opcional)
```

- `X-API-Key` se valida contra un secreto leído únicamente del entorno (`CU013_API_KEY`), nunca de `config.yaml`, código, logs o fixtures, y se compara con `secrets.compare_digest`.
- Sin secreto configurado el servicio falla cerrado (`internal`, 500). Ausente o incorrecta producen la misma respuesta `authorization` (401), sin distinguir el caso.
- `X-Request-ID` es correlación HTTP, no una idempotency key del side effect, y no se registra.

## Selector de contrato de respuesta

Header opcional canónico:

```text
X-CU013-Response-Contract: next-step-v1
```

- La autenticación precede siempre al selector.
- Sin header: contrato legacy exacto, sin cambios de envelope ni de vocabulario.
- Con el valor exacto `next-step-v1`: envelope común `next-step-v1` en ambos endpoints.
- Header vacío, repetido o con una versión desconocida: `400` con
  `{"error": {"code": "unsupported_response_contract", "message": "unsupported response contract"}}`.
- El selector es explícito: nunca se infiere por la existencia de `route`, `directive`, `next_step` ni por heurística alguna.
- El nombre sin prefijo `X-` no se lee y no se conserva como alias: no tiene consumidor real acreditado. Un cliente que envíe el nombre antiguo recibe el contrato legacy (su header es ignorado), nunca el envelope v1.

**Evidencia E2E (2026-09-23).** Una llamada real envió el nombre sin `X-` y recibió el envelope legacy (`route`, `turn_id`) pese a que el Switch esperaba `next_step`; el valor por defecto del Switch derivó en transferencia. El diagnóstico fue `HEADER_MISMATCH`, no un fallo de despliegue ni de la revisión servida.

## Contrato next-step-v1

Con el selector activo, ambos endpoints responden `2xx` con exactamente estas cuatro claves:

```json
{
  "message": null,
  "next_step": "LISTEN",
  "operation_state": null,
  "command": null
}
```

`next_step` es un enum cerrado decidido por el runtime; el modelo no puede decidirlo ni proponerlo:

```text
LISTEN | COLLECT_IDENTITY | EXECUTE_ACTION | POLL_RD | DELIVER_PASSWORD | TRANSFER | COMPLETE
```

`operation_state` es `null` o la proyección de cable ya definida (`PENDING | UNKNOWN | SUCCEEDED | FAILED`). `command` sólo puede existir con `next_step=EXECUTE_ACTION`, y `EXECUTE_ACTION` siempre lleva `command`:

```json
{
  "message": null,
  "next_step": "EXECUTE_ACTION",
  "operation_state": null,
  "command": {
    "operation_id": "<opaque>",
    "action": "UNLOCK_ACCOUNT",
    "goal_revision": 2
  }
}
```

`message` es `null` cuando TEST no debe sonar TTS. Antes de serializar, el adaptador v1 normaliza sólo espacios en blanco de control (CR/LF/tab colapsan a un espacio y se colapsan las corridas de espacios); preserva Unicode, apóstrofos, comillas ASCII y backslash. La normalización nunca se aplica a contraseñas, documentos ni fechas, que no entran al backend.

Proyecciones por endpoint:

| Origen | `next_step` |
|---|---|
| `/turns`, ruta conversacional `CONTINUE` | `LISTEN` |
| `/turns`, ruta conversacional `COLLECT_IDENTITY` | `COLLECT_IDENTITY` |
| `/turns`, ruta conversacional `COMPLETE` | `COMPLETE` |
| `/turns`, ruta conversacional `ESCALATE` | `TRANSFER` |
| `/turns`, guard de despacho persistido | `EXECUTE_ACTION` |
| `IDENTITY_VALIDATION_RESULT` | `LISTEN` |
| `IDENTITY_VALIDATION_RESULT/INVALID` bajo el máximo | `COLLECT_IDENTITY` |
| `VOICE_INPUT_FAILURE` | `LISTEN` |
| `ACCOUNT_ACTION_STATUS` no terminal | `POLL_RD` |
| `ACCOUNT_ACTION_ERROR/POLL` no terminal | `POLL_RD` |
| `ACCOUNT_ACTION_ERROR/DISPATCH` | `POLL_RD` |
| `UNLOCK_ACCOUNT` confirmado | `COMPLETE` |
| `RESET_PASSWORD` confirmado sin presentación | `DELIVER_PASSWORD` |
| operación fallida o reset ya presentado | `LISTEN` |
| presupuesto de polling agotado | `TRANSFER` |
| `IDENTITY_INPUT_FAILURE` o máximo de fallos de identidad | `TRANSFER` |

**Precedencia de estado (owner decision).** El runtime deriva `next_step` del estado consolidado, no sólo de la propuesta del modelo. Con un goal soportado pendiente, identidad no válida y ninguna operación activa, el `CONTINUE` residual se proyecta a `COLLECT_IDENTITY`: el mensaje del modelo sigue respondiendo la necesidad inmediata y el goal se conserva, pero XCALLY recibe la capacidad que el estado exige. Los guards de `COMPLETE` y `ESCALATE` conservan su precedencia.

**Bootstrap pre-turno (next-step-v1).** Un `VOICE_INPUT_FAILURE` v1 válido puede crear la sesión ausente con un documento mínimo (`turn_count=0`, sin goal, sin identidad, sin challenge, sin dispatch ni operación) mediante un create condicional; nunca sobrescribe un documento concurrente. Cualquier otro primer evento produce `409` y cero escrituras, y el carril legacy no gana bootstrap. Mientras la sesión siga pre-turno, sólo un voice failure v1 se aplica; identidad, acción y password se rechazan con `409 pre_turn_event_not_allowed`. Un `/turns` válido posterior continúa la misma sesión y cierra el ciclo de reintentos.

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

| `outcome` | Efecto durable | Directiva legacy | `next_step` v1 | Mensaje |
|---|---|---|---|---|
| `VALID` | marca `identity.validated_at = now` según TTL; conserva goal y su revisión; invalida cualquier challenge anterior; crea un challenge nuevo ligado a la acción, revisión e identidad vigentes cuando el goal soportado está pendiente; no ejecuta acción | `RESUME_CONVERSATION` | `LISTEN` | sí |
| `INVALID` | incrementa sólo los fallos imputables al caller; bajo el máximo pide nueva captura; al tercer fallo aplica el handoff ya definido por la SPEC | `COLLECT_IDENTITY` / `ESCALATE` | `COLLECT_IDENTITY` / `TRANSFER` | sí |
| `TECHNICAL_FAILURE` | no consume intento, no autoriza y no inventa causa: la fase de identidad permanece abierta | `COLLECT_IDENTITY` | `COLLECT_IDENTITY` | sí |

Tras `VALID`, el runtime produce la confirmación específica por acción (`UNLOCK_ACCOUNT` o `RESET_PASSWORD`) y abre el challenge sin una segunda llamada al modelo; una afirmación posterior sólo puede autorizar ese challenge. Si no existe goal, `VALID` no inventa uno y responde con la confirmación genérica.

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

### Secuencia de polling, deduplicación y presupuesto (next-step-v1)

En el contrato v1, `ACCOUNT_ACTION_STATUS` y `ACCOUNT_ACTION_ERROR/POLL` exigen `poll_sequence`; `ACCOUNT_ACTION_ERROR/DISPATCH` no lo lleva y nunca consume presupuesto de GET. El contrato legacy sigue rechazando `poll_sequence` como campo desconocido.

```json
{
  "event": "ACCOUNT_ACTION_STATUS",
  "operation_id": "opaque-operation-id",
  "action": "UNLOCK_ACCOUNT",
  "goal_revision": 2,
  "status": "NONE",
  "poll_sequence": 1
}
```

Reglas del piloto:

- entero estricto mayor que cero; la primera secuencia es `1` y cada observación nueva es `last + 1`;
- límite de `9` GET iniciados (`observation_limit`); el presupuesto y la cadencia de feedback son independientes entre sí y de cualquier deadline;
- mismo `poll_sequence` con la misma observación (fingerprint SHA-256 del tipo cerrado) es un ACK idempotente que no consume presupuesto ni vuelve a sonar;
- mismo `poll_sequence` con observación distinta, o un salto de secuencia, produce `conflict_or_duplicate` (409) sin mutación;
- un replay nunca consume presupuesto;
- un status desconocido y un error de GET consumen una observación; un error de dispatch no consume presupuesto de GET;
- una observación terminal consume su secuencia y termina la operación;
- al llegar a la novena observación no terminal, `next_step=TRANSFER` sin cambiar `PENDING`/`UNKNOWN` a `FAILED`; una observación no terminal posterior al límite es un 409 y un terminal posterior todavía reconcilia la misma operación;
- nunca se repite el `POST /call`.

El fingerprint se calcula sólo sobre el tipo cerrado de observación (y, en errores, sobre `phase`, `error_kind` y `http_status`): el literal RD desconocido nunca se persiste.

### Fallo de captura de identidad (next-step-v1)

```json
{
  "event": "IDENTITY_INPUT_FAILURE",
  "reason": "CAPTURE_EXHAUSTED"
}
```

Sólo `CAPTURE_EXHAUSTED`. No es `INVALID`, no suma intentos imputables al caller, conserva el goal, no toca la operación externa y responde `next_step=TRANSFER`. El contrato legacy lo rechaza.

### Presentación de contraseña (next-step-v1)

```json
{
  "event": "PASSWORD_PRESENTATION_RESULT",
  "operation_id": "opaque-operation-id",
  "action": "RESET_PASSWORD",
  "goal_revision": 2,
  "voice": "PLAYBACK_RETURNED",
  "email_requested": 1,
  "email_acceptance": "UNKNOWN",
  "email_delivery": "UNKNOWN"
}
```

- Sólo aplica a `RESET_PASSWORD` confirmado por el boundary; la contraseña nunca entra al backend.
- `voice` sólo admite `PLAYBACK_RETURNED`; `email_requested` es un entero estricto `0/1`; aceptación y entrega comienzan sólo en `UNKNOWN`.
- Un duplicado idéntico es un ACK idempotente; un evento incompatible o tardío es un 409. Un duplicado nunca reemite `DELIVER_PASSWORD`.
- Mientras la entrega siga `UNKNOWN`, la respuesta es `next_step=LISTEN` sin afirmar envío ni entrega.
- El contrato legacy lo rechaza.

### Feedback de espera contextual (next-step-v1)

En v1 no existe rotación fija de frases. El orden es: observación → correlación → verdad externa → terminalidad → presupuesto → `feedback_due` → redacción opcional → validación → persistencia → `200`.

- No hay llamada al modelo cuando la observación es terminal, es un duplicado, el presupuesto está agotado o el feedback no está vencido.
- Cuando corresponde, hay exactamente una llamada estrecha de redacción (`PollingFeedbackComposer`) cuya entrada PII-safe se limita a acción, revisión, confirmación obtenida, estado de operación, tipo de observación cerrado, secuencia, observaciones usadas, límite y hasta dos mensajes previos ya validados. Excluye transcript, ventana textual, documento, fecha, identidad, `operation_id`, body RD, status desconocido crudo, contraseña, email y PII espontánea.
- La salida es sólo `message`: el composer no puede devolver ni modificar `next_step`, `operation_state`, autorización, despacho ni identidad.
- Ante timeout, salida inválida o texto no admisible: `message=null`, estado empresarial intacto, metadata segura de polling preservada, sin frase rotatoria, sin segunda llamada y sin re-POST.
- Se persisten como máximo dos mensajes validados; la cadencia candidata es de 10 s y no es un SLO.

### Response

Respuesta legacy plana para Cally Square:

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

Con el selector `next-step-v1` la respuesta es el envelope común descrito arriba; `directive` no viaja.

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
3. Ante `NONE`, CU013 decide sin LLM si corresponde otro mensaje. Persiste sólo metadata técnica mínima.
4. Intervalo experimental de progreso: 10 s iniciales, coherente con el `wait 10` observado. El valor final sólo se acepta tras E2E. El primer `GET` inmediato normalmente no produce segundo TTS.

En el carril legacy (sin secuencia de polling) la decisión es determinista y persiste `last_progress_feedback_at` y `progress_feedback_index` del `external_operation`. En el carril `next-step-v1` la cadencia vive en el plano `polling` (`last_feedback_attempt_at`, hasta dos mensajes validados) y la redacción puede delegarse en el composer estrecho; la rotación fija no se usa.

Frases de progreso permitidas (sólo carril legacy):

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
| `unsupported_response_contract` | 400 | Header selector vacío, repetido o con versión desconocida |
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
- El fingerprint de una observación hashea sólo el tipo cerrado (y los campos técnicos de error), nunca el literal externo crudo.
- El composer de feedback recibe sólo la proyección PII-safe descrita y nunca transcript, memoria textual, documento, fecha, identidad, `operation_id`, body RD, status desconocido crudo, contraseña ni email.
- La memoria textual reciente y la ventana experimental no se activan para callers reales en esta iteración; el path productivo no persiste transcript.

## Observabilidad

- Un único namespace padre `cu013` con un `StreamHandler` a stderr, nivel INFO y sin propagación al root; `cu013.app` y `cu013.metrics` son hijos sin handlers propios. Cloud Run recoge stdout/stderr sin SDK ni agente.
- Eventos cerrados: `response_contract_selected` (lane, response_contract), `turn_handled` (lane, response_contract, next_step), `integration_event_received` (lane, response_contract, event_type), `integration_event_accepted` (event_type, next_step, operation_state), `integration_event_rejected` (event_type, normalized_rejection_reason), `http_result` (lane, response_contract, http_status) y `request_validation_failed` (lane, facts de `loc`/`type`).
- El baseline INFO no incluye conversation ID, turn ID, operation ID, trace, request ID ni rutas completas. Los rechazos usan un vocabulario cerrado (`unknown_session`, `pre_turn_event_not_allowed`, `operation_missing`, `operation_mismatch`, `action_mismatch`, `dispatch_mismatch`, `revision_mismatch`, `illegal_transition`, `poll_sequence_conflict`, `password_presentation_conflict`) y nunca el texto libre.
- Una validación fallida registra sólo la ubicación y el tipo (`body.transcript:missing`, `ACCOUNT_ACTION_STATUS.email:extra_forbidden`, `body:json_invalid`), jamás el valor, el mensaje ni el contexto. Los responses públicos mantienen su taxonomía contractual.

## Persistencia

- Reutiliza el Thin Firestore Session Repository de [ADR-0009](../decisions/0009-use-thin-firestore-session-repository.md): un load, el modelo dentro del grafo LangGraph en RAM sin persistent checkpointer y un save antes del HTTP response.
- El grafo del turno es `START → run_model → advance_turn → END`; la consolidación durable excluye transcript y decisión del modelo.
- `/integration-events` no usa el grafo ni el modelo conversacional: un load y, sólo si el evento muta estado, un save. No incrementa `turn_count` ni `revision`. La única llamada de modelo posible es la redacción estrecha de feedback de espera.
- `external_operation` conserva la metadata técnica mínima de anti-silencio legacy (`last_progress_feedback_at`, `progress_feedback_index`).
- El contrato durable es la versión 4. Añade planos separados: `polling` (operación, `started_at`, `observation_limit`, receipts de `sequence` + fingerprint SHA-256, `last_feedback_attempt_at` y hasta dos mensajes validados), `password_presentation` (operación, acción, revisión, `voice`, `email_requested`, aceptación y entrega) y `voice_retry_count`, el contador escalar, consecutivo y PII-safe de voice failures. Los documentos v1, v2 y v3 migran en memoria fail-closed; un v2 con `delivery` no nulo se traduce sin reinterpretarlo y cualquier campo fuera del whitelist cerrado se rechaza.
- `voice_retry_count` empieza en 0, avanza con cada voice failure recibido y se reinicia a 0 sólo tras un `/turns` válido y persistido. No conserva reason ni texto, no reutiliza intentos de identidad, `turn_count`, `revision` ni la secuencia de polling, y no impone hoy un máximo: la política de agotamiento sigue pendiente de decisión del owner.
- El bootstrap usa exclusivamente un create condicional (precondición de inexistencia); nunca un `set()` sobre un identificador que parecía ausente. Un conflicto de create no es un 503: se recarga el documento real y el evento se aplica sobre él.
- Un `/turns` válido preserva `polling` y `password_presentation` del registro previo y sólo reinicia el contador de voz; no reconstruye parcialmente el documento.
- El contrato de transporte (legacy o v1) no es estado durable: no se persiste.
- **Precaución operativa.** Una revisión estable antigua no puede leer documentos v3. Durante la ventana E2E todos los bloques CU013 deben usar la tag URL, sin mezclar requests al hostname estable y al etiquetado en una misma llamada; no se promueve tráfico ni se declara rollback productivo compatible con sesiones v3 hasta diseñarlo explícitamente.

## Abierto

- Resultado positivo de validación de identidad y su integración con AD/TIVIT (ID-001).
- Correlación, idempotencia, polling, reintentos y resultados tardíos de XCALLY (XC-002 a XC-004); el contrato candidato de secuencia/dedupe/presupuesto sigue pendiente de evidencia real.
- Shape real de responses/errors y mapeo de estados externos (XC-005, XC-006).
- Deadline explícito de Firestore (FS-002).
- Mapeo final status RD → experiencia/handoff y validación E2E de anti-silencia, feedback contextual, presentación de contraseña y terminales.
- Valor final de la cadencia de feedback (10 s candidatos) y del presupuesto de observaciones (9 candidatas).

## Trazabilidad

- [Especificación del sistema](system.md)
- [Especificación de acciones de cuenta](account-actions.md)
- [Gaps de implementación](../gaps.md)
- [Experimento 0010 — Contrato de eventos técnicos](../experiments/0010-integration-events-contract.md)
- [Boundary XCALLY / Orchestrator / TIVIT](account-actions.md#boundary-xcally--orchestrator--tivit)
