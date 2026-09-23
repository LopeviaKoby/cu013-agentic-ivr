# Experimento 0010: contrato backend de eventos técnicos para TEST_XCALLY_CU013_API_APPROACH

- Status: Running (contrato local y next-step-v1 implementados y probados; deploy etiquetado y caller tests E2E pendientes)
- Lifecycle: Planned → Running → Completed / Failed / Inconclusive
- Authority: evidencia experimental; no es una decisión arquitectónica
- Date: 2026-09-21

## Pregunta e hipótesis

¿Puede CU013 ofrecer contratos backend suficientes para que el flujo destino
`TEST_XCALLY_CU013_API_APPROACH` ejecute acciones de cuenta sin recibir DTMF
crudo, sin llamar a RD/AD y sin que el LLM toque el side effect, conservando
autorización, correlación, verdad externa y anti-silencio?

Hipótesis antes de implementar: el patrón command/event —el runtime crea una
orden opaca y XCALLY ejecuta y devuelve eventos PII-safe— permite corregir
las propiedades observadas del flujo TEST (rama `EXECUTE_ACTION` ausente,
DTMF crudo hacia el backend, ASR insuficiente no informado, cualquier 2xx
tratado como respuesta conversacional) sin copiar TIVIT_RD_LATAM y sin que
el backend necesite la credencial RD.

El flujo destino es `TEST_XCALLY_CU013_API_APPROACH`; `TIVIT_RD_LATAM` es
sólo la fuente de la que se adaptan bloques y semántica. La secuencia
autorizada es: backend implementado y probado → owner adapta TEST en Cally
Square → deploy coordinado → caller tests E2E → aceptación/revisión de
contratos con evidencia.

## Candidato medido (local)

```text
app/api/contracts.py        /turns sin IDENTITY_DATA; TurnResponse.route
                            BoundaryRoute + command; response técnica plana
app/api/app.py              POST /integration-events; errores seguros
app/session/turns.py        BoundaryRoute.EXECUTE_ACTION, ExternalActionCommand,
                            guard de despacho y mensaje canónico de procesamiento
app/session/integration.py  IntegrationEvent, IntegrationEventService, directivas,
                            máquina de operación y anti-silencio
app/session/record.py       metadata técnica de progreso en ExternalOperation
tests/api/                  contrato, autorización, eventos, PII
tests/session/              máquina de estados determinista
```

No se añadió cliente HTTP RD/TIVIT, tool LangGraph/model, base adicional,
framework ni orquestador. El guard durable precede a la orden; `/turns` es el
único productor de órdenes y `/integration-events` el único reconciliador de
verdad externa.

## Alcance ejecutado localmente

1. `/turns` acepta sólo transcript; la forma `IDENTITY_DATA` con DTMF crudo se
   eliminó del contrato activo y se rechaza como payload inválido.
2. `EXECUTE_ACTION` + `command` (`operation_id` opaco, `action` cerrado,
   `goal_revision`) sólo cuando el guard se persiste; el contrato del modelo
   no incluye la ruta nueva y su esquema no cambió.
3. `/integration-events` con union discriminada cerrada:
   `IDENTITY_VALIDATION_RESULT`, `VOICE_INPUT_FAILURE`,
   `ACCOUNT_ACTION_STATUS`, `ACCOUNT_ACTION_ERROR`.
4. Respuesta plana `{acknowledged, operation_state, directive, message}` con
   proyección de cable de `OperationStatus` y directivas propias del polling.
5. Máquina de operación: `pending → unknown` en error de dispatch, terminales
   `confirmed`/`failed`, ACK idempotente, conflicto seguro sin overwrite,
   reconciliación de late results y cero re-dispatch.
6. Anti-silencio determinista con intervalo experimental de 10 s, rotación de
   tres frases permitidas y cero llamadas al modelo por polling.
7. Correcciones de readiness: aliases experimentales (`b0`, `p`, `c1`, `s0`…)
   eliminados de código/harness/tests/docs activos y bloqueados por el gate de
   repository readiness; oráculo `confirmation-affirmative-authorizes`
   reconciliado con la autoridad: tras un despacho legal,
   `action_eligibility = not_eligible` (una operación activa por conversación).

## Evidencia local

- `python -m pytest`: 424 tests, 0 fallos (doce nuevos archivos/casos de
  contrato, autorización, estado, JSON y canarios PII).
- `python -m ruff check .` y `python -m ruff format --check .`: sin hallazgos.
- `python -m mypy app`: sin hallazgos.
- `python -B evals/conversation_eval.py --validate-only`: corpus 47 casos, 0
  problemas.
- Canarios sintéticos de documento, fecha, email, identidad, password y
  secreto ausentes del input del modelo, Firestore, logs, estado durable,
  respuesta HTTP y artefactos versionados.
