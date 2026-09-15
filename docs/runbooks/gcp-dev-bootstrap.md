# GCP DEV/SPIKE Bootstrap Runbook

## Propósito

Reproducir y verificar la base GCP mínima de CU013 para DEV y SPIKE mediante `gcloud` y PowerShell, sin Terraform ni claves JSON de service accounts.

## Alcance

Incluye APIs, Firestore `(default)`, Artifact Registry, tres service accounts, siete bindings IAM y el camino local de ADC impersonation.

No crea proyecto, billing, Cloud Run, secretos, WIF, runtime, redes ni recursos de producción.

## Precondiciones

- Google Cloud SDK instalado.
- PowerShell 7.
- `gcloud auth login` completado para una cuenta con permisos suficientes.
- Proyecto `cu013-xcally-agentic` ya creado bajo `ylopevia-org`.
- Billing ya asociado.
- Región acordada `us-east1`.
- Worktree revisado y sin intención de ejecutar cleanup destructivo.

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
configuración gcloud
→ APIs
→ Firestore
→ Artifact Registry
→ service accounts
→ IAM
→ ADC impersonation
→ verificación
```

Desde la raíz del repositorio:

```powershell
pwsh -NoProfile -File .\ops\gcp\bootstrap-dev.ps1
```

El script no activa ni elimina otras configuraciones. Crea `cu013-xcally-agentic` con `--no-activate` cuando falta y usa `--configuration` explícitamente.

## Idempotencia y stop conditions

El script consulta antes de crear o conceder. Una API o binding existente se conserva sin duplicación.

Se detiene si:

- el proyecto, número u organización no coinciden;
- la configuración dedicada contiene valores incompatibles;
- Firestore existe con otra región, modo o edición;
- Artifact Registry existe con otra ubicación, formato o modo;
- una consulta necesaria falla y no puede distinguirse de un recurso ausente.

Nunca corrige una incompatibilidad recreando recursos o eliminando políticas.

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

Esto crea ADC local con impersonación de credenciales de corta duración. No establecer `GOOGLE_APPLICATION_CREDENTIALS` hacia una key JSON.

## Verificación

```powershell
pwsh -NoProfile -File .\ops\gcp\verify-dev.ps1
```

El verificador es read-only. Exit code 0 significa que no detectó drift crítico; bindings adicionales relacionados aparecen como warnings.

## Cleanup y rollback

Los siguientes son procedimientos manuales y destructivos. **No ejecutarlos como parte del bootstrap ni sin intención explícita y comprobación previa.**

### Configuración local incorrecta

Primero inspeccionar:

```powershell
gcloud config configurations describe cu013-xcally-agentic --all
```

La eliminación de esa configuración afecta sólo estado local, pero debe hacerse manualmente tras confirmar el nombre exacto. Nunca eliminar otras configuraciones por patrón.

### Binding IAM incorrecto

Leer la policy del recurso, identificar exactamente principal, role y condición, y retirar sólo ese binding. Volver a ejecutar `verify-dev.ps1`. No reemplazar policies completas.

### Service account accidental

Confirmar que fue creada por error, que no está adjunta a un servicio y que no posee recursos o uso legítimo. La eliminación no es cleanup rutinario.

### Artifact Registry accidental

Inspeccionar ubicación, contenido e IAM. Sólo un repositorio confirmado como accidental y vacío puede considerarse para eliminación manual.

### Firestore y recursos con datos

Firestore `(default)` contiene estado durable. Eliminarlo o recrearlo es destructivo y queda fuera del cleanup rutinario. Preservar o exportar datos requiere un procedimiento separado y autorizado.

Eliminar el proyecto completo no es un rollback normal.

## Seguridad

- No usar service-account keys.
- No guardar secretos en `config.yaml`, scripts o documentación.
- Usar la spike SA sólo para colecciones experimentales aisladas.
- No usar AD/TIVIT, XCALLY o correo real durante el spike de persistencia.

## Costo

La base evita recursos always-on y duplicados. El servicio Cloud Run futuro tendrá inicialmente min 0/max 1. El presupuesto externo es una alerta económica, no un hard cap técnico.

## Troubleshooting

- `PERMISSION_DENIED`: confirmar la cuenta autenticada y el scope del recurso; no ampliar roles automáticamente.
- Configuración incompatible: inspeccionarla y corregirla de forma explícita; el script se detiene.
- Firestore o repositorio incompatible: STOP & REPORT; no recrear.
- ADC impersonation falla: confirmar `iamcredentials.googleapis.com` y Token Creator sobre la spike SA.
- Drift IAM adicional: revisar el warning con el propietario; el verificador no elimina bindings.

## Fuera de alcance

- servicio o revisión Cloud Run;
- imágenes Docker;
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
