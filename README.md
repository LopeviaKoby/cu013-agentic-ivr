# CU013 Conversational Backend v0.2.0

Backend conversacional telefónico de Mesa de Ayuda integrado con XCALLY Motion y Cally Square. El LLM conduce la conversación; el runtime controla legalidad, verdad, autorización, estado y efectos externos.

CU013 v0.2.0 es una reconstrucción arquitectónica nueva: monolito modular en Python. El runtime anterior permanece sólo en Git como evidencia. El primer corte de acciones de cuenta es `RESET_PASSWORD` + `UNLOCK_ACCOUNT`, con validación inicial de identidad por DTMF.

## Estado actual

Están implementados el núcleo productivo mínimo del Thin Session Repository (`app/session`), el baseline DEV provisional del boundary HTTP para Cally Square (`app/api`) y el primer motor real Gemini 2.5 Flash-Lite (`app/conversation`, con prompt versionado en `app/conversation/prompts.py`). El servicio Cloud Run DEV `cu013-runtime-dev` está desplegado en `us-east1` con `min=0` en reposo. Todavía no existe integración real XCALLY/Cally Square, AD/TIVIT ni SendMail.

## Arquitectura

```text
llamante
   │  voz
   ▼
XCALLY Motion / Cally Square                ASR · TTS · DTMF
   │  POST /api/v1/conversations/{conversation_id}/turns · X-API-Key
   ▼
Cloud Run · cu013-runtime-dev · us-east1 · min=0

  app/api            boundary FastAPI: contrato Pydantic 2, auth
   │                 X-API-Key, errores seguros, contención de DTMF
   ▼  ConversationEngine (seam)
  app/session        TurnService · grafo LangGraph en RAM sin
   │                 persistent checkpointer · 1 load + 1 save
   ├────────────────▶ Firestore (default) · SessionRecord durable
   ▼
  app/conversation   GeminiTurnModel + prompt versionado
   │
   └────────────────▶ Vertex AI · gemini-2.5-flash-lite · ADC

app/
├── main.py          composition root DEV: clientes Vertex/Firestore
│                    reutilizados y cerrados en el lifespan
├── api/             boundary HTTP: contratos, auth, errores, DTMF
├── session/         Thin Session Repository: record, grafo, load/save
└── conversation/    seam ConversationEngine, motor Gemini, prompt
```

Un turno normal:

```text
POST /turns
→ validación del contrato y de X-API-Key (sólo desde entorno)
→ load SessionRecord (Firestore) y GraphState efímero en RAM
→ run_model: 1 llamada a Gemini con output estructurado tipado
→ advance_turn: el runtime decide legalidad y estado; no reescribe route
→ consolidate + save antes del HTTP response
→ {message, route, turn_id}
```

El transcript es efímero y no se persiste. Un crash a mitad de turno reinicia desde la última sesión durable. El DTMF crudo queda contenido en el boundary: nunca se persiste, registra, devuelve ni alcanza al LLM, y su llegada no valida identidad.

## Capacidades del sistema

| Capacidad | Estado |
|---|---|
| Conversación telefónica natural en español | Implemented (Gemini 2.5 Flash-Lite, prompt versionado) |
| Rutas cerradas `CONTINUE`, `COLLECT_IDENTITY`, `COMPLETE`, `ESCALATE` | Implemented |
| `RESET_PASSWORD`: autoservicio guiado y acción directa tras validar identidad | Conversación habilitada; ejecución externa pendiente de AD/TIVIT |
| `UNLOCK_ACCOUNT`: sólo acción directa tras validar identidad | Conversación habilitada; ejecución externa pendiente de AD/TIVIT |
| Identidad por DTMF (documento + fecha de nacimiento) | Boundary contenido; validación positiva pendiente (`ID-001`); `IDENTITY_DATA` termina en 503 seguro |
| Continuidad durable por `conversation_id` | Implemented (Thin Firestore Session Repository) |
| Autenticación `X-API-Key` y taxonomía segura de errores | Implemented (boundary `PROVISIONAL`) |
| Métricas y logs estructurados PII-safe | Implemented (segmentos fijos y contadores de tokens) |

