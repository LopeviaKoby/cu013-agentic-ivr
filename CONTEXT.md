# CU013 v0.2.0 — Contexto actual

## Propósito y alcance actual

CU013 reconstruye el backend conversacional de Mesa de Ayuda para XCALLY Motion y Cally Square. El repositorio contiene autoridad documental, estándares de ingeniería, configuración no sensible y herramientas operativas reproducibles para DEV y experimentación. Todavía no contiene código de ejecución.

El primer corte de acciones de cuenta es `RESET_PASSWORD` + `UNLOCK_ACCOUNT`, sin prioridad obligatoria entre ambas.

## Pila y entorno

- Python 3.12, FastAPI, Pydantic 2, LangGraph y `google-genai`/Vertex AI.
- Firestore como único almacén durable aceptado.
- Cloud Run como destino futuro de cómputo.
- Docker, GitHub Actions, pytest, Ruff y MyPy.
- Proyecto GCP: `cu013-xcally-agentic`.
- Región primaria: `us-east1`.

## Infraestructura actual

Infraestructura GCP aprovisionada y confirmada por el propietario:

- APIs requeridas habilitadas;
- Firestore `(default)`, Native/Standard, `us-east1`;
- Artifact Registry `cu013-containers-dev`, `us-east1`;
- cuentas de servicio dedicadas para experimento, ejecución y despliegue;
- base IAM de siete asignaciones.

IAM y diseño de impersonación ADC configurados:

- identidad exclusiva `cu013-spike-firestore` para el experimento;
- acceso `roles/datastore.user`;
- autenticación local prevista mediante impersonación ADC, sin claves JSON de cuentas de servicio.

Validación ADC y lectura Firestore desde el host real de OpenCode: aprobada por el propietario con Python 3.12.2, `.venv` en Python 3.12.2 y `GOOGLE_APPLICATION_CREDENTIALS` sin definir. La impersonación ADC, el refresh de ADC mediante `google-auth` y la lectura read-only de Firestore `(default)` fueron correctos; el documento de prueba no existía.

La ausencia de valores locales predeterminados como `compute/region` o `artifacts/location` sigue siendo una desviación menor de la estación de trabajo, no un bloqueo arquitectónico.

Servicios habilitados pero aún no materializados:

- API de Cloud Run; ningún servicio desplegado;
- API de Secret Manager; ningún secreto creado;
- API de Vertex AI; código de ejecución y evaluación comparativa del modelo pendientes.

## Estado arquitectónico actual

- v0.2.0 es una arquitectura nueva y un monolito modular.
- LangGraph es el marco aceptado para orquestación de turnos.
- Los IOP corporativos locales son la autoridad del procedimiento empresarial y tienen un [manifiesto versionado](docs/iop/README.md).
- `RESET_PASSWORD` permite autoservicio guiado y acción directa autorizada después de validar identidad.
- `UNLOCK_ACCOUNT` no tiene autoservicio; la acción directa autorizada usa XCALLY/Cally Square → Orchestrator/TIVIT/AD.
- CU013 no integra tickets ITSM; el registro en herramientas de gestión está fuera del límite técnico del backend.
- La validación de identidad comienza con documento y fecha de nacimiento por DTMF.
- Los valores DTMF crudos quedan fuera del LLM y de los registros, y se minimizan en persistencia.
- SendMail está Deferred. La secuencia aceptada es: experimento de persistencia → integración AD/TIVIT → depuración guiada por logs y pruebas con callers → SendMail. CU013 sólo recibirá el estado del envío.
- La Opción A del mecanismo de checkpoints Firestore es el siguiente experimento, no un mecanismo de persistencia con estado Accepted.
- Gemini 2.5 Flash-Lite con razonamiento desactivado sigue como referencia temporal.
- No existen código de ejecución, Terraform, Dockerfile ni servicio Cloud Run.

## Puntos de entrada del repositorio

