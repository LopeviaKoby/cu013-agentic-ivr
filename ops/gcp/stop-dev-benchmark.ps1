#requires -Version 5.1
<#
.SYNOPSIS
Restores the Cloud Run DEV service to the safe idle state: min-instances=0.
The service itself is kept deployed. Safe to run repeatedly.
#>
[CmdletBinding()]
param(
    [string]$ProjectId = "tivit-cu013-prd",
    [string]$Region = "us-east1",
    [string]$Service = "cu013-runtime-dev"
)

$ErrorActionPreference = "Stop"

Write-Host "== cloud run min-instances=0"
gcloud run services update $Service `
    --project $ProjectId --region $Region `
    --min-instances 0
if ($LASTEXITCODE -ne 0) {
    Write-Error "update failed (exit $LASTEXITCODE)"
    exit 1
}

Write-Host "== read-only verification"
$verifier = Join-Path $PSScriptRoot "verify-dev-benchmark.ps1"
& $verifier `
    -ProjectId $ProjectId `
    -Region $Region `
    -Service $Service `
    -ExpectedMinInstances 0
if ($LASTEXITCODE -ne 0) {
    Write-Error "post-stop verification failed (exit $LASTEXITCODE)"
    exit 1
}
Write-Host "service kept deployed with min=0 (safe idle state)."
