# Estándar de fiabilidad

Este documento define convenciones de implementación subordinadas a la [SPEC del sistema](../specs/system.md), la [SPEC de acciones de cuenta](../specs/account-actions.md) y los ADR con `Status: Accepted`. Los nombres concretos de schemas e interfaces permanecen sujetos a sus autoridades correspondientes.

## Latencia

El objetivo de producto es:

```text
end-of-speech → first useful audio < 2 s
```

Un objetivo aproximado de 800 ms permanece aspiracional hasta disponer de evidencia propia.

Medir por separado:

- speech endpointing;
- XCALLY → backend;
- lectura de sesión;
- modelo;
- tool u operación externa;
- escritura de sesión;
- total del backend;
- TTS y first useful audio.

El TTFT del modelo es una métrica diagnóstica; no equivale a first useful audio si XCALLY espera la respuesta HTTP completa. Instrumentar timestamps y correlación sin PII. Los nombres finales del schema pueden permanecer TBD.

## Timeouts y retries

- Toda I/O externa debe tener un deadline o timeout explícito.
- Reintentar sólo cuando coincidan un error transitorio, una operación idempotente o condicionalmente idempotente y presupuesto de latencia restante.
- Preferir retry y backoff soportados por la SDK antes de crear infraestructura propia.
- Aplicar exponential backoff con jitter cuando corresponda.
- No reintentar errores permanentes.
- `RESET_PASSWORD` y `UNLOCK_ACCOUNT` no tienen retry automático desde CU013 hasta que exista una política aceptada de idempotencia y correlación mediante `operation_id` o equivalente.
- El retry del modelo debe definir attempts y deadline, y respetar el presupuesto de voz; no debe heredar defaults incompatibles con ese presupuesto.
- Un turno normal apunta a una sola llamada semántica al modelo. Más de dos llamadas secuenciales exige STOP & REPORT.

## Invariantes de confirmación y operación externa

Estas invariantes complementan las transversales de la [SPEC del sistema](../specs/system.md); sus valores concretos viven allí o en la evidencia de integración:

- Un timeout, silencio o ASR insuficiente de la confirmación verbal no equivale a autorización: invalida ese intento y obliga a re-prompt verbal, sin tocar la identidad validada ni consumir intentos de identidad.
- Tras un despacho externo de resultado incierto, la verdad de la operación queda en un estado desconocido (`UNKNOWN`): no se declara éxito ni fracaso, no se repite el side effect automáticamente y un resultado tardío se reconcilia con la operación existente.
- No existe replay automático de side effects desconocidos; la reconciliación requiere confirmación del boundary externo.
- Una sola operación externa activa por conversación; el guard durable precede a todo side effect ([ADR-0010](../decisions/0010-durable-semantic-plan-separate-from-authorization.md)).
- El timing exacto de voz (endpointing, barge-in, timeouts de confirmación en el canal XCALLY/ASR/TTS) sigue dependiendo de evidencia XCALLY: no se inventan valores de polling, retry ni deadline externos; los gaps XC-002 a XC-006 gobiernan su obtención.

## Polling, presupuesto y feedback de espera

- El presupuesto de observaciones de polling (9 GET candidatos), la cadencia de feedback (10 s candidatos) y cualquier deadline son valores independientes entre sí; ninguno es un SLO y su valor final depende de evidencia E2E.
- Un replay de observación nunca consume presupuesto; un error de dispatch nunca consume presupuesto de GET; un status desconocido o un error de GET sí consumen una observación.
- El agotamiento del presupuesto no convierte `PENDING`/`UNKNOWN` en `FAILED`: la verdad de la operación permanece sin confirmar.
- El composer de feedback es la única llamada de modelo posible en `/integration-events`: recibe una proyección PII-safe cerrada, devuelve sólo `message` y nunca decide `next_step`, autoriza, despacha ni toca identidad.
- Un timeout, salida inválida o texto no admisible del composer produce silencio (`message=null`) con el estado empresarial intacto y sin segunda llamada ni re-POST.
- La memoria textual reciente y la ventana experimental no se activan para callers reales en esta iteración.

## Errores

Usar esta taxonomía mínima y estable:

- `validation`
- `authorization`
- `conflict_or_duplicate`
- `dependency_timeout`
- `dependency_unavailable`
- `internal`

Los errores de Google, Firestore, LangGraph o HTTP no deben escapar directamente al contrato XCALLY. Traducirlos en el boundary adecuado y conservar el detalle técnico sólo en logging seguro.

## Concurrencia y estado

- El código debe ser seguro ante concurrencia.
- No mantener estado mutable de negocio o sesión como global de proceso.
- Firestore es la autoridad durable.
- No ejecutar persistencia crítica después de devolver HTTP 2xx.
- Los side effects deben distinguir `pending`, `unknown`, `confirmed` y `failed` (terminología canónica de la [SPEC del sistema](../specs/system.md) y [ADR-0010](../decisions/0010-durable-semantic-plan-separate-from-authorization.md)).

La concurrencia productiva de Cloud Run permanece TBD. Un benchmark controlado debe comparar al menos:

```text
concurrency = 1
concurrency = 8
```

Estos valores no son una decisión productiva.

Baseline de costo:

- DEV normal: `min instances = 0`;
- ventana autorizada de benchmark (cold start o latencia) o de validación DEV de voz controlada: `min instances = 1` temporalmente;
- al finalizar la ventana: volver a `min instances = 0`.

## Contenedor

El `Dockerfile` vigente construye la imagen que Cloud Run DEV despliega. Debe respetar:

- imagen base confiable compatible con Python 3.12 (`python:3.12-slim`);
- `.dockerignore` que excluye docs, tests, evals, `ops/`, `.env` y artefactos locales;
- proceso non-root (usuario dedicado `cu013`);
- ningún secreto en imagen, layers o build args; runtime instala sólo dependencias con el lock (`pip install -c requirements.lock .`);
- un único proceso de aplicación (`uvicorn` con entrypoint factory);
- escucha en `0.0.0.0:$PORT`;
- filesystem efímero, nunca durable.

No imponer un multi-stage build sin necesidad demostrada.

## Referencias oficiales

- [Google Cloud retry strategy](https://docs.cloud.google.com/storage/docs/retry-strategy)
- [FastAPI error handling](https://fastapi.tiangolo.com/tutorial/handling-errors/)
- [Docker build best practices](https://docs.docker.com/build/building/best-practices/)
- [Cloud Run container contract](https://docs.cloud.google.com/run/docs/container-contract)
- [Cloud Run concurrency](https://docs.cloud.google.com/run/docs/about-concurrency)
- [Cloud Run minimum instances](https://docs.cloud.google.com/run/docs/configuring/min-instances)