Fuera de alcance: ticketing ITSM, SendMail (Deferred), VPN (posterior) y acceso directo a AD/TIVIT fuera de la ruta XCALLY → Orchestrator/TIVIT/AD.

## Harness de evaluación

`evals/` concentra los clientes manuales de medición. No participan de CI y nunca registran transcript, DTMF ni texto generado: sólo segmentos con nombres fijos (`handler`, `session_load`, `model`, `graph`, `session_save`, `total`) y contadores de tokens.

| Script | Qué mide | Requisitos |
|---|---|---|
| `evals/backend_latency.py` | Camino backend completo in-process (ASGI) contra Firestore y Vertex reales desde el host DEV | ADC con impersonación |
| `evals/cloud_run_latency.py` | El mismo camino contra el servicio desplegado, por HTTPS real (`--url`) | `CU013_API_KEY` en el entorno y ventana warm |
| `evals/conversation_policy_eval.py` | Política conversacional de petición previa contra el modelo real | ADC con impersonación |
| `evals/conversation_baseline_eval.py` | Runtime semántico completo (modelo real + guards de legalidad) contra el corpus versionado de `evals/conversation/` | ADC con impersonación |

El corpus de evaluación conversacional (`evals/conversation/cases.yaml`, 34 casos, 30 familias, sintético y sin PII) expresa expectativas semánticas por familia — rutas, goals, confirmación, elegibilidad, claims — sin phrase matching. El runner compara rutas, estado y claims, nunca wording; los eventos de boundary son eventos de dominio simulados porque el contrato wire XCALLY/AD sigue abierto (ID-001, XC-001..XC-006). La metodología eval-driven está en [testing standards](docs/engineering/testing.md).

Metodología del benchmark: 5 warmups y luego 30 requests secuenciales medidas (13 `RESET`, 13 `UNLOCK`, secuencia multi-turn de 4), percentiles por segmento y verificación de continuidad durable del `SessionRecord`. Resultados en el [Experimento 0003](docs/experiments/0003-gemini-baseline-latency.md) (local) y el [Experimento 0004](docs/experiments/0004-cloud-run-latency.md) (in-region).

```powershell
.\.venv\Scripts\python.exe evals\backend_latency.py
.\.venv\Scripts\python.exe evals\conversation_policy_eval.py
.\.venv\Scripts\python.exe evals\conversation_baseline_eval.py
python evals\cloud_run_latency.py --url <service-url>   # ventana warm
```

Los gates deterministas (193 tests con `pytest`, sin Gemini, Firestore ni credenciales) son la suite local, no el harness.

## Tecnologías e infraestructura

| Capa | Tecnología | Uso |
|---|---|---|
| Runtime | Python 3.12 | Lenguaje único del backend |
| HTTP | FastAPI + Uvicorn | Boundary y servidor ASGI de un solo proceso |
| Contratos | Pydantic 2 | Request/response, salida del LLM y `SessionRecord` |
| Orquestación | LangGraph | Grafo del turno sin persistent checkpointer |
| LLM | Vertex AI + `google-genai` | Gemini 2.5 Flash-Lite, `thinking_budget=0`, 1 llamada por turno |
| Persistencia | Firestore `(default)` | Único store durable (`cu013dev_sessions`) |
| Cómputo | Cloud Run | `cu013-runtime-dev`: 1 vCPU/512 MiB, concurrency 1, min 0/max 1 |
| Contenedor | Docker (`python:3.12-slim`) | Non-root, uvicorn con entrypoint factory |
| Secretos | Secret Manager | `cu013-api-key-dev` referenciado por versión numérica |
| Identidad | ADC impersonation | Sin claves JSON de service account |
| Calidad | pytest · Ruff · MyPy strict | Gates locales; CI/CD objetivo GitHub Actions |
| Reproducibilidad | `requirements.lock` | Constraints exactos para runtime y DEV |

