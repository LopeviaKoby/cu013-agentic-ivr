> **Estado actual:** el entorno DEV apunta a `tivit-cu013-prd` con la runtime SA `cu013-cloud-run-sa@tivit-cu013-prd.iam.gserviceaccount.com` y sin impersonation; los scripts `ops/gcp/deploy-dev-benchmark.ps1` y `ops/gcp/verify-dev-benchmark.ps1` ya están retargeteados. El aprovisionamiento TIVIT está preparado y no ejecutado. El contenido siguiente se conserva como referencia del entorno anterior.

# Runbook: Cloud Run DEV warm baseline (pre-XCALLY E2E)

Este runbook opera el servicio DEV `cu013-runtime-dev` en `us-east1` para la
ventana de benchmark. El estado de reposo aceptado es `min-instances=0`;
`min-instances=1` existe sÃ³lo durante la ventana y se paga a tarifa idle
con billing request-based. **Debe volver a 0 al terminar, pase o falle el
benchmark.**

## Prerrequisitos de IAM y secret (una sola vez)

- Secret Manager `cu013-api-key-dev`: 32 bytes aleatorios creados por el
  owner; primera versiÃ³n desde stdin; el runtime SA (`cu013-runtime-dev`)
  recibe Ãºnicamente `roles/secretmanager.secretAccessor` sobre ese secret.
  El deployer SA recibe `roles/secretmanager.secretAccessor` sobre el mismo
  secret sÃ³lo para validar `--set-secrets` en el despliegue.
- ImpersonaciÃ³n: el owner necesita `iam.serviceAccounts.getAccessToken`
  sobre `cu013-deployer-dev` para build/push/deploy.
- `cu013-deployer-dev` necesita `run.services.setIamPolicy` (custom role
  mÃ­nimo) para `--allow-unauthenticated`, decisiÃ³n PROVISIONAL limitada a
  DEV: la autenticaciÃ³n real del boundary sigue siendo `X-API-Key`.
- No se crean VPC, connector, load balancer, Redis ni Cloud SQL.

## Ventana de benchmark

Si la versiÃ³n 1 de `cu013-api-key-dev` contiene CR/LF/NUL y no puede usarse
en `X-API-Key`, el owner debe cerrar primero la ventana con
`stop-dev-benchmark.ps1`. DespuÃ©s puede ejecutar
`rotate-dev-benchmark-api-key.ps1`: el script confirma `min=0`, imagen y
referencia actuales; aÃ±ade una versiÃ³n al secret existente con bytes
exactos sin salto de lÃ­nea, verifica la lectura, actualiza la referencia
numÃ©rica del servicio y restaura `min=1`. Esta operaciÃ³n crea una revisiÃ³n
nueva sin reconstruir la imagen. El valor no se imprime ni se guarda en
`.env`. La versiÃ³n 1 permanece como evidencia; su deshabilitaciÃ³n se
decidirÃ¡ despuÃ©s de comprobar la nueva revisiÃ³n.

En el JSON de Cloud Run, los mÃ­nimos no configurados pueden estar ausentes:
`autoscaling.knative.dev/minScale` en la plantilla de revisiÃ³n y
`run.googleapis.com/minScale` en el servicio equivalen entonces a cero.
El verificador comprueba ambos niveles para no confundir un mÃ­nimo de
servicio activo con una revisiÃ³n aparentemente inactiva.

1. `powershell -File ops/gcp/deploy-dev-benchmark.ps1`
   - valida branch dev + worktree limpio + HEAD == origin/dev;
   - comprueba Docker, gcloud y Artifact Registry;
   - toma la versiÃ³n numÃ©rica habilitada mÃ¡s reciente del secret (nunca su
     valor);
   - construye la imagen con el tag `us-east1-docker.pkg.dev/.../cu013-containers-dev/cu013-runtime-dev:<git-sha>`;
   - hace login/push con token impersonado del deployer (nunca impreso);
   - despliega con runtime SA, 1 vCPU / 512 MiB, concurrency 1, max 1,
     min 1 (ventana), cpu throttling, `--allow-unauthenticated` y
     `CU013_API_KEY` desde Secret Manager fijado a versiÃ³n numÃ©rica;
   - imprime URL, revisiÃ³n, digest de imagen y configuraciÃ³n efectiva.
