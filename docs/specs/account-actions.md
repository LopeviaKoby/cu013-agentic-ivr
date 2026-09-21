# CU013 v0.2.0 — Account Actions Specification

## Alcance del slice

**ACCEPTED.** El primer vertical slice incluye conjuntamente:

- `RESET_PASSWORD`
- `UNLOCK_ACCOUNT`

No existe prioridad obligatoria entre ambas. VPN queda como capacidad posterior.

## Autoridad empresarial y técnica

Esta SPEC distingue tres niveles y no los sustituye entre sí:

1. Los IOP corporativos disponibles en `docs/iop/` son el procedimiento empresarial autoritativo.
2. XCALLY/Cally Square y Orchestrator/TIVIT constituyen el mecanismo autorizado para ejecutar acciones empresariales en esta fase.
3. Esta SPEC define el comportamiento del agente CU013 que combina los IOP con ese mecanismo; no reescribe los procedimientos corporativos.

IOP vigentes consultados para este slice:

- [Manifiesto versionado de IOP](../iop/README.md)
- [IOP-MDA-012 — Desbloqueo de cuentas](<../iop/IOP-MDA-012- DESBLOQUEO DE CUENTAS.pdf>)
- [IOP-MDA-013 — Cambio de contraseña](<../iop/IOP-MDA-013- CAMBIO DE CONTRASEÑA.pdf>)

Una obligación de los IOP sólo deja de aplicar cuando una decisión autorizada la sustituye explícitamente. Si una obligación sigue vigente pero su integración automatizada no está definida, debe conservarse como `UNKNOWN` pendiente de integración.

## Identidad y autorización

El mecanismo inicial aceptado es DTMF:

1. capturar documento de identidad;
2. consultar el lookup externo por documento `GET /validauser/TIVIT/{DOCUMENTO}`;
3. si la consulta devuelve un registro (`FOUND`), capturar la fecha de ingreso `DDMMYYYY` (ocho dígitos) y compararla en XCALLY contra `resposta2` del registro recuperado;
4. obtener un resultado positivo de validación;
5. sólo entonces autorizar la solicitud de reset o desbloqueo.

**ACCEPTED (evidence).** El lookup real observado es `GET https://urawps.tivit.com/prod-v2/api/v1/resetunlock/validauser/TIVIT/{DOCUMENTO}`. El documento se captura por DTMF en XCALLY y nunca llega al backend CU013.

El dominio externo conocido de esa consulta es `FOUND | NOT_FOUND`, separado de los errores técnicos (timeout, HTTP error, respuesta inesperada). `FOUND` sólo significa que el lookup encontró un registro para ese documento: no valida la fecha, no concede autorización y no equivale a identidad válida; puede existir antes de capturar la fecha de ingreso. `NOT_FOUND` sólo significa que la consulta no encontró coincidencia, y los errores técnicos no se reinterpretan como `NOT_FOUND`.

La semántica local de CU013/XCALLY es un dominio distinto que no se atribuye a TIVIT: `VALID | INVALID | TECHNICAL_FAILURE` y el contador de intentos. XCALLY produce el outcome local:

- lookup `NOT_FOUND`, o fecha de ingreso que no coincide con `resposta2` → `INVALID`;
- lookup `FOUND` y fecha de ingreso correcta → `VALID`;
- timeout, HTTP error o respuesta inesperada → `TECHNICAL_FAILURE`.

El contador de intentos pertenece al runtime CU013: `INVALID` consume un intento imputable al caller, `TECHNICAL_FAILURE` no consume intento y `VALID` tampoco. RD/TIVIT no conoce ni devuelve ese contador.

**PROVISIONAL (evidence).** La consulta por documento está acreditada; falta demostrar E2E el recorrido completo `FOUND → captura DDMMYYYY → comparación con resposta2 → evento VALID/INVALID → backend` (ID-001).

