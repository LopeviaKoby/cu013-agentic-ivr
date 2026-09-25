# Runbook de bootstrap DEV (estado vigente: TIVIT)

> **Estado actual:** el entorno DEV del repositorio apunta a `tivit-cu013-prd` (runtime SA `cu013-cloud-run-sa@tivit-cu013-prd.iam.gserviceaccount.com`, sin impersonation). El script vigente es `ops/gcp/bootstrap-dev.ps1` (minimal e idempotente, dry-run por defecto, sin creación de SAs). El contenido siguiente describe el bootstrap histórico del proyecto anterior y se conserva como referencia.

# GCP DEV/SPIKE Bootstrap Runbook

## PropÃ³sito

Reproducir y verificar la base GCP mÃ­nima de CU013 para DEV y SPIKE mediante `gcloud` y PowerShell, sin Terraform ni claves JSON de service accounts.

## Alcance

Incluye APIs, Firestore `(default)`, Artifact Registry, tres service accounts, siete bindings IAM y el camino local de ADC impersonation.

No crea proyecto, billing, Cloud Run, secretos, WIF, runtime, redes ni recursos de producciÃ³n.

## Precondiciones

- Google Cloud SDK instalado.
- PowerShell 7.
- `gcloud auth login` completado para una cuenta con permisos suficientes.
- Proyecto `cu013-xcally-agentic` ya creado bajo `ylopevia-org`.
- Billing ya asociado.
- RegiÃ³n acordada `us-east1`.
- Worktree revisado y sin intenciÃ³n de ejecutar cleanup destructivo.

No colocar credenciales, tokens o claves en comandos, archivos o historial.

## Variables

```text
ProjectId: cu013-xcally-agentic
ProjectNumber: 17280606194
OrganizationId: 268452702158
Region: us-east1
ConfigurationName: cu013-xcally-agentic
ArtifactRepository: cu013-containers-dev
SpikeServiceAccountId: cu013-spike-firestore
RuntimeServiceAccountId: cu013-runtime-dev
DeployerServiceAccountId: cu013-deployer-dev
BootstrapUser: ylopevia@gmail.com
```

## Orden de bootstrap

```text
configuraciÃ³n gcloud
â†’ APIs
â†’ Firestore
â†’ Artifact Registry
â†’ service accounts
â†’ IAM
â†’ ADC impersonation
â†’ verificaciÃ³n
```

Desde la raÃ­z del repositorio:

```powershell
pwsh -NoProfile -File .\ops\gcp\bootstrap-dev.ps1
```

El script no activa ni elimina otras configuraciones. Crea `cu013-xcally-agentic` con `--no-activate` cuando falta y usa `--configuration` explÃ­citamente.

## Idempotencia y stop conditions

El script consulta antes de crear o conceder. Una API o binding existente se conserva sin duplicaciÃ³n.

Se detiene si:

- el proyecto, nÃºmero u organizaciÃ³n no coinciden;
- la configuraciÃ³n dedicada contiene valores incompatibles;
- Firestore existe con otra regiÃ³n, modo o ediciÃ³n;
- Artifact Registry existe con otra ubicaciÃ³n, formato o modo;
- una consulta necesaria falla y no puede distinguirse de un recurso ausente.

Nunca corrige una incompatibilidad recreando recursos o eliminando polÃ­ticas.

## Recursos e IAM esperados

- Spike SA: `roles/datastore.user` en proyecto.
- Runtime SA: `roles/datastore.user` y `roles/aiplatform.user` en proyecto.
- Deployer SA: `roles/run.developer` en proyecto.
- Deployer SA: `roles/artifactregistry.writer` sobre `cu013-containers-dev`.
- `ylopevia@gmail.com`: `roles/iam.serviceAccountTokenCreator` sobre spike SA.
- Deployer SA: `roles/iam.serviceAccountUser` sobre runtime SA.

No se conceden Owner, Editor, Run Admin, IAM Admin, Artifact Registry Admin ni acceso a Secret Manager.

## ADC impersonation

El bootstrap imprime, pero no ejecuta, el paso interactivo:

```powershell
gcloud auth application-default login --impersonate-service-account=cu013-spike-firestore@cu013-xcally-agentic.iam.gserviceaccount.com
```