2. Ejecutar el cliente E2E desde la shell del owner (contiene
   `$env:CU013_API_KEY`, que el cliente lee sin imprimir):
   `python evals/cloud_run_latency.py --url <service-url>`
   - si la sesiÃ³n no conserva la variable, cargar sÃ³lo la versiÃ³n fijada en
     memoria con
     `. .\ops\gcp\set-dev-benchmark-api-key.ps1 -SecretVersion <versiÃ³n>`;
     tras la rotaciÃ³n, no usar el valor por defecto (versiÃ³n 1). El script se
     ejecuta mediante dot-sourcing, no imprime ni persiste el valor y rechaza
     una versiÃ³n que contenga NUL o saltos de lÃ­nea (invÃ¡lidos en `X-API-Key`);
   - conservar la salida completa sin secretos: incluye `benchmark_prefix`,
     `measured_started_at_utc` y `measured_ended_at_utc` para recuperar sÃ³lo
     las mÃ©tricas server-side de las 30 requests medidas;
   - `first` es la primera request medida en orden temporal; `min` y los
     percentiles se calculan independientemente sobre la distribuciÃ³n.
   - la instancia productiva de `StructuredLogTurnMetrics` emite lÃ­neas
     `turn_metric` INFO al stderr capturado por Cloud Run. Recuperar
     `handler`, `session_load`, `model`, `graph` y `session_save` del intervalo
     medido; calcular `runtime = graph - model` por request, como en el
     experimento 0003. No atribuir mÃ©tricas si falta algÃºn segmento.
3. VerificaciÃ³n read-only durante la ventana:
   `powershell -File ops/gcp/verify-dev-benchmark.ps1 -ExpectedMinInstances 1`
   (nunca imprime el valor del secret). Tras rotar, aÃ±adir
   `-ExpectedSecretVersion <versiÃ³n>` y comparar el tag de imagen.
4. **Apagar obligatoriamente**:
   `powershell -File ops/gcp/stop-dev-benchmark.ps1`
   y verificar `min instances: 0` con `-ExpectedMinInstances 0`.
5. Limpiar la variable sensible: `Remove-Item Env:CU013_API_KEY -ErrorAction SilentlyContinue`.

## Cost guard

`min=1` se paga a tarifa idle cuando no procesa requests. No introducir
recursos always-on adicionales; no usar instance-based billing. Si la
ventana se interrumpe, ejecutar el paso 4 igualmente.

## Experimento 0009 â€” rÃ¡faga de ocho callers (PREPARADO, NO EJECUTADO)

Esta secciÃ³n prepara el benchmark de capacidad del
[Experimento 0009](../experiments/0009-conversational-memory-and-eight-callers.md)
sin ejecutarlo: ningÃºn comando aquÃ­ crea revisiones, cambia trÃ¡fico,
construye imÃ¡genes ni genera gasto. La ejecuciÃ³n requiere autorizaciÃ³n
separada del owner con ventana explÃ­cita.

Artefactos preparados (esta iteraciÃ³n):

- `evals/conversation_burst.py`: cliente de barrera de ocho IDs sintÃ©ticos
  distintos, seam determinista async (mismo render de prompt/memoria y
  validaciÃ³n de decisiÃ³n, delay fijo declarado de 600 ms, resultado fijo
  seguro; sin Vertex ni AD), colecciÃ³n de mÃ©tricas client-side
  (release/arrival skew, wall por request, errores/timeouts), estimador de
  costo con stop-line, escritor de manifiesto de documentos sintÃ©ticos y
  plan propuesto impreso. `--self-check` valida la mecÃ¡nica en local
  (in-memory, sin red); `--estimate-only`, `--print-plan` y
  `--manifest-only` no tocan cloud. Cualquier `--url`/`--execute-live`
  se rechaza sin una autorizaciÃ³n distinta.
