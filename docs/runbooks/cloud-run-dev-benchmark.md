> **Estado actual:** el entorno DEV apunta a `tivit-cu013-prd` con la runtime SA `cu013-cloud-run-sa@tivit-cu013-prd.iam.gserviceaccount.com` y sin impersonation. El servicio `cu013-runtime-dev` está desplegado (`min=0` en reposo; la ventana warm ya se cerró) y la tag `e2e-en` se conserva como referencia. El contenido siguiente se conserva como referencia del entorno anterior.

# Runbook: Cloud Run DEV warm baseline (pre-XCALLY E2E)

Este runbook opera el servicio DEV `cu013-runtime-dev` en `us-east1` para la
ventana de benchmark. El estado de reposo aceptado es `min-instances=0`;
`min-instances=1` existe sólo durante la ventana y se paga a tarifa idle
con billing request-based. **Debe volver a 0 al terminar, pase o falle el
benchmark.**

## Prerrequisitos de IAM y secret (una sola vez)

- Secret Manager `cu013-api-key-dev`: 32 bytes aleatorios creados por el
  owner; versión desde stdin y sin salto de línea; la runtime SA
  `cu013-cloud-run-sa@tivit-cu013-prd.iam.gserviceaccount.com` recibe
  únicamente `roles/secretmanager.secretAccessor` a nivel de secreto. El
  mismo binding se aplica a los secretos de protocolo
  (`cu013-protocol-reset-password-dev` y `cu013-protocol-unlock-account-dev`).
- Sin impersonation: build/push/deploy usan el token de la cuenta activa
  (`pedro.lopez@tivit.com`); no hay SA de despliegue ni de spike en uso.
- `--allow-unauthenticated` requiere permiso de setIamPolicy sobre el
  servicio; decisión PROVISIONAL limitada a DEV: la autenticación real del
  boundary sigue siendo `X-API-Key`. Si el dominio restringido (DRS) lo
  bloquea, STOP & REPORT.
- Montaje de protocolos: un árbol de directorios por secreto (Cloud Run
  rechaza dos secretos en el mismo directorio) con
  `CU013_PROTOCOL_RESET_FILE` y `CU013_PROTOCOL_UNLOCK_FILE`.
- No se crean VPC, connector, load balancer, Redis ni Cloud SQL.

## Ventana de benchmark

Si la versión 1 de `cu013-api-key-dev` contiene CR/LF/NUL y no puede usarse
en `X-API-Key`, el owner debe cerrar primero la ventana con
`stop-dev-benchmark.ps1`. Después puede ejecutar
`rotate-dev-benchmark-api-key.ps1`: el script confirma `min=0`, imagen y
referencia actuales; añade una versión al secret existente con bytes
exactos sin salto de línea, verifica la lectura, actualiza la referencia
numérica del servicio y restaura `min=1`. Esta operación crea una revisión
nueva sin reconstruir la imagen. El valor no se imprime ni se guarda en
`.env`. La versión 1 permanece como evidencia; su deshabilitación se
decidirá después de comprobar la nueva revisión.

En el JSON de Cloud Run, los mínimos no configurados pueden estar ausentes:
`autoscaling.knative.dev/minScale` en la plantilla de revisión y
`run.googleapis.com/minScale` en el servicio equivalen entonces a cero.
El verificador comprueba ambos niveles para no confundir un mínimo de
servicio activo con una revisión aparentemente inactiva.

1. `powershell -File ops/gcp/deploy-dev-benchmark.ps1`
   - valida branch dev + worktree limpio + HEAD == origin/dev;
   - comprueba Docker, gcloud y Artifact Registry;
   - toma la versión numérica habilitada más reciente del secret (nunca su
     valor);
   - construye la imagen con el tag `us-east1-docker.pkg.dev/.../cu013-containers-dev/cu013-runtime-dev:<git-sha>`;
   - hace login/push con token impersonado del deployer (nunca impreso);
   - despliega con runtime SA, 1 vCPU / 512 MiB, concurrency 1, max 1,
     min 1 (ventana), cpu throttling, `--allow-unauthenticated` y
     `CU013_API_KEY` desde Secret Manager fijado a versión numérica;
   - imprime URL, revisión, digest de imagen y configuración efectiva.
2. Ejecutar el cliente E2E desde la shell del owner (contiene
   `$env:CU013_API_KEY`, que el cliente lee sin imprimir):
   `python evals/cloud_run_latency.py --url <service-url>`
   - si la sesión no conserva la variable, cargar sólo la versión fijada en
     memoria con
     `. .\ops\gcp\set-dev-benchmark-api-key.ps1 -SecretVersion <versión>`;
     tras la rotación, no usar el valor por defecto (versión 1). El script se
     ejecuta mediante dot-sourcing, no imprime ni persiste el valor y rechaza
     una versión que contenga NUL o saltos de línea (inválidos en `X-API-Key`);
   - conservar la salida completa sin secretos: incluye `benchmark_prefix`,
     `measured_started_at_utc` y `measured_ended_at_utc` para recuperar sólo
     las métricas server-side de las 30 requests medidas;
   - `first` es la primera request medida en orden temporal; `min` y los
     percentiles se calculan independientemente sobre la distribución.
   - la instancia productiva de `StructuredLogTurnMetrics` emite líneas
     `turn_metric` INFO al stderr capturado por Cloud Run. Recuperar
     `handler`, `session_load`, `model`, `graph` y `session_save` del intervalo
     medido; calcular `runtime = graph - model` por request, como en el
     experimento 0003. No atribuir métricas si falta algún segmento.
