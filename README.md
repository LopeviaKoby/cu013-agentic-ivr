# CU013 Conversational Backend v0.2.0

Backend conversacional telefónico de Mesa de Ayuda integrado con XCALLY Motion y Cally Square.

CU013 v0.2.0 es una reconstrucción arquitectónica nueva. El runtime anterior permanece sólo en Git como evidencia; no define la arquitectura actual.

## Estado actual

El repositorio contiene autoridad documental, configuración no sensible y tooling operativo reproducible para la base GCP DEV/SPIKE. Los experimentos de persistencia concluyeron, la estrategia Thin Firestore Session Repository está aceptada y su núcleo productivo mínimo vive en `app/session`. El baseline DEV provisional del boundary HTTP para Cally Square vive en `app/api`, con el motor real Gemini 2.5 Flash-Lite en `app/conversation`. El servicio Cloud Run DEV `cu013-runtime-dev` está desplegado en `us-east1` con `min=0` en reposo; todavía no existe integración XCALLY/Cally Square real ni AD/TIVIT.

La infraestructura confirmada usa el proyecto `cu013-xcally-agentic` y la región primaria `us-east1`, con Firestore `(default)`, Artifact Registry y service accounts separadas para spike, runtime y despliegue.

## Autoridad

- [Specs](docs/specs/) → requisitos vigentes.
- [Decisions](docs/decisions/) → decisiones arquitectónicas.
- [Experiments](docs/experiments/) → evidencia experimental.
- [Runbooks](docs/runbooks/) → operación.
- [Estándares de ingeniería](docs/engineering/) → convenciones de implementación.
- [Manifiesto de IOP locales](docs/iop/README.md) → fuentes empresariales esperadas.
- [CONTEXT](CONTEXT.md) → estado actual.
- [CHANGELOG](CHANGELOG.md) → cambios por versión.
- [AGENTS](AGENTS.md) → reglas para agentes.

El primer slice incluye `RESET_PASSWORD` y `UNLOCK_ACCOUNT`. VPN queda para una capacidad posterior.

## Operación GCP

- [Runbook de bootstrap GCP DEV](docs/runbooks/gcp-dev-bootstrap.md)
- [Runbook Cloud Run DEV benchmark](docs/runbooks/cloud-run-dev-benchmark.md)
- [`bootstrap-dev.ps1`](ops/gcp/bootstrap-dev.ps1)
- [`verify-dev.ps1`](ops/gcp/verify-dev.ps1)
- [`deploy-dev-benchmark.ps1`](ops/gcp/deploy-dev-benchmark.ps1) · [`stop-dev-benchmark.ps1`](ops/gcp/stop-dev-benchmark.ps1) · [`verify-dev-benchmark.ps1`](ops/gcp/verify-dev-benchmark.ps1)
- [Configuración no sensible](config.yaml)

El bootstrap no crea Cloud Run, secretos, WIF o Terraform. La autenticación local del spike usa ADC impersonation y nunca claves JSON de service account. La ventana warm de Cloud Run existe sólo durante un benchmark autorizado y se apaga a `min=0` al terminar.

## Persistencia de sesión

[ADR-0009](docs/decisions/0009-use-thin-firestore-session-repository.md) acepta un `SessionRecord` semántico en Firestore y un `GraphState` efímero por request, sin persistent LangGraph checkpointer en el voice path. El núcleo mínimo productivo vive en `app/session`: un load, un grafo LangGraph en RAM y un save antes de devolver control. Los registros [Option A](docs/experiments/0001-firestore-langgraph-checkpointer.md) y [Option B](docs/experiments/0002-firestore-thin-session-repository.md) se conservan como evidencia histórica `Completed`.

## Boundary XCALLY

El baseline DEV provisional del contrato HTTP entre Cally Square y CU013 está en [Boundary HTTP XCALLY ↔ CU013](docs/specs/xcally-boundary.md): `POST /api/v1/conversations/{conversation_id}/turns`, autenticación `X-API-Key` desde entorno, variantes transcript ASR e `IDENTITY_DATA`, respuesta `message`/`route` y errores con taxonomía segura. No es todavía el contrato integrado final. El transcript es efímero y el DTMF crudo queda contenido en el boundary.

El motor real es Gemini 2.5 Flash-Lite sobre Vertex AI (`app/conversation`), integrado dentro del turno delgado de sesión con output estructurado tipado. El [Experimento 0003](docs/experiments/0003-gemini-baseline-latency.md) conserva el baseline DEV local del camino completo y el [Experimento 0004](docs/experiments/0004-cloud-run-latency.md) el baseline in-region en Cloud Run; los clientes están en [evals/](evals/).

Las instrucciones operativas para agentes están en [AGENTS.md](AGENTS.md). [pyproject.toml](pyproject.toml) declara dependencias y configuración ejecutable; [requirements.lock](requirements.lock) fija las versiones productivas exactas.
