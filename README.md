# CU013 Conversational Backend v0.2.0

Backend conversacional telefónico de Mesa de Ayuda integrado con XCALLY Motion y Cally Square.

CU013 v0.2.0 es una reconstrucción arquitectónica nueva. El runtime anterior permanece sólo en Git como evidencia; no define la arquitectura actual.

## Estado actual

El repositorio contiene autoridad documental, configuración no sensible y tooling operativo reproducible para la base GCP DEV/SPIKE. Todavía no existe runtime, servicio Cloud Run ni implementación del spike Firestore/LangGraph.

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
- [`bootstrap-dev.ps1`](ops/gcp/bootstrap-dev.ps1)
- [`verify-dev.ps1`](ops/gcp/verify-dev.ps1)
- [Configuración no sensible](config.yaml)

El bootstrap no crea Cloud Run, secretos, WIF o Terraform. La autenticación local del spike usa ADC impersonation y nunca claves JSON de service account.

## Experimento siguiente

El plan y registro durable del experimento está en [checkpointer Firestore/LangGraph](docs/experiments/0001-firestore-langgraph-checkpointer.md). Está en estado `Planned`; su ejecución pertenece a un encargo separado y a un worktree efímero.

Las instrucciones operativas para agentes están en [AGENTS.md](AGENTS.md). Las dependencias Python se centralizan en [pyproject.toml](pyproject.toml).