3. Verificación read-only durante la ventana:
   `powershell -File ops/gcp/verify-dev-benchmark.ps1 -ExpectedMinInstances 1`
   (nunca imprime el valor del secret). Tras rotar, añadir
   `-ExpectedSecretVersion <versión>` y comparar el tag de imagen.
4. **Apagar obligatoriamente**:
   `powershell -File ops/gcp/stop-dev-benchmark.ps1`
   y verificar `min instances: 0` con `-ExpectedMinInstances 0`.
5. Limpiar la variable sensible: `Remove-Item Env:CU013_API_KEY -ErrorAction SilentlyContinue`.

## Cost guard

`min=1` se paga a tarifa idle cuando no procesa requests. No introducir
recursos always-on adicionales; no usar instance-based billing. Si la
ventana se interrumpe, ejecutar el paso 4 igualmente.

## Experimento 0009 — ráfaga de ocho callers (PREPARADO, NO EJECUTADO)

Esta sección prepara el benchmark de capacidad del
[Experimento 0009](../experiments/0009-conversational-memory-and-eight-callers.md)
sin ejecutarlo: ningún comando aquí crea revisiones, cambia tráfico,
construye imágenes ni genera gasto. La ejecución requiere autorización
separada del owner con ventana explícita.

Artefactos preparados (esta iteración):

- `evals/conversation_burst.py`: cliente de barrera de ocho IDs sintéticos
  distintos, seam determinista async (mismo render de prompt/memoria y
  validación de decisión, delay fijo declarado de 600 ms, resultado fijo
  seguro; sin Vertex ni AD), colección de métricas client-side
  (release/arrival skew, wall por request, errores/timeouts), estimador de
  costo con stop-line, escritor de manifiesto de documentos sintéticos y
  plan propuesto impreso. `--self-check` valida la mecánica en local
  (in-memory, sin red); `--estimate-only`, `--print-plan` y
  `--manifest-only` no tocan cloud. Cualquier `--url`/`--execute-live`
  se rechaza sin una autorización distinta.
- `ops/gcp/collect-burst-prestate.ps1`: captura read-only del pre-state
  (`spec.traffic` completo con porcentajes, tags y `latestRevision` frente
  a `revisionName`, escalado service/revision, image digests, entorno).
- Estimación (tarifas recuperadas el 2026-09-18, a reconfirmar al
  autorizar): Fase A ≈ US$0.03 (744 requests con seam, sin Vertex),
  Fase B ≈ US$0.08 (336 requests con provider real),
  Fase C ≈ US$0.01 (48 requests cold), cleanup ≈ US$0.00;
  **total ≈ US$0.12**, dentro del stop-line de US$2.50 (presupuesto
  US$3/mes). Detalle: `python evals/conversation_burst.py --estimate-only`.

Diseño autorizado (sólo tras autorización separada):

- Fase A: 1 vCPU / 512 MiB, **concurrency=8, max_instances=1** primero con
  el seam; si falla por contención/latencia: concurrency=4/max=2; sólo
  después concurrency=2/max=4. Al menos 30 ráfagas por brazo en al menos
  tres ventanas de 60 s, alternando brazos; **no** 2 vCPU/workers/threads/
  uvloop por anticipación.
- Fase B: provider real sólo para configuración(es) prometedora(s),
  al menos 20 ráfagas válidas por brazo.
- Fase C: cold burst separado con `min_instances=0` verificado antes de
  cada una de al menos cinco ráfagas.
- Revisión tagged temporal con `--no-traffic` sobre el servicio DEV
  existente (reutiliza IAM/red/secretos/Firestore) **sólo si** el pre-state
  y la semántica de restauración de `LATEST` son demostrables; si no, se
  propone servicio aislado temporal en lugar de crearlo profilácticamente.
- Rollback exacto: `gcloud run services update-traffic SERVICE
  --remove-tags TAG`, borrado sólo de revisiones 0%-tráfico listadas, y
  verificación de `spec.traffic`, tráfico efectivo, `min_instances=0`,
  imagen servidora original y ninguna revisión warm facturable. Nunca
  `--to-latest` mientras una revisión experimental pueda volverse latest.
- Limpieza Firestore: borrar documento a documento sólo los IDs del
  manifiesto, bajo autorización de cleanup; sin wildcards ni
  collection-group deletes.

Monitoreo (filtrado por revisión tagged y ventana UTC; las métricas pueden
llegar con retraso de muestreo):

- `run.googleapis.com/container/cpu/utilizations`,
  `container/memory/utilizations`, `container/max_request_concurrencies`,
  `container/instance_count`, `container/startup_latencies`,
  `request_latencies`, `request_count`, más `request_latency/pending` y
  `request_latency/e2e_latencies`; correlación por `turn_id`/run ID
  sintético, nunca transcript.

## Referencias

- [Configuración no sensible](../../config.yaml)
- [Experimento 0003 — baseline local](../experiments/0003-gemini-baseline-latency.md)
- [Experimento 0004 — baseline Cloud Run](../experiments/0004-cloud-run-latency.md)
- Nota de selección 2026-09-19: el carril temporal multi-proveedor fue
  retirado del runtime activo; su historia vive en el Experimento 0009 y
  Git.