Infraestructura GCP confirmada:

- proyecto `cu013-xcally-agentic`, región primaria `us-east1`;
- Firestore Native/Standard y Artifact Registry `cu013-containers-dev`;
- service accounts de mínimo privilegio `cu013-spike-firestore` (spike), `cu013-runtime-dev` (runtime) y `cu013-deployer-dev` (despliegue);
- APIs `aiplatform`, `artifactregistry`, `firestore`, `iam`, `iamcredentials`, `run` y `secretmanager`;
- sin Terraform (Deferred): la reproducibilidad actual es `gcloud` + scripts idempotentes versionados.

## Inicialización y replicación

### 1. Entorno local

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -e ".[dev]"
```

Gates canónicos:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy app
```

Ejecución local (requiere `X-API-Key` y ADC con acceso a Vertex y Firestore):

```powershell
$env:CU013_API_KEY = "<clave-local>"
.\.venv\Scripts\python.exe -m uvicorn --factory app.main:build_app --port 8080
```

Overrides opcionales de runtime: `CU013_VERTEX_PROJECT`, `CU013_VERTEX_LOCATION`, `CU013_VERTEX_MODEL`, `CU013_VERTEX_TIMEOUT_MS` y `CU013_FIRESTORE_COLLECTION`.

### 2. Base GCP (idempotente)

```powershell
pwsh -NoProfile -File .\ops\gcp\bootstrap-dev.ps1
pwsh -NoProfile -File .\ops\gcp\verify-dev.ps1
```

El bootstrap crea APIs, Firestore, Artifact Registry, service accounts e IAM; no crea Cloud Run, secretos, WIF ni Terraform. La autenticación local es ADC impersonation, nunca claves JSON:

```powershell
gcloud auth application-default login --impersonate-service-account=cu013-runtime-dev@cu013-xcally-agentic.iam.gserviceaccount.com
```

Detalle en el [runbook de bootstrap GCP DEV](docs/runbooks/gcp-dev-bootstrap.md).

### 3. Despliegue DEV (ventana de benchmark)

```powershell
powershell -File ops\gcp\deploy-dev-benchmark.ps1
python evals\cloud_run_latency.py --url <service-url>
powershell -File ops\gcp\stop-dev-benchmark.ps1
```

El deploy exige branch `dev` limpio y `HEAD == origin/dev`, construye la imagen con tag igual al SHA y despliega con `min=1`; el stop restaura `min=0` siempre. Detalle en el [runbook de benchmark Cloud Run DEV](docs/runbooks/cloud-run-dev-benchmark.md).

### 4. Replicación

- `config.yaml` versiona la configuración no sensible; los secretos viven en `.env` local (Git-ignored) o Secret Manager, nunca en el repositorio.
- `requirements.lock` fija el entorno exacto; el `Dockerfile` instala sólo runtime con ese lock.
- Los scripts de `ops/gcp/` son idempotentes y read-only donde corresponde: re-ejecutarlos no duplica recursos ni corrige drift recreando recursos.

## Autoridad y enlaces

- [Specs](docs/specs/) · [Boundary HTTP XCALLY ↔ CU013](docs/specs/xcally-boundary.md)
- [Decisions](docs/decisions/) · [ADR-0009 Thin Firestore Session Repository](docs/decisions/0009-use-thin-firestore-session-repository.md)
- [Experiments](docs/experiments/) · [Runbooks](docs/runbooks/) · [Gaps](docs/gaps.md)
- [Estándares de ingeniería](docs/engineering/) · [Manifiesto de IOP locales](docs/iop/README.md)
- [CONTEXT](CONTEXT.md) · [CHANGELOG](CHANGELOG.md) · [AGENTS](AGENTS.md)
- [config.yaml](config.yaml) · [pyproject.toml](pyproject.toml) · [requirements.lock](requirements.lock)
