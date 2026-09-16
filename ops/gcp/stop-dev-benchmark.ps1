#requires -Version 5.1
<#
.SYNOPSIS
Restores the Cloud Run DEV service to the safe idle state: min-instances=0.
The service itself is kept deployed. Safe to run repeatedly.
#>
[CmdletBinding()]
param(
    [string]$ProjectId = "cu013-xcally-agentic",
    [string]$Region = "us-east1",
    [string]$Service = "cu013-runtime-dev",
    [string]$DeployerSa = "cu013-deployer-dev@cu013-xcally-agentic.iam.gserviceaccount.com"
)

$ErrorActionPreference = "Stop"

Write-Host "== cloud run min-instances=0"
gcloud run services update $Service `
    --project $ProjectId --region $Region `
    --min-instances 0 `
    --impersonate-service-account $DeployerSa
if ($LASTEXITCODE -ne 0) {
    Write-Error "update failed (exit $LASTEXITCODE)"
    exit 1
}

Write-Host "== read-only verification"
$serviceJson = gcloud run services describe $Service `
    --project $ProjectId --region $Region --format=json
$service = $serviceJson | ConvertFrom-Json
$min = $service.spec.template.scaling.minInstanceCount
Write-Host "min instances: $min"
if ($min -ne 0) {
    Write-Error "min instances is $min, expected 0"
    exit 1
}
Write-Host "service kept deployed with min=0 (safe idle state)."
