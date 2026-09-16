#requires -Version 5.1
<#
.SYNOPSIS
Builds, pushes and deploys the DEV benchmark revision of the CU013 Cloud Run
service with min-instances=1 for the measurement window.

.NOTES
Run from a clean dev checkout by the owner. Requires, per the runbook:
deployer-SA impersonation rights for the caller, Artifact Registry writer for
the deployer SA, and the api-key Secret Manager secret. Never prints secrets.
Remember to run stop-dev-benchmark.ps1 when the window ends (min=0).
#>
[CmdletBinding()]
param(
    [string]$ProjectId = "cu013-xcally-agentic",
    [string]$Region = "us-east1",
    [string]$Service = "cu013-runtime-dev",
    [string]$RuntimeSa = "cu013-runtime-dev@cu013-xcally-agentic.iam.gserviceaccount.com",
    [string]$DeployerSa = "cu013-deployer-dev@cu013-xcally-agentic.iam.gserviceaccount.com",
    [string]$SecretName = "cu013-api-key-dev",
    [string]$ArtifactRepo = "cu013-containers-dev"
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([scriptblock]$Command, [string]$Step)
    Write-Host "== $Step"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        Write-Error "$Step failed (exit $LASTEXITCODE)"
        exit 1
    }
}

Write-Host "== repository state"
Invoke-Checked { git fetch origin dev } "fetch"
$branch = (git branch --show-current).Trim()
if ($branch -ne "dev") {
    Write-Error "branch is '$branch', expected 'dev'"
    exit 1
}
if (git status --porcelain) {
    Write-Error "worktree is not clean; commit or stash before deploying"
    exit 1
}
$GitSha = (git rev-parse HEAD).Trim()
$RemoteSha = (git rev-parse origin/dev).Trim()
if ($GitSha -ne $RemoteSha) {
    Write-Error "HEAD ($GitSha) != origin/dev ($RemoteSha)"
    exit 1
}
Write-Host "clean HEAD: $GitSha"

Invoke-Checked { docker --version } "docker"
Invoke-Checked { gcloud --version } "gcloud"

$ImageName = "us-east1-docker.pkg.dev/$ProjectId/$ArtifactRepo/$Service"
$Tag = "$ImageName`:$GitSha"

Invoke-Checked {
    gcloud artifacts repositories describe $ArtifactRepo `
        --location $Region --project $ProjectId | Out-Null
} "artifact registry"

Invoke-Checked {
    gcloud secrets describe $SecretName --project $ProjectId | Out-Null
} "secret exists"
$enabledVersions = gcloud secrets versions list $SecretName --project $ProjectId `
    --filter="state=ENABLED" --format="value(name)"
if ($LASTEXITCODE -ne 0) {
    Write-Error "cannot list secret versions"
    exit 1
}
$numericVersions = $enabledVersions | Where-Object { $_ -match '^\d+$' }
if (-not $numericVersions) {
    Write-Error "no enabled numeric version of secret $SecretName"
    exit 1
}
$Version = $numericVersions | Sort-Object { [int]$_ } -Descending | Select-Object -First 1
Write-Host "secret: $SecretName (latest enabled version: $Version; value never printed)"

Invoke-Checked { docker build -t $Tag . } "docker build"

Write-Host "== docker login (impersonated deployer token; token never printed)"
$token = gcloud auth print-access-token --impersonate-service-account $DeployerSa
if ($LASTEXITCODE -ne 0) {
    Write-Error "cannot impersonate $DeployerSa; grant iam.serviceAccounts.getAccessToken first"
    exit 1
}
$token | docker login -u oauth2accesstoken --password-stdin us-east1-docker.pkg.dev | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker login failed"
    exit 1
}

Invoke-Checked { docker push $Tag } "docker push"

Invoke-Checked {
    gcloud run deploy $Service `
        --project $ProjectId --region $Region `
        --image $Tag `
        --service-account $RuntimeSa `
        --cpu 1 --memory 512Mi `
        --concurrency 1 --max-instances 1 --min-instances 1 `
        --cpu-throttling --no-cpu-boost `
        --allow-unauthenticated `
        --set-secrets "CU013_API_KEY=${SecretName}:${Version}" `
        --impersonate-service-account $DeployerSa
} "cloud run deploy (min-instances=1 for the benchmark window)"

Write-Host "== effective configuration"
$serviceJson = gcloud run services describe $Service `
    --project $ProjectId --region $Region --format=json
$service = $serviceJson | ConvertFrom-Json
$digest = gcloud artifacts docker images describe $Tag --format="value(image_summary.digest)"
Write-Host "url: $($service.status.url)"
Write-Host "revision: $($service.status.latestReadyRevisionName)"
Write-Host "image: $Tag"
Write-Host "image digest: $digest"
Write-Host "min instances: $($service.spec.template.scaling.minInstanceCount)"
Write-Host "REMINDER: run ops/gcp/stop-dev-benchmark.ps1 right after the window (min=0)."