- Cero llamadas al modelo en `/integration-events` (los dobles lo verifican).

## Límites explícitos

No se declara integrado: identidad real, RD real, polling real, ASR/TTS real,
latencia E2E ni handoff real. Los gaps XC-001 a XC-006 e ID-001 quedan
`Investigated (candidate contract)` o `Discovered` hasta la evidencia E2E.
SendMail sigue Deferred y el reset confirmado no se declara completado al
caller sin resultado de entrega. La concurrencia same-session mantiene la
política Accepted (secuencial por `conversation_id`); solapar `/turns` y
`/integration-events` obligaría a reabrirla antes de producción.

## Handoff para el diseño Cally Square

| Punto de TEST actual | Cambio posterior esperado |
|---|---|
| REST de voz `/turns` | conservar; consumir `EXECUTE_ACTION` + `command` |
| distribuidor de rutas | añadir rama explícita `EXECUTE_ACTION` antes del fallback |
| `COLLECT_IDENTITY` | mantener TTS de entrada; sustituir el retorno de DTMF crudo por captura/validación dentro de XCALLY y `IDENTITY_VALIDATION_RESULT` |
| fallo ASR local | añadir llamada `VOICE_INPUT_FAILURE` antes del retry cuando corresponda |
| POST RD | adaptar bloques reset/desbloqueio desde LATAM; no copiar IDs |
| GET/polling RD | adaptar consutcall y estados LATAM; cero LLM por poll |
| variable de route actual | mantenerla separada de `RD_STATUS` |
| terminal RD | llamar `/integration-events` antes de TTS/cierre |
| anti-silencio | reproducir TTS sólo cuando `message != null`; después seguir `directive` |
| fallback/handoff | conservar el destino TEST actual hasta validación E2E; no importar destinos LATAM |

No se modificó ningún XML XCALLY en esta iteración; el mapeo
`RESET_PASSWORD → reset` y `UNLOCK_ACCOUNT → desbloqueio` pertenece a ese
diseño.

## Checkpoint de aceptación del owner (2026-09-21)

- El contrato backend local queda **aceptado para pasar a E2E**; la
  implementación no se rediseña por esta corrección.
- `consutcall` queda confirmado como la grafía contractual del polling
  (`GET /resetunlock/consutcall/{CALLERID(Name)}`); no es un typo y no se
  normaliza.
- Lookup real de identidad por documento:
  `GET /validauser/TIVIT/{DOCUMENTO}` (`FOUND`/`NOT_FOUND` observados).
- `FOUND`/`NOT_FOUND` son estados del lookup por documento; los errores
  técnicos se mantienen separados y no se reinterpretan como `NOT_FOUND`.
- `FOUND` no equivale a identidad válida: puede existir antes de la fecha de
  ingreso y no autoriza nada por sí solo.
- `VALID`/`INVALID`/`TECHNICAL_FAILURE` y el contador de intentos son
  semántica local CU013/XCALLY; no se documentan como estados o counters de
  TIVIT/RD.
- Fecha de identidad aceptada: **fecha de ingreso `DDMMYYYY`** (ocho
  dígitos), comparada en XCALLY contra `resposta2` del registro recuperado.
- Secuencia aceptada: documento → `validauser` → `FOUND` → fecha de ingreso →
  comparación → outcome local → `VALID` → confirmación verbal → `EXECUTE_ACTION`.
- La consulta por documento está observada; la captura de la fecha, la
  comparación y el evento local siguen pendientes de demostración E2E
  (ID-001). El experimento permanece `Running` hasta los caller tests.

## Iteración next-step-v1 (2026-09-23)

Candidato medido localmente:

- selector explícito `CU013-Response-Contract: next-step-v1` con envelope común
  `{message, next_step, operation_state, command}` en ambos endpoints; sin
  header el contrato legacy permanece byte-compatible y un header vacío,
  repetido o desconocido responde 400 `unsupported_response_contract`;
- continuidad post-identidad sin segunda llamada al modelo: goal y revisión
  conservados, challenge anterior invalidado, challenge nuevo ligado a
  acción/revisión/identidad y confirmación específica por acción;
- secuencia de polling estricta, dedupe por fingerprint SHA-256 del tipo
  cerrado y presupuesto de 9 observaciones; el agotamiento responde `TRANSFER`
  sin convertir `PENDING`/`UNKNOWN` en `FAILED` y sin re-POST;
- `IDENTITY_INPUT_FAILURE/CAPTURE_EXHAUSTED` (sin intento, sin operación,
  `TRANSFER`) y `PASSWORD_PRESENTATION_RESULT` (hechos de presentación;
  `DELIVER_PASSWORD` sólo para reset confirmado sin presentación; duplicado
  ACK idempotente, incompatible 409);