- [Especificación del sistema](docs/specs/system.md)
- [Especificación de acciones de cuenta](docs/specs/account-actions.md)
- [Decisiones arquitectónicas](docs/decisions/)
- [Gaps de implementación](docs/gaps.md)
- [Estándares de ingeniería](docs/engineering/)
- [Manifiesto de IOP locales](docs/iop/README.md)
- [Runbook de inicialización GCP](docs/runbooks/gcp-dev-bootstrap.md)
- [Experimento Firestore/LangGraph](docs/experiments/0001-firestore-langgraph-checkpointer.md)
- [`config.yaml`](config.yaml)

## Implementado, validado y pendiente

Implementado en el repositorio:

- especificaciones separadas y decisiones atómicas;
- semántica cerrada para reset, desbloqueo y límite de ticketing;
- gaps AD/TIVIT separados de la evidencia documental y centralizados en `docs/gaps.md`;
- manifiesto versionado para IOP locales de sólo lectura;
- estándares de Python, fiabilidad y pruebas;
- configuración ejecutable de Ruff, MyPy y pytest en `pyproject.toml`;
- configuración transitoria `packages = []` mientras no exista un paquete Python productivo;
- base GCP y decisión de inicialización documentadas;
- configuración no sensible;
- guion reproducible de inicialización y verificador de sólo lectura;
- registro planificado del experimento.

Validado localmente el 15-09-2026:

- integridad SHA-256 de los dos IOP y coincidencia exacta de nombres;
- PDF de IOP ignorados por Git y manifiesto versionable;
- Python 3.12.2 en `.venv`, instalación editable DEV correcta y gates Ruff 0.16.5 aprobados;
- impersonación ADC, refresh `google-auth` y lectura read-only de Firestore validados desde el host real por el propietario;
- MyPy 1.20.2 con modo estricto y sin ignorar imports globalmente;
- pytest 8.4.2 y pytest-asyncio 0.26.0 con `asyncio_mode = "auto"`;
- sintaxis PowerShell y estructura YAML de la iteración anterior;
- enlaces Markdown, límites documentales, ausencia de atajos TLS y consistencia de artefactos;
- índice CodeGraph válido con 0 símbolos de código.

Pendiente:

- ejecutar la Opción A en `spike/firestore-checkpointer` mediante un encargo separado a OpenCode;
- decidir el mecanismo LangGraph↔Firestore con evidencia;
- evaluar Gemini 2.5 Flash-Lite y una alternativa antes del 16-10-2026;
- validar los contratos externos aún abiertos antes de acciones de cuenta productivas.

## Control operativo previo al experimento

El propietario confirmó desde el host real la cadena completa `ADC impersonation → google-auth refresh → Firestore read-only` con `cu013-spike-firestore` sobre el proyecto `cu013-xcally-agentic` y la base `(default)`. El control previo al experimento está aprobado.

Nunca deshabilitar TLS ni la verificación de certificados para sortear el problema.

## Bloqueos y preguntas abiertas

- Conjunto seguro y compatible de versiones LangGraph/Firestore y contrato concreto del saver al ejecutar el experimento.
- Evidencia de latencia, amplificación de escrituras, contención y recuperación de la Opción A.
- Contrato objetivo XCALLY↔CU013.
- Correlación, idempotencia, polling, reintentos y resultados tardíos.
- Esquema completo de resultados XCALLY/Orchestrator/TIVIT/AD.
- Mapeo exacto de estados externos a respuesta o escalamiento cuando aún no esté probado.
- La validación de TTL requiere permisos no concedidos a la cuenta de servicio del experimento.

SendMail permanece Deferred y fuera del alcance inmediato. Los valores predeterminados ausentes de la configuración local no son bloqueos arquitectónicos.

## Próximo incremento

En un encargo separado, preparar el árbol de trabajo `spike/firestore-checkpointer` para que OpenCode ejecute la Opción A.

## Ciclo de vida

```text
iteración
→ implementación y pruebas
→ aceptación
→ actualizar CONTEXT
→ integrar/commit
```

No añadir a esta instantánea trabajo especulativo o no aceptado.

## Hitos anteriores

- Limpieza destructiva y reinicio arquitectónico preservados por el tag de auditoría.
- Base GCP DEV/SPIKE e impersonación ADC con lectura Firestore confirmadas por el propietario.
- Baseline documental y operativa v0.2.0 reconciliada para `dev`.
