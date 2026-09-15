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
- Los side effects deben distinguir `pending`, `confirmed` y `failed`.

La concurrencia productiva de Cloud Run permanece TBD. Un benchmark controlado debe comparar al menos:

```text
concurrency = 1
concurrency = 8
```

Estos valores no son una decisión productiva.

Baseline de costo:

- DEV normal: `min instances = 0`;
- benchmark autorizado de cold start o latencia: `min instances = 1` temporalmente;
- al finalizar: volver a `min instances = 0`.

## Contenedor futuro

No existe Dockerfile en la baseline actual. Cuando se autorice su creación deberá respetar:

- imagen base confiable compatible con Python 3.12;
- `.dockerignore`;
- proceso non-root;
- ningún secreto en imagen, layers o build args;
- dependencias en layers aprovechables por cache antes del source cuando sea razonable;
- imagen mínima, sin herramientas innecesarias;
- un único proceso de aplicación inicialmente;
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