- feedback de espera contextual en v1 mediante un composer estrecho con
  entrada PII-safe cerrada y salida sólo `message`; la rotación fija se retira
  del carril v1 y sobrevive sólo en legacy;
- contrato durable v3 con planos separados `polling` y
  `password_presentation` y migración v1/v2 fail-closed;
- wording aceptado fecha de ingreso con guard determinista que impide
  reintroducir el wording descartado.

Evidencia local: `pytest` 548 pasando (dos fallos de entorno preexistentes por
`google-cloud-firestore` 2.28.1 instalado frente al pin 2.30.0 del lock),
Ruff, `ruff format --check`, MyPy y `--validate-only` (47 casos) en verde;
canarios PII ausentes del input del modelo, estado durable, respuesta HTTP y
logs.

Límite explícito: la evaluación económica sustituye al full paired de esta
iteración porque no cambia la semántica de decisión del modelo conversacional
(el prompt sólo cambia wording y el decision schema queda intacto); el smoke
real acotado se ejecuta contra la revisión etiquetada antes de los caller
tests. La semántica externa de secuencia, presentación y feedback sigue
pendiente de evidencia E2E.

Despliegue E2E: nueva revisión Cloud Run con 0% de tráfico, `min instances = 1`
a nivel de revisión, tag `e2e-4b72dfa` reasignado a la nueva revisión y la
misma tag URL consumida por XCALLY; la revisión estable conserva el 100% del
tráfico y el mínimo de servicio no cambia.

## Evidencia E2E de llamadas reales (2026-09-23)

Llamadas ejecutadas por el owner contra la tag `e2e-4b72dfa` (revisión
`cu013-runtime-dev-00028-6rb`, digest `sha256:8cf04d98…`, commit `3d4b503`).
Hechos observados en Cloud Run (request logs + stdout), sin transcript ni
payloads:

| Hora UTC | Endpoint | Resultado | Lectura |
|---|---|---|---|
| 14:01:52 | `/integration-events` | 409 | evento técnico sin turno previo: `unknown_session` |
| 14:52:32 | `/turns` | 422 | body fuera del contrato cerrado |
| 15:32:31 | `/turns` | 422 | body fuera del contrato cerrado |
| 15:50:15 | `/turns` | 200 legacy, 1,2105 s | sesión creada; envelope legacy servido |

Evidencia durable aportada por el owner para `Ivr01-1790178599.346002`
(documento v3 en ese momento): `turn_count=1`, `revision=1`, goal
`UNLOCK_ACCOUNT` revisión 1, identidad no validada y cero fallos, sin
challenge, dispatch ni operación. El model decision creó correctamente el
goal; el runtime devolvió `LISTEN/CONTINUE` en vez de exigir
`COLLECT_IDENTITY`.

Diagnóstico cerrado: **`HEADER_MISMATCH`**. La request llegó a la revisión
correcta y esa revisión sólo reconoce `X-CU013-Response-Contract`; el flujo
real no seleccionó el contrato v1 (nombre sin `X-` o ausencia de selector), la
respuesta fue el envelope legacy, el Switch de XCALLY no encontró `next_step`
y su rama por defecto derivó en transferencia. Ese hecho **no** es atención
humana ni un handoff del runtime.

Gaps de observabilidad detectados en la misma ventana: las líneas INFO de
aplicación (`turn handled`, motivo del rechazo) no llegaban a Cloud Logging
porque el root logger no tenía handler y sólo `cu013.metrics` configuraba el
suyo; la request log sí permitía correlacionar por URL y trace.

Política aceptada de voice retry (owner, 2026-09-23): hasta tres reintentos
tras el intento inicial; el cuarto fallo consecutivo de captura responde
`TRANSFER`, el contador durable se acota al máximo y un `/turns` válido
persistido lo reinicia a 0. Sin llamada al modelo, sin goal, sin identidad,
sin challenge, sin operación, sin consumir intentos de identidad y sin retry
HTTP automático del evento.

Correcciones implementadas en esta iteración: header canónico
`X-CU013-Response-Contract` sin alias, `next_step` derivado del estado
consolidado (goal pendiente sin autorización exige `COLLECT_IDENTITY`),
bootstrap pre-turno v1 con create condicional y contador de voice retry,
rejection reasons tipados, proyección segura de 422 y topología de logging
`cu013` con eventos cerrados. La semántica externa de polling, presentación de
contraseña, RD/TIVIT y SendMail sigue pendiente de evidencia.

## Trazabilidad

- [Boundary HTTP XCALLY ↔ CU013](../specs/xcally-boundary.md)
- [Especificación de acciones de cuenta](../specs/account-actions.md)
- [Gaps de implementación](../gaps.md)
- [ADR-0010](../decisions/0010-durable-semantic-plan-separate-from-authorization.md)
