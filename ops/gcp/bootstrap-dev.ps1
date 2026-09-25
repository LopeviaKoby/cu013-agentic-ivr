#requires -Version 5.1
<#
.SYNOPSIS
Minimal, idempotent TIVIT DEV bootstrap for CU013 (prepared, owner-run only).

.NOTES
Creates or reuses ONLY the resources the DEV environment actually needs:
the gcloud configuration, the required APIs (already enabled in
tivit-cu013-prd), the Artifact Registry repository and the API-key secret.
It never creates service accounts, buckets, Pub/Sub topics, VPC, Cloud SQL,
Redis, Workload Identity Federation or GitHub Actions resources, and it never
impersonates another identity.

The API-key secret version is intentionally NOT created here: it must be added
by the owner from stdin, never printed or persisted:
  openssl rand -base64 32 | gcloud secrets versions add cu013-api-key-dev `
    --project=tivit-cu013-prd --data-file=-

Usage (after explicit owner authorization):
  .\ops\gcp\bootstrap-dev.ps1 -Confirm:$false
#>
[CmdletBinding()]
param(
    [string]$ProjectId = "tivit-cu013-prd",
    [string]$ProjectNumber = "731118338507",
    [string]$OrganizationId = "974679392812",
    [string]$ConfigurationName = "tivit-cu013-prd",
    [string]$Account = "pedro.lopez@tivit.com",
    [string]$Region = "us-east1",
    [string]$ArtifactRepository = "cu013-containers-dev",
    [string]$SecretName = "cu013-api-key-dev",
    [string]$RuntimeServiceAccount = "cu013-cloud-run-sa@tivit-cu013-prd.iam.gserviceaccount.com",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

$RequiredApis = @(
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com"
)

function Invoke-Gcloud {
    param([Parameter(Mandatory)][string[]]$Arguments, [switch]$AllowFailure)
    $output = @(& gcloud @Arguments 2>&1)
    $exit = $LASTEXITCODE
    if ($exit -ne 0 -and -not $AllowFailure) {
        throw "gcloud $($Arguments -join ' ') failed (exit $exit): $($output -join ' ')"
    }
    return [pscustomobject]@{ Exit = $exit; Lines = $output }
}

Write-Host "== plan (nothing is applied unless -Apply is passed)"
Write-Host "project:  $ProjectId ($ProjectNumber)"
Write-Host "config:   $ConfigurationName (account $Account, region $Region)"
Write-Host "artifact: $ArtifactRepository"
Write-Host "secret:   $SecretName"
Write-Host "runtime:  $RuntimeServiceAccount"

if (-not $Apply) {
    Write-Host "[DRY-RUN] pass -Apply to create the missing resources."
    exit 0
}

Write-Host "== ensure gcloud configuration"
$configurations = (Invoke-Gcloud -Arguments @(
        "config", "configurations", "list", "--format=json"
    )).Lines -join [Environment]::NewLine
if ($configurations -notmatch [regex]::Escape($ConfigurationName)) {
    Invoke-Gcloud -Arguments @(
        "config", "configurations", "create", $ConfigurationName, "--no-activate"
    ) | Out-Null
}
Invoke-Gcloud -Arguments @(
    "config", "set", "project", $ProjectId, "--configuration=$ConfigurationName"
) | Out-Null
Invoke-Gcloud -Arguments @(
    "config", "set", "run/region", $Region, "--configuration=$ConfigurationName"
) | Out-Null
Invoke-Gcloud -Arguments @(
    "config", "set", "account", $Account, "--configuration=$ConfigurationName"
) | Out-Null

Write-Host "== verify project identity"
$project = (Invoke-Gcloud -Arguments @(
        "projects", "describe", $ProjectId,
        "--configuration=$ConfigurationName", "--format=json"
    )).Lines -join [Environment]::NewLine | ConvertFrom-Json
if ([string]$project.projectNumber -ne $ProjectNumber) {
    throw "project number mismatch: $($project.projectNumber); expected $ProjectNumber"
}

Write-Host "== ensure required APIs"
$enabled = (Invoke-Gcloud -Arguments @(
        "services", "list", "--enabled", "--project=$ProjectId",
        "--configuration=$ConfigurationName", "--format=value(config.name)"
    )).Lines
foreach ($api in $RequiredApis) {
    if ($enabled -contains $api) {
        Write-Host "[OK] $api"
        continue
    }
    Write-Host "[CREATE] enable $api"
    Invoke-Gcloud -Arguments @(
        "services", "enable", $api, "--project=$ProjectId",
        "--configuration=$ConfigurationName", "--quiet"
    ) | Out-Null
}

Write-Host "== ensure Artifact Registry repository"
$repositories = (Invoke-Gcloud -Arguments @(
        "artifacts", "repositories", "list", "--location=$Region",
        "--project=$ProjectId", "--configuration=$ConfigurationName", "--format=value(name)"
    )).Lines
if ($repositories -notcontains $ArtifactRepository) {
    Invoke-Gcloud -Arguments @(
        "artifacts", "repositories", "create", $ArtifactRepository,
        "--repository-format=docker", "--location=$Region", "--project=$ProjectId",
        "--configuration=$ConfigurationName", "--quiet"
    ) | Out-Null
    Write-Host "[CREATE] $ArtifactRepository"
} else {
    Write-Host "[OK] $ArtifactRepository"
}

Write-Host "== ensure API-key secret and runtime accessor"
$secrets = (Invoke-Gcloud -Arguments @(
        "secrets", "list", "--project=$ProjectId",
        "--configuration=$ConfigurationName", "--format=value(name)"
    )).Lines
if ($secrets -notcontains $SecretName) {
    Invoke-Gcloud -Arguments @(
        "secrets", "create", $SecretName, "--project=$ProjectId",
        "--configuration=$ConfigurationName", "--replication-policy=automatic", "--quiet"
    ) | Out-Null
    Write-Host "[CREATE] $SecretName (add the first version from stdin)"
} else {
    Write-Host "[OK] $SecretName"
}
Invoke-Gcloud -Arguments @(
    "secrets", "add-iam-policy-binding", $SecretName,
    "--project=$ProjectId", "--configuration=$ConfigurationName",
    "--member=serviceAccount:$RuntimeServiceAccount",
    "--role=roles/secretmanager.secretAccessor", "--condition=None", "--quiet"
) | Out-Null
Write-Host "[OK] secretAccessor -> $RuntimeServiceAccount (secret scope only)"

Write-Host "bootstrap complete. Cloud Run deployment stays a separate, owner-authorized step."