Esto crea ADC local con impersonaciÃ³n de credenciales de corta duraciÃ³n. No establecer `GOOGLE_APPLICATION_CREDENTIALS` hacia una key JSON.

## VerificaciÃ³n

```powershell
pwsh -NoProfile -File .\ops\gcp\verify-dev.ps1
```

El verificador es read-only. Exit code 0 significa que no detectÃ³ drift crÃ­tico; bindings adicionales relacionados aparecen como warnings.

## Cleanup y rollback

Los siguientes son procedimientos manuales y destructivos. **No ejecutarlos como parte del bootstrap ni sin intenciÃ³n explÃ­cita y comprobaciÃ³n previa.**

### ConfiguraciÃ³n local incorrecta

Primero inspeccionar:

```powershell
gcloud config configurations describe cu013-xcally-agentic --all
```

La eliminaciÃ³n de esa configuraciÃ³n afecta sÃ³lo estado local, pero debe hacerse manualmente tras confirmar el nombre exacto. Nunca eliminar otras configuraciones por patrÃ³n.

### Binding IAM incorrecto

Leer la policy del recurso, identificar exactamente principal, role y condiciÃ³n, y retirar sÃ³lo ese binding. Volver a ejecutar `verify-dev.ps1`. No reemplazar policies completas.

### Service account accidental

Confirmar que fue creada por error, que no estÃ¡ adjunta a un servicio y que no posee recursos o uso legÃ­timo. La eliminaciÃ³n no es cleanup rutinario.

### Artifact Registry accidental

Inspeccionar ubicaciÃ³n, contenido e IAM. SÃ³lo un repositorio confirmado como accidental y vacÃ­o puede considerarse para eliminaciÃ³n manual.

### Firestore y recursos con datos

Firestore `(default)` contiene estado durable. Eliminarlo o recrearlo es destructivo y queda fuera del cleanup rutinario. Preservar o exportar datos requiere un procedimiento separado y autorizado.

Eliminar el proyecto completo no es un rollback normal.

## Seguridad

- No usar service-account keys.
- No guardar secretos en `config.yaml`, scripts o documentaciÃ³n.
- Usar la spike SA sÃ³lo para colecciones experimentales aisladas.
- No usar AD/TIVIT, XCALLY o correo real durante el spike de persistencia.

## Costo

La base evita recursos always-on y duplicados. El servicio Cloud Run futuro tendrÃ¡ inicialmente min 0/max 1. El presupuesto externo es una alerta econÃ³mica, no un hard cap tÃ©cnico.

## Troubleshooting

- `PERMISSION_DENIED`: confirmar la cuenta autenticada y el scope del recurso; no ampliar roles automÃ¡ticamente.
- ConfiguraciÃ³n incompatible: inspeccionarla y corregirla de forma explÃ­cita; el script se detiene.
- Firestore o repositorio incompatible: STOP & REPORT; no recrear.
- ADC impersonation falla: confirmar `iamcredentials.googleapis.com` y Token Creator sobre la spike SA.
- Drift IAM adicional: revisar el warning con el propietario; el verificador no elimina bindings.

## Fuera de alcance

- servicio o revisiÃ³n Cloud Run;
- imÃ¡genes Docker;
- secretos y bindings de Secret Manager;
- WIF/GitHub Actions;
- Terraform;
- VPC, Cloud SQL, Redis o Kubernetes;
- `southamerica-east1`;
- runtime CU013 y spike Firestore/LangGraph.

## Referencias oficiales

Consultadas para Google Cloud CLI 576.0.0 y el estado documental del 15-09-2026:

- [Named configurations](https://docs.cloud.google.com/sdk/gcloud/reference/config/configurations/create)
- [Enable services](https://docs.cloud.google.com/sdk/gcloud/reference/services/enable)
- [Create a Firestore database](https://docs.cloud.google.com/sdk/gcloud/reference/firestore/databases/create)
- [Describe an Artifact Registry repository](https://docs.cloud.google.com/sdk/gcloud/reference/artifacts/repositories/describe)
- [Service account impersonation](https://docs.cloud.google.com/docs/authentication/use-service-account-impersonation)
- [Scripting gcloud CLI](https://docs.cloud.google.com/sdk/docs/scripting-gcloud)
