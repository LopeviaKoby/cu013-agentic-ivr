# Runbook: Cloud Run DEV warm baseline (pre-XCALLY E2E)

Este runbook opera el servicio DEV `cu013-runtime-dev` en `us-east1` para la
ventana de benchmark. El estado de reposo aceptado es `min-instances=0`;
`min-instances=1` existe sólo durante la ventana y se paga a tarifa idle
con billing request-based. **Debe volver a 0 al terminar, pase o falle el
benchmark.**

## Prerrequisitos de IAM y secret (una sola vez)

- Secret Manager `cu013-api-key-dev`: 32 bytes aleatorios creados por el
  owner; primera versión desde stdin; el runtime SA (`cu013-runtime-dev`)
  recibe únicamente `roles/secretmanager.secretAccessor` sobre ese secret.
  El deployer SA recibe `roles/secretmanager.secretAccessor` sobre el mismo
  secret sólo para validar `--set-secrets` en el despliegue.
- Impersonación: el owner necesita `iam.serviceAccounts.getAccessToken`
  sobre `cu013-deployer-dev` para build/push/deploy.
- `cu013-deployer-dev` necesita `run.services.setIamPolicy` (custom role
  mínimo) para `--allow-unauthenticated`, decisión PROVISIONAL limitada a
  DEV: la autenticación real del boundary sigue siendo `X-API-Key`.
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

## Referencias

- [Configuración no sensible](../../config.yaml)
- [Experimento 0003 — baseline local](../../experiments/0003-gemini-baseline-latency.md)
- [Experimento 0004 — baseline Cloud Run](../../experiments/0004-cloud-run-latency.md)
