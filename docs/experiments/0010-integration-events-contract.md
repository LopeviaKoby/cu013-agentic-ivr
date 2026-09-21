# Experimento 0010: contrato backend de eventos técnicos para TEST_XCALLY_CU013_API_APPROACH

- Status: Running (contrato local implementado y probado; diseño Cally Square, deploy coordinado y caller tests E2E pendientes)
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

## Trazabilidad

- [Boundary HTTP XCALLY ↔ CU013](../specs/xcally-boundary.md)
- [Especificación de acciones de cuenta](../specs/account-actions.md)
- [Gaps de implementación](../gaps.md)
- [ADR-0010](../decisions/0010-durable-semantic-plan-separate-from-authorization.md)