- `ops/gcp/collect-burst-prestate.ps1`: captura read-only del pre-state
  (`spec.traffic` completo con porcentajes, tags y `latestRevision` frente
  a `revisionName`, escalado service/revision, image digests, entorno).
- EstimaciÃ³n (tarifas recuperadas el 2026-09-18, a reconfirmar al
  autorizar): Fase A â‰ˆ US$0.03 (744 requests con seam, sin Vertex),
  Fase B â‰ˆ US$0.08 (336 requests con provider real),
  Fase C â‰ˆ US$0.01 (48 requests cold), cleanup â‰ˆ US$0.00;
  **total â‰ˆ US$0.12**, dentro del stop-line de US$2.50 (presupuesto
  US$3/mes). Detalle: `python evals/conversation_burst.py --estimate-only`.

DiseÃ±o autorizado (sÃ³lo tras autorizaciÃ³n separada):

- Fase A: 1 vCPU / 512 MiB, **concurrency=8, max_instances=1** primero con
  el seam; si falla por contenciÃ³n/latencia: concurrency=4/max=2; sÃ³lo
  despuÃ©s concurrency=2/max=4. Al menos 30 rÃ¡fagas por brazo en al menos
  tres ventanas de 60 s, alternando brazos; **no** 2 vCPU/workers/threads/
  uvloop por anticipaciÃ³n.
- Fase B: provider real sÃ³lo para configuraciÃ³n(es) prometedora(s),
  al menos 20 rÃ¡fagas vÃ¡lidas por brazo.
- Fase C: cold burst separado con `min_instances=0` verificado antes de
  cada una de al menos cinco rÃ¡fagas.
- RevisiÃ³n tagged temporal con `--no-traffic` sobre el servicio DEV
  existente (reutiliza IAM/red/secretos/Firestore) **sÃ³lo si** el pre-state
  y la semÃ¡ntica de restauraciÃ³n de `LATEST` son demostrables; si no, se
  propone servicio aislado temporal en lugar de crearlo profilÃ¡cticamente.
- Rollback exacto: `gcloud run services update-traffic SERVICE
  --remove-tags TAG`, borrado sÃ³lo de revisiones 0%-trÃ¡fico listadas, y
  verificaciÃ³n de `spec.traffic`, trÃ¡fico efectivo, `min_instances=0`,
  imagen servidora original y ninguna revisiÃ³n warm facturable. Nunca
  `--to-latest` mientras una revisiÃ³n experimental pueda volverse latest.
- Limpieza Firestore: borrar documento a documento sÃ³lo los IDs del
  manifiesto, bajo autorizaciÃ³n de cleanup; sin wildcards ni
  collection-group deletes.

Monitoreo (filtrado por revisiÃ³n tagged y ventana UTC; las mÃ©tricas pueden
llegar con retraso de muestreo):

- `run.googleapis.com/container/cpu/utilizations`,
  `container/memory/utilizations`, `container/max_request_concurrencies`,
  `container/instance_count`, `container/startup_latencies`,
  `request_latencies`, `request_count`, mÃ¡s `request_latency/pending` y
  `request_latency/e2e_latencies`; correlaciÃ³n por `turn_id`/run ID
  sintÃ©tico, nunca transcript.

## Referencias

- [ConfiguraciÃ³n no sensible](../../config.yaml)
- [Experimento 0003 â€” baseline local](../experiments/0003-gemini-baseline-latency.md)
- [Experimento 0004 â€” baseline Cloud Run](../experiments/0004-cloud-run-latency.md)
- Nota de selecciÃ³n 2026-09-19: el carril temporal multi-proveedor fue
  retirado del runtime activo; su historia vive en el Experimento 0009 y
  Git.
