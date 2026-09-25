#requires -Version 5.1
<#
.SYNOPSIS
Read-only verification of the current TIVIT DEV environment (tivit-cu013-prd).

.NOTES
Checks the configuration, project identity, enabled APIs, Firestore, Artifact
Registry, the runtime service account and its project roles, the API-key
secret and the Cloud Run service. It never mutates anything and never
impersonates another identity.
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
    [string]$Service = "cu013-runtime-dev"
)

$ErrorActionPreference = "Stop"
$script:Failed = $false

function Write-Pass { param([string]$Message) Write-Host "[PASS] $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Write-Fail { param([string]$Message) Write-Host "[FAIL] $Message" -ForegroundColor Red; $script:Failed = $true }

function Invoke-GcloudJson {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $lines = @(& gcloud @Arguments "--format=json" 2>&1)
    if ($LASTEXITCODE -ne 0) { return $null }
    $text = $lines -join [Environment]::NewLine
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }
    return ConvertFrom-Json -InputObject $text
}

$RequiredApis = @(
    "aiplatform.googleapis.com", "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com", "firestore.googleapis.com",
    "iam.googleapis.com", "iamcredentials.googleapis.com",
    "logging.googleapis.com", "monitoring.googleapis.com",
    "pubsub.googleapis.com", "run.googleapis.com",
    "secretmanager.googleapis.com", "storage.googleapis.com"
)

Write-Host "== configuration"
$configuration = Invoke-GcloudJson -Arguments @(
    "config", "configurations", "describe", $ConfigurationName, "--all"
)
if ($null -eq $configuration) {
    Write-Fail "configuration $ConfigurationName is missing"
} else {
    if ($configuration.properties.core.project -ne $ProjectId) {
        Write-Fail "core/project is not $ProjectId"
    }
    if ($configuration.properties.core.account -ne $Account) {
        Write-Fail "core/account is not $Account"
    }
    if ($configuration.properties.run.region -ne $Region) {
        Write-Fail "run/region is not $Region"
    }
    Write-Pass "configuration"
}

Write-Host "== project identity"
$project = Invoke-GcloudJson -Arguments @(
    "projects", "describe", $ProjectId, "--configuration=$ConfigurationName"
)
if ($null -eq $project) {
    Write-Fail "cannot describe $ProjectId"
} else {
    if ([string]$project.projectNumber -ne $ProjectNumber) {
        Write-Fail "project number is $($project.projectNumber); expected $ProjectNumber"
    }
    if ($project.parent.type -ne "organization" -or [string]$project.parent.id -ne $OrganizationId) {
        Write-Fail "project organization is not $OrganizationId"
    }
    Write-Pass "project"
}

Write-Host "== enabled APIs"
$enabledApis = @((Invoke-GcloudJson -Arguments @(
            "services", "list", "--enabled", "--project=$ProjectId",
            "--configuration=$ConfigurationName"
        )) | ForEach-Object { $_.config.name })
foreach ($api in $RequiredApis) {
    if ($enabledApis -contains $api) { Write-Pass "api $api" } else { Write-Fail "api $api is not enabled" }
}

Write-Host "== Firestore"
$databases = Invoke-GcloudJson -Arguments @(
    "firestore", "databases", "list", "--project=$ProjectId",
    "--configuration=$ConfigurationName"
)
if (@($databases).Count -ge 1) { Write-Pass "Firestore (default) present" } else { Write-Fail "Firestore (default) is missing" }

Write-Host "== Artifact Registry"
$repositories = @((Invoke-GcloudJson -Arguments @(
            "artifacts", "repositories", "list", "--location=$Region",
            "--project=$ProjectId", "--configuration=$ConfigurationName"
        )) | ForEach-Object { $_.name })
if ($repositories -contains $ArtifactRepository) {
    Write-Pass "Artifact Registry $ArtifactRepository"
} else {
    Write-Warn "Artifact Registry $ArtifactRepository is not created yet (prepared, not executed)"
}

Write-Host "== runtime service account"
$serviceAccounts = @((Invoke-GcloudJson -Arguments @(
            "iam", "service-accounts", "list", "--project=$ProjectId",
            "--configuration=$ConfigurationName"
        )) | ForEach-Object { $_.email })
if ($serviceAccounts -contains $RuntimeServiceAccount) {
    Write-Pass "runtime SA"
} else {
    Write-Fail "runtime SA $RuntimeServiceAccount is missing"
}

Write-Host "== project IAM for the runtime SA"
$policy = Invoke-GcloudJson -Arguments @(
    "projects", "get-iam-policy", $ProjectId, "--configuration=$ConfigurationName"
)
$expectedRoles = @("roles/datastore.user", "roles/aiplatform.user")
foreach ($role in $expectedRoles) {
    $binding = @($policy.bindings | Where-Object { $_.role -eq $role })
    $member = "serviceAccount:$RuntimeServiceAccount"
    $found = $false
    foreach ($item in $binding) { if (@($item.members) -contains $member) { $found = $true } }
    if ($found) { Write-Pass "$role -> runtime SA" } else { Write-Warn "$role -> runtime SA not visible" }
}

Write-Host "== API-key secret"
$secrets = @((Invoke-GcloudJson -Arguments @(
            "secrets", "list", "--project=$ProjectId",
            "--configuration=$ConfigurationName"
        )) | ForEach-Object { $_.name })
if ($secrets -contains $SecretName) {
    Write-Pass "secret $SecretName"
} else {
    Write-Warn "secret $SecretName is not created yet (prepared, not executed)"
}

Write-Host "== Cloud Run service"
$service = Invoke-GcloudJson -Arguments @(
    "run", "services", "describe", $Service,
    "--project=$ProjectId", "--region=$Region", "--configuration=$ConfigurationName"
)
if ($null -eq $service) {
    Write-Warn "Cloud Run service $Service is not deployed yet (prepared, not executed)"
} else {
    $minScale = $service.spec.template.metadata.annotations.'autoscaling.knative.dev/minScale'
    Write-Pass "Cloud Run $Service present (minScale=$minScale)"
}

if ($script:Failed) {
    Write-Host "verification failed."
    exit 1
}
Write-Host "all checks passed."
