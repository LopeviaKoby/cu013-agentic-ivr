# ADR-0008: Inicializar GCP con gcloud reproducible antes de Terraform

- Status: Accepted
- Fecha: 2026-09-14

## Contexto y problema

CU013 está en una etapa experimental con topología aún cambiante. Necesita una base GCP reproducible y auditable sin asumir el coste de mantener IaC declarativo antes de comprender y estabilizar los recursos reales.

## Impulsores de la decisión

- Arquitectura todavía en evolución.
- PoC de bajo volumen y presupuesto estricto.
- Necesidad de entender primero los recursos reales.
- Evitar IaC prematuro.
- Mantener reproducibilidad y facilitar una futura traducción a Terraform.

## Opciones consideradas

- Aprovisionamiento reproducible con `gcloud` y scripts PowerShell versionados.
- Terraform inmediato.
- Aprovisionamiento manual no scriptado.

## Decisión

Opción elegida: **aprovisionamiento reproducible con `gcloud` y scripts PowerShell versionados durante la etapa experimental**. Terraform queda diferido hasta que la topología se estabilice o aparezca un criterio de revocación.

### Consecuencias

- Positiva: permite velocidad y experimentación explícita.
- Positiva: mantiene baja la sobrecarga actual.
- Positiva: conserva una ruta reproducible y traducible a Terraform.
- Negativa: ofrece menor detección automática de drift.
- Negativa: el rollback es menos declarativo.
- Negativa: existe dependencia temporal de scripts y runbooks.
- Negativa: será necesaria una migración futura si se adopta Terraform.

## Confirmación

- El bootstrap debe ser idempotente cuando sea razonable y detenerse ante incompatibilidades.
- La verificación debe ser estrictamente read-only y detectar drift crítico.
- No deben crearse claves de service accounts, secretos, Cloud Run, WIF o recursos no acordados.
- No debe existir `infra/terraform/` mientras esta decisión permanezca vigente.

## Criterios de revocación

Reevaluar si aparece cualquiera de estas condiciones:

- staging o producción;
- proyectos efímeros recurrentes;
- topología estable;
- drift manual significativo;
- demasiados recursos o IAM para auditar cómodamente;
- necesidad de plan/review declarativo y reproducible;
- recreación frecuente del entorno.

## Trazabilidad

- [Especificación del sistema](../specs/system.md#entorno-gcp-actual)
- [Runbook de bootstrap GCP DEV](../runbooks/gcp-dev-bootstrap.md)
- [`bootstrap-dev.ps1`](../../ops/gcp/bootstrap-dev.ps1)
- [`verify-dev.ps1`](../../ops/gcp/verify-dev.ps1)
- [CONTEXT.md](../../CONTEXT.md)
