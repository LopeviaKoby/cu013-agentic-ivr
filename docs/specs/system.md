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

## Persistencia de sesión

**ACCEPTED.** Cada request debe cargar desde Firestore un `SessionRecord` pequeño, semántico y con campos permitidos explícitamente; construir un `GraphState` efímero en RAM; ejecutar LangGraph sin checkpointer persistente; consolidar el siguiente `SessionRecord`; y persistirlo antes de emitir el HTTP response.

El `GraphState` no es un contrato durable. No se persisten tools, schemas de tools, SDK clients, objetos internos de LangGraph, checkpoints ni estado arbitrario del grafo.

LangGraph orquesta el turno técnico y el LLM conserva la responsabilidad conversacional. Una futura `pending_operation` durable puede exigir escrituras adicionales antes o después de un side effect empresarial; no se introducen escrituras por super-step o por internals de LangGraph.

Ante un crash a mitad del turno, el siguiente request reinicia desde la última sesión durable. Last-writer-wins por documento se acepta mientras XCALLY ejecute secuencialmente por `conversation_id`; evidencia de concurrencia real del mismo conversation obliga a reabrir optimistic locking o transacciones.

## Boundary HTTP

**PROVISIONAL — implemented DEV baseline.** CU013 materializa un boundary HTTP mínimo para DEV. El contrato implementado, sus restricciones y su evolución basada en evidencia viven en [Boundary HTTP XCALLY ↔ CU013](xcally-boundary.md); no constituye todavía el contrato integrado final con Cally Square ni define órdenes/resultados AD/TIVIT.

## Entorno GCP actual

**IMPLEMENTED AND VERIFIED BY OWNER.**

```yaml
gcp:
  project_id: cu013-xcally-agentic
  organization: ylopevia-org
  primary_region: us-east1
```

Recursos actuales:

- Firestore `(default)`, Native mode, Standard edition, `us-east1`.
- Artifact Registry `cu013-containers-dev`, formato Docker, `us-east1`.
- Cloud Run `cu013-runtime-dev` desplegado en `us-east1` como entorno DEV PROVISIONAL; estado de reposo `min instances = 0` y `min = 1` sólo durante ventanas de benchmark autorizadas.
- Vertex AI habilitado en `us-east1`; el motor real ejecuta el baseline temporal y la selección productiva sigue pendiente.
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

- `cu013-spike-firestore`: aísla el spike local y se usa mediante ADC impersonation. Tiene `roles/datastore.user`.
- `cu013-runtime-dev`: identidad de menor privilegio del servicio Cloud Run DEV (en uso). Tiene `roles/datastore.user` y `roles/aiplatform.user`, y sólo accede al secreto DEV por binding a nivel de secreto.
- `cu013-deployer-dev`: separa despliegue y runtime, y prepara GitHub Actions. Tiene `roles/run.developer`, acceso writer al repositorio DEV y derecho a usar la runtime SA.

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
- Cloud Run DEV opera con `min instances = 0` y `max instances = 1`; `min = 1` existe sólo durante una ventana de benchmark autorizada y se restaura a 0 al terminar, pase o falle.
- No se crearán recursos always-on innecesarios ni una segunda base Firestore por defecto.
- No se añadirán VPC, Cloud SQL, Redis, Kubernetes u observabilidad pesada sin evidencia.
- El presupuesto y alerta económica se gestionan externamente; no son un hard cap técnico.

## Región

`us-east1` es la región primaria actual. No demuestra ser la región óptima.

`southamerica-east1` permanece como alternativa futura a benchmarkear, especialmente por cercanía con AD/TIVIT en Brasil. No es failover ni región secundaria activa.

Vertex AI en `us-east1` es una dirección temporal sujeta a medición.

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

`gemini-2.5-flash-lite` con `ThinkingConfig(thinking_budget=0)` es el baseline temporal. No es la selección definitiva de producción.

**IMPLEMENTED (DEV baseline).** El primer motor real está integrado detrás del seam conversacional sobre Vertex AI con ADC, sin streaming ni tools, con output estructurado tipado y un solo attempt por turno. La medición del camino backend completo (HTTP → load → modelo → grafo → save → response) vive en el [Experimento 0003](../experiments/0003-gemini-baseline-latency.md) (host DEV) y el baseline in-region con una instancia warm en el [Experimento 0004](../experiments/0004-cloud-run-latency.md) (Cloud Run `us-east1`); ambos son baselines DEV, no un SLO.

Debe evaluarse al menos una alternativa antes del 16-10-2026 mediante benchmarks CU013, priorizando latencia, calidad conversacional, selección/argumentos de tools, continuidad contextual y razonamiento cuando sea necesario.

## Seguridad y observabilidad

Los logs deben ser estructurados y PII-safe. Nunca deben contener credenciales, contraseñas, tokens, transcripciones completas ni datos personales crudos.

La observabilidad mínima debe permitir correlacionar conversación, turno, ruta, latencia, cantidad de llamadas al modelo, tool y clase de error sin exponer datos sensibles. Los nombres concretos del schema siguen TBD.

## Entrega y validación

GitHub Actions es la plataforma CI/CD aceptada. `dev` es la rama normal de trabajo y `main` representa releases aceptados.

Los cambios conversacionales aceptados requieren validación de voz en DEV. Los tests locales no sustituyen ASR/TTS ni la llamada real.

Antes de integrar una iteración aceptada se actualiza [CONTEXT.md](../../CONTEXT.md). El agente no debe hacer commit o push sin autorización explícita.

Las convenciones de implementación subordinadas a esta SPEC y a los ADR Accepted están en [Python](../engineering/python.md), [fiabilidad](../engineering/reliability.md) y [testing](../engineering/testing.md).
