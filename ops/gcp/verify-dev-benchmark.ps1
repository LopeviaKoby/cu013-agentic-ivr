#requires -Version 5.1
<#
.SYNOPSIS
Read-only verification of the deployed Cloud Run DEV benchmark service.
Never prints secret values: Secret Manager references are shown by name and
numeric version only.
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

$Failures = @()

function Check {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    if ($Ok) {
        Write-Host ("PASS {0}: {1}" -f $Name, $Detail)
    }
    else {
        Write-Host ("FAIL {0}: {1}" -f $Name, $Detail)
        $script:Failures += $Name
    }
}

$serviceJson = gcloud run services describe $Service `
    --project $ProjectId --region $Region `
    --impersonate-service-account $DeployerSa `
    --format=json
if ($LASTEXITCODE -ne 0) {
    Write-Error "cannot describe service (exit $LASTEXITCODE)"
    exit 1
}
$service = $serviceJson | ConvertFrom-Json
$template = $service.spec.template
$container = $template.spec.containers[0]

Check "service_url" ($service.status.url -like "https://*") $service.status.url
Check "region" ($service.metadata.labels."cloud.googleapis.com/location" -eq $Region) `
    $service.metadata.labels."cloud.googleapis.com/location"
$revisionName = $service.status.latestReadyRevisionName
Check "latest_revision_ready" ($service.status.conditions | Where-Object { $_.type -eq "Ready" -and $_.status -eq "True" }) `
    $revisionName
Check "runtime_sa" ($template.spec.serviceAccountName -eq $RuntimeSa) $template.spec.serviceAccountName
Check "concurrency" ($template.spec.containerConcurrency -eq 1) $template.spec.containerConcurrency
Check "cpu" ($container.resources.limits.cpu -eq "1") $container.resources.limits.cpu
Check "memory" ($container.resources.limits.memory -eq "512Mi") $container.resources.limits.memory
Check "min_instances" ($template.scaling.minInstanceCount -eq 0) `
    "min=$($template.scaling.minInstanceCount) (expected 0 in idle state)"
Check "max_instances" ($template.scaling.maxInstanceCount -eq 1) `
    "max=$($template.scaling.maxInstanceCount)"
Check "cpu_throttling" (
    $template.metadata.annotations."run.googleapis.com/cpu-throttling" -eq "true"
) $template.metadata.annotations."run.googleapis.com/cpu-throttling"
$expectedImagePrefix = "us-east1-docker.pkg.dev/$ProjectId/$ArtifactRepo/$Service"
Check "image_prefix" ($container.image.StartsWith($expectedImagePrefix)) $container.image

$secretRef = $container.env | Where-Object { $_.name -eq "CU013_API_KEY" }
if ($null -ne $secretRef -and $null -ne $secretRef.valueFrom.secretKeyRef) {
    $refName = $secretRef.valueFrom.secretKeyRef.name
    $refVersion = $secretRef.valueFrom.secretKeyRef.version
    Check "secret_ref" ($refName -eq $SecretName) "secret=$refName version=$refVersion"
}
else {
    Check "secret_ref" $false "CU013_API_KEY env var missing or not backed by Secret Manager"
}

$revisionJson = gcloud run revisions describe $revisionName `
    --project $ProjectId --region $Region `
    --impersonate-service-account $DeployerSa `
    --format=json
$revision = $revisionJson | ConvertFrom-Json
Check "image_digest" (-not [string]::IsNullOrEmpty($revision.status.imageDigest)) `
    $revision.status.imageDigest

Write-Host "---"
Write-Host "model/location config: defaults baked in the image (project cu013-xcally-agentic,"
Write-Host "location us-east1, model gemini-2.5-flash-lite, thinking_budget=0)"
Write-Host "revision: $revisionName"
Write-Host "url: $($service.status.url)"

if ($Failures.Count -gt 0) {
    Write-Error ("verification failed: {0}" -f ($Failures -join ", "))
    exit 1
}
Write-Host "all checks passed."