**PROVISIONAL (boundary).** En el contrato backend↔TEST la captura ocurre dentro de XCALLY: CU013 no recibe documento, fecha ni DTMF crudo, sino un resultado PII-safe `IDENTITY_VALIDATION_RESULT` por `/integration-events`. El contrato técnico y la secuencia esperada de TEST viven en [Boundary HTTP XCALLY ↔ CU013](xcally-boundary.md#evento-de-identidad-pii-safe).

La identidad validada concede derecho a solicitar una acción; no equivale al éxito de AD/TIVIT ni a la autorización de despacho, que exige además la confirmación HITL verbal de [system.md](system.md#confirmación-hitl-verbal).

**ACCEPTED.** La identidad es válida sólo durante la llamada actual y por un TTL absoluto de 30 minutos. Un re-prompt de confirmación verbal no invalida la identidad y no consume intentos de validación; un timeout o ASR insuficiente de confirmación tampoco.

Los valores crudos de documento y fecha de ingreso:

- no deben entrar al LLM;
- no deben aparecer en logs o telemetría;
- no deben persistirse más allá de lo estrictamente necesario para validar;
- deben minimizarse en cualquier estado durable.

## Intentos de validación de identidad

**ACCEPTED.** Se permiten hasta tres fallos de identidad imputables al caller por llamada (documento o fecha incorrectos). Al tercer fallo el agente ejecuta handoff.

**ACCEPTED.** Los fallos técnicos de validación (indisponibilidad o timeout del boundary externo) no consumen intentos del caller. No confunden la validación con la confirmación HITL: son fases distintas.

## Atención automatizada y handoff

**ACCEPTED.** CU013/XCALLY cuenta como atención automatizada de Mesa para `RESET_PASSWORD` y `UNLOCK_ACCOUNT`. No existe escalamiento preventivo por sensibilidad de la operación: ninguna de las dos acciones escala sólo por serlo.

**ACCEPTED.** El handoff procede únicamente cuando:

1. el caller lo solicita de forma explícita e inequívoca;
2. el IOP o protocolo vigente lo exige;
3. existe un fallo terminal que impide resolver la operación automáticamente;
4. otra condición aceptada en esta SPEC lo exige.

No se inventan causas adicionales de handoff.

**ACCEPTED (owner decision).** Pedir una operación fuera del slice soportado (`RESET_PASSWORD`, `UNLOCK_ACCOUNT`) no implica handoff automático: ESCALATE no es fallback de clasificación ni de alcance. Si la capacidad es conocida de Mesa de Ayuda pero todavía no está soportada (por ejemplo VPN o VDI), el agente responde brevemente que aún no puede ayudar con esa capacidad; si la petición queda fuera del ámbito de Mesa de Ayuda, redirige amablemente a ese ámbito. En ninguno de los dos casos se ejecuta nada, no se inventa un flujo y no se escala sólo por ello. El handoff sólo procede si concurre una causa aceptada, por ejemplo una solicitud explícita de persona del caller.

## Confirmación verbal por operación

**ACCEPTED.** Después de identidad válida y antes de cualquier despacho, cada operación exige su propia confirmación verbal afirmativa e inequívoca del caller sobre la acción concreta presentada, según la invariante HITL de [system.md](system.md#confirmación-hitl-verbal):

- negación explícita, silencio, timeout y ASR no concluyente nunca autorizan;
- un timeout de confirmación provoca un re-prompt verbal;
- una cancelación explícita antes del despacho cancela la acción;
- después del despacho no se promete reversión;
- no existe máximo aceptado de reintentos de confirmación; los tres intentos de identidad son una fase distinta y no se mezclan.

## RESET_PASSWORD

El agente debe poder ofrecer dos vías:

### Autoservicio guiado

El agente debe guiar al caller según el IOP vigente de cambio de contraseña, sin convertir el procedimiento en una nueva versión de la SPEC:

- portal de información de seguridad de Microsoft, incluyendo los requisitos de composición de contraseña indicados por el IOP;
- portal de accesos TIVIT, informando la condición vigente de conexión a la red corporativa TIVIT o VPN;
- escalamiento a Service Desk cuando el usuario no pueda realizar el cambio por ninguna de las dos vías, tenga permisos VDI o requiera desbloqueo de cuenta.

Aclaración vigente: la referencia del IOP a "requiera desbloqueo de cuenta" no convierte por sí sola ese caso en handoff humano obligatorio. CU013/XCALLY satisface la atención de Mesa como atención automatizada para `UNLOCK_ACCOUNT`; cuando la operación soportada puede resolverse autónomamente, el flujo continúa con el desbloqueo automático de esta SPEC (identidad + confirmación HITL), y el handoff humano sólo aplica según las causas aceptadas en esta SPEC.

### Acción directa

La acción directa sólo puede solicitarse después de completar la validación positiva de identidad por DTMF y de la confirmación HITL verbal de esa acción concreta. Se ejecuta mediante:

```text
CU013 ↔ XCALLY/Cally Square ↔ Orchestrator/TIVIT/AD
```

El agente no debe afirmar que la contraseña fue restablecida ni que su entrega fue exitosa hasta recibir un resultado verificable del boundary autorizado.

**ACCEPTED.** `reset confirmed` (resultado de AD/TIVIT) y `delivery confirmed` (estado de SendMail) son hechos separados; ninguno implica al otro y cada uno se comunica sólo con el estado recibido. El reset real para callers queda gated por SendMail validado: mientras SendMail esté Deferred, el reset directo no se declara completado para el caller sin su resultado de entrega.

## UNLOCK_ACCOUNT

No existe una vía de autoservicio guiado aceptada para desbloquear una cuenta.

Después de capturar por DTMF el documento, completar el lookup `FOUND` + fecha de ingreso `DDMMYYYY`, obtener una validación positiva y obtener la confirmación verbal de esa acción concreta, el agente puede solicitar directamente el desbloqueo mediante XCALLY/Orchestrator. La respuesta al caller debe describir la acción y su resultado sin exponer nombres de servicios o componentes técnicos.

La solicitud usa el comando externo observado `desbloqueio` mediante los bloques REST de Cally Square hacia Orchestrator/TIVIT/AD. La respuesta al caller deriva exclusivamente del resultado externo observado; ni una intención del caller ni una inferencia del LLM prueban el éxito.

## Ticketing y Mesa de Servicio

CU013 no crea, consulta ni modifica tickets ITSM. El registro de incidentes en herramientas de gestión está fuera del boundary técnico de este backend y no se implementa aquí.

### Excepción owner al registro de IOP-MDA-012

**ACCEPTED (owner decision).** IOP-MDA-012 exige registrar un incidente por cada desbloqueo. Para CU013, la persistencia en Firestore más logging seguro y PII-safe sustituyen ese registro de incidente. Esta excepción está autorizada explícitamente por el owner y no convierte Firestore en un sistema ITSM: CU013 no crea, consulta, actualiza ni cierra tickets, y el registro durable conserva sólo datos semánticos de operación, nunca datos personales crudos ni DTMF.

Para CU013, el desbloqueo automatizado autorizado se ejecuta por la ruta XCALLY/Cally Square → Orchestrator/TIVIT/AD. Si la operación no puede resolverse, se usa la ruta de escalamiento o handoff disponible en XCALLY según la evidencia de los XML CU013/RD y `DOC_API_RD.pdf`.

No debe inventarse una integración con Jira, ServiceNow u otra herramienta de tickets.

## Boundary XCALLY / Orchestrator / TIVIT

**ACCEPTED.** La ruta experimental inicial es:

```text
CU013
  ↕ órdenes y resultados
XCALLY / Cally Square
  ↕ bloques REST
Orchestrator / TIVIT / AD
```

CU013 no llama directamente a TIVIT en esta fase. No se implementará ahora la alternativa `CU013 → adapter desacoplado → Orchestrator/TIVIT/AD`.

En el contrato técnico vigente la orden viaja como `command` en la respuesta `/turns` (`route=EXECUTE_ACTION`, `operation_id` opaco de CU013, `action` y `goal_revision`), y el resultado vuelve como evento PII-safe (`ACCOUNT_ACTION_STATUS` / `ACCOUNT_ACTION_ERROR`) por `/integration-events`; el mapeo `RESET_PASSWORD → reset` y `UNLOCK_ACCOUNT → desbloqueio` pertenece a XCALLY, nunca al LLM ni al backend. Los shapes reales de RD/AD siguen siendo evidencia E2E ([Boundary HTTP XCALLY ↔ CU013](xcally-boundary.md)).

Esta ruta debe reevaluarse si la validación integrada demuestra problemas materiales de latencia, fiabilidad, retries, correlación, códigos de estado o complejidad del flujo Cally Square.

## Evidencia de integración conocida

Los IOP enlazados anteriormente son la autoridad del procedimiento empresarial. La evidencia disponible del mecanismo de integración queda limitada a los PDF en `docs/iop/`, `DOC_API_RD.pdf`, los XML CU013/RD, el lookup real por documento confirmado por el propietario y los parámetros o comportamientos confirmados por el propietario. Esta evidencia está agotada para planificación; los puntos experimentales restantes viven en [Gaps de implementación](../gaps.md) y no implican que exista documentación adicional por descubrir.

Rutas relativas observadas:

```text
GET /validauser/{CLIENTE}/{DOCUMENTO}     (lookup real observado con CLIENTE=TIVIT)
POST /call/{CALLERID(Name)}
GET /consutcall/{CALLERID(Name)}
```

Header observado: `api-key`.

Estados externos observados del lookup por documento: `FOUND` y `NOT_FOUND`, separados de los errores técnicos. `FOUND` sólo acredita que existe un registro para el documento; no equivale a identidad válida (ver [Identidad y autorización](#identidad-y-autorización)).

Comandos observados:

- `reset`
- `desbloqueio`

Campos observados del body:

- `empresa`
- `usuario`
- `pergunta_id1`
- `resposta1`
- `pergunta_id2`
- `resposta2`

Statuses literales observados:

- `SUCESSO`
- `NONE`
- `CPF_NAO_ENCONTRADO`
- `ERRO_NA_VALIDACAO`
- `FALHA_AD`
- `USUARIO_DESABILITADO`
- `USUARIO_EXPIRADO`

Estos nombres no deben normalizarse o renombrarse sin evidencia del servicio.

En el flujo de referencia, `GET /consutcall/{CALLERID(Name)}` implementa polling y `NONE` representa un estado pendiente. Correlación, idempotencia, retries, resultados tardíos y shapes completos continúan siendo experimentales, no ausencias documentales.

## Órdenes, resultados y operación pendiente

El runtime debe distinguir como mínimo:

- autorización de la identidad;
- acción solicitada;
- operación externa pendiente;
- resultado confirmado por XCALLY;
- estado del envío cuando corresponda.

No se fijan todavía nombres de nodos, GraphState keys, modelos Pydantic, endpoints ni payloads target para las órdenes y resultados de AD/TIVIT. El baseline DEV provisional del boundary conversacional y del boundary técnico XCALLY ↔ CU013 está materializado y tipado en [Boundary HTTP XCALLY ↔ CU013](xcally-boundary.md), que reutiliza los estados canónicos de operación de esta SPEC sin duplicarlos.

Una afirmación del caller o del LLM no puede convertirse en resultado empresarial. El agente sólo comunica estados efectivamente devueltos por el boundary externo.

**ACCEPTED.** Un resultado tardío (`late result`) se reconcilia con la operación existente y no crea una operación nueva ni un contacto nuevo; el resultado de una operación ya cancelada o cerrada no reabre nada.

La estrategia de idempotencia, correlación, polling, retries y resultados tardíos permanece experimental y se gestiona en [docs/gaps.md](../gaps.md). No se autorizan retries automáticos de acciones de cuenta hasta aceptar una política respaldada por evidencia.

## Contraseña temporal y SendMail

- Status: Deferred
- Sequence: XCALLY voice baseline → AD/TIVIT integration → log-driven debugging/caller tests → SendMail

La entrega aceptada es:

```text
TIVIT/AD devuelve resultado
→ XCALLY/Cally Square obtiene la contraseña cuando corresponda
→ SendMail de Cally Square envía la contraseña
→ CU013 recibe sólo el resultado/estado del envío
→ el agente informa éxito o fallo al caller
```

CU013 no implementará un servicio de correo propio.

La contraseña temporal nunca debe:

- persistirse en Firestore;
- enviarse al LLM;
- registrarse en logs o telemetría;
- conservarse en fixtures.

El resultado exacto de SendMail permanece Deferred y fuera del alcance inmediato. No bloquea el baseline de voz XCALLY aislado ni la integración AD/TIVIT posterior.

## Persistencia y concurrencia

Firestore es el único store durable aceptado. La estrategia vigente es Thin Firestore Session Repository:

```text
request
→ cargar SessionRecord
→ construir GraphState efímero
→ ejecutar LangGraph sin persistent checkpointer
→ consolidar SessionRecord
→ persistir antes del HTTP response
```

El `SessionRecord` sólo conserva campos semánticos permitidos explícitamente; no conserva DTMF crudo, tools, schemas de tools, SDK clients, internals de LangGraph ni `GraphState` arbitrario.

Una futura `pending_operation` durable puede exigir una escritura adicional antes de autorizar un side effect y otra al confirmar su resultado. Este requisito mantiene abierta la definición del contrato AD/TIVIT; no la inventa ni convierte una escritura por turno en dogma.

Un crash mid-turn reinicia desde la última sesión durable. Last-writer-wins por documento se acepta mientras XCALLY procese secuencialmente un `conversation_id`; si aparece concurrencia real del mismo conversation se deben reevaluar optimistic locking o transacciones antes de producción.

## Seguridad

El runtime debe aplicar minimización, separación de responsabilidades y autorización antes de acciones externas. No deben usarse datos personales o secretos reales en tests, fixtures o spikes.

No se permite acceso directo a AD/TIVIT, correo real ni modificación del flujo XCALLY real fuera de una integración autorizada.

## Criterios de aceptación

Los futuros goldens deben cubrir, sin fijar todavía un schema de runtime:

1. reset solicitado antes de validar identidad: la acción directa no está autorizada, pero el autoservicio guiado conforme al IOP sigue disponible;
2. desbloqueo solicitado antes de validar identidad: la acción directa no está autorizada y no se ofrece una vía de autoservicio guiado;
3. documento capturado por DTMF y nunca enviado al LLM/logs;
4. fecha de ingreso `DDMMYYYY` capturada por DTMF y nunca enviada al LLM/logs;
5. identidad positiva seguida de `RESET_PASSWORD`;
6. identidad positiva seguida de `UNLOCK_ACCOUNT`;
7. identidad validada y operación externa fallida: no declarar éxito;
8. operación pendiente y reintento/duplicado: no repetir side effect sin política aceptada;
9. SendMail exitoso o fallido: comunicar sólo el estado recibido;
10. contraseña temporal ausente de estado durable, prompts, logs y fixtures;
11. continuidad de la conversación con el mismo identificador de sesión;
12. corrección o aclaración conversacional sin convertir el procedimiento en spoken form.

## Gaps activos

Los gaps experimentales activos se mantienen exclusivamente en [docs/gaps.md](../gaps.md). Antes de implementar una parte productiva, sólo bloquea el gap que sea necesario para esa parte concreta.

SendMail está Deferred y no bloquea el baseline de voz XCALLY aislado ni la integración AD/TIVIT posterior. Un gap necesario para ejecutar side effects reales debe provocar STOP & REPORT hasta resolverse con evidencia.
