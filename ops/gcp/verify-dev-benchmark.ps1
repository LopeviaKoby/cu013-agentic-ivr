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
    [string]$ArtifactRepo = "cu013-containers-dev",
    [ValidateSet(0, 1)]
    [int]$ExpectedMinInstances = 1,
    [string]$ExpectedSecretVersion = "",
    [string]$ExpectedImage = "",
    [string]$ExpectedImageDigest = ""
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

function Get-MinInstanceCount {
    param([Parameter(Mandatory)]$Annotations, [Parameter(Mandatory)][string]$Key)

    $property = $Annotations.PSObject.Properties[$Key]
    if ($null -eq $property -or [string]::IsNullOrEmpty([string]$property.Value)) {
        return 0  # Cloud Run's unset minimum defaults to zero.
    }
    $raw = [string]$property.Value
    if ($raw -notmatch '^\d+$') { throw "invalid Cloud Run minimum instance count at $Key" }
    return [int]$raw
}

function Get-PublicServiceUrl {
    param([Parameter(Mandatory)]$ServiceDescription, [Parameter(Mandatory)][string]$Region)

    $urls = @([string]$ServiceDescription.status.url)
    $annotatedUrls = [string]$ServiceDescription.metadata.annotations."run.googleapis.com/urls"
    if (-not [string]::IsNullOrWhiteSpace($annotatedUrls)) {
        try {
            $annotated = ConvertFrom-Json -InputObject $annotatedUrls
            $urls = @($urls + @($annotated))
        }
        catch {
            throw "service URLs annotation is not valid JSON"
        }
    }
    $expected = "https://{0}-{1}.{2}.run.app" -f `
        $ServiceDescription.metadata.name, $ServiceDescription.metadata.namespace, $Region
    if ($urls -contains $expected) {
        return $expected
    }
    return [string]$ServiceDescription.status.url
}

$serviceOutput = @(& gcloud run services describe $Service `
    --project $ProjectId --region $Region `
    --impersonate-service-account $DeployerSa `
    --format=json)
if ($LASTEXITCODE -ne 0) {
    Write-Error "cannot describe service (exit $LASTEXITCODE)"
    exit 1
}
$serviceText = $serviceOutput -join [Environment]::NewLine
if ([string]::IsNullOrWhiteSpace($serviceText)) {
    Write-Error "service describe returned no JSON"
    exit 1
}
$serviceDescription = ConvertFrom-Json -InputObject $serviceText
$template = $serviceDescription.spec.template
$containers = @($template.spec.containers)
if ($containers.Count -ne 1) {
    Write-Error "expected exactly one Cloud Run container, found $($containers.Count)"
    exit 1
}
$container = $containers | Select-Object -First 1
$annotations = $template.metadata.annotations
$serviceUrl = Get-PublicServiceUrl -ServiceDescription $serviceDescription -Region $Region
$expectedServiceUrl = "https://{0}-{1}.{2}.run.app" -f `
    $serviceDescription.metadata.name, $serviceDescription.metadata.namespace, $Region

Check "service_url" ($serviceUrl -eq $expectedServiceUrl) $serviceUrl
Check "region" ($serviceDescription.metadata.labels."cloud.googleapis.com/location" -eq $Region) `
    $serviceDescription.metadata.labels."cloud.googleapis.com/location"
$revisionName = $serviceDescription.status.latestReadyRevisionName
$readyConditions = @($serviceDescription.status.conditions | Where-Object {
    $_.type -eq "Ready" -and $_.status -eq "True"
})
Check "latest_revision_ready" ($readyConditions.Count -gt 0) $revisionName
Check "runtime_sa" ($template.spec.serviceAccountName -eq $RuntimeSa) $template.spec.serviceAccountName
Check "concurrency" ($template.spec.containerConcurrency -eq 1) $template.spec.containerConcurrency
Check "cpu" ($container.resources.limits.cpu -eq "1") $container.resources.limits.cpu
Check "memory" ($container.resources.limits.memory -eq "512Mi") $container.resources.limits.memory
$revisionMin = Get-MinInstanceCount -Annotations $annotations -Key "autoscaling.knative.dev/minScale"
$serviceMin = Get-MinInstanceCount -Annotations $serviceDescription.metadata.annotations -Key "run.googleapis.com/minScale"
$effectiveMin = [Math]::Max($revisionMin, $serviceMin)
Check "min_instances" ($effectiveMin -eq $ExpectedMinInstances) `
    "min=$effectiveMin (revision=$revisionMin service=$serviceMin expected $ExpectedMinInstances)"
Check "max_instances" ([int]$annotations."autoscaling.knative.dev/maxScale" -eq 1) `
    "max=$($annotations."autoscaling.knative.dev/maxScale")"
Check "cpu_throttling" (
    $annotations."run.googleapis.com/cpu-throttling" -eq "true"
) $annotations."run.googleapis.com/cpu-throttling"
$expectedImagePrefix = "us-east1-docker.pkg.dev/$ProjectId/$ArtifactRepo/$Service"
Check "image_prefix" ($container.image.StartsWith($expectedImagePrefix)) $container.image
if (-not [string]::IsNullOrWhiteSpace($ExpectedImage)) {
    Check "image_exact" ($container.image -ceq $ExpectedImage) $container.image
}

$secretRef = $container.env | Where-Object { $_.name -eq "CU013_API_KEY" }
if ($null -ne $secretRef -and $null -ne $secretRef.valueFrom.secretKeyRef) {
    $refName = $secretRef.valueFrom.secretKeyRef.name
    $refVersion = $secretRef.valueFrom.secretKeyRef.key
    $secretMatches = $refName -eq $SecretName
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSecretVersion)) {
        $secretMatches = $secretMatches -and [string]$refVersion -eq $ExpectedSecretVersion
    }
    Check "secret_ref" $secretMatches "secret=$refName version=$refVersion"
}
else {
    Check "secret_ref" $false "CU013_API_KEY env var missing or not backed by Secret Manager"
}

$revisionOutput = @(& gcloud run revisions describe $revisionName `
    --project $ProjectId --region $Region `
    --impersonate-service-account $DeployerSa `
    --format=json)
if ($LASTEXITCODE -ne 0) {
    Write-Error "cannot describe revision (exit $LASTEXITCODE)"
    exit 1
}
$revisionText = $revisionOutput -join [Environment]::NewLine
if ([string]::IsNullOrWhiteSpace($revisionText)) {
    Write-Error "revision describe returned no JSON"
    exit 1
}
$revision = ($revisionText | ConvertFrom-Json)
Check "image_digest" (-not [string]::IsNullOrEmpty($revision.status.imageDigest)) `
    $revision.status.imageDigest
if (-not [string]::IsNullOrWhiteSpace($ExpectedImageDigest)) {
    Check "image_digest_exact" ($revision.status.imageDigest -ceq $ExpectedImageDigest) `
        $revision.status.imageDigest
}

Write-Host "---"
Write-Host "model/location config: defaults baked in the image (project cu013-xcally-agentic,"
Write-Host "location us-east1, model gemini-2.5-flash-lite, thinking_budget=0)"
Write-Host "revision: $revisionName"
Write-Host "url: $serviceUrl"
Write-Host "expected min instances: $ExpectedMinInstances"

if ($Failures.Count -gt 0) {
    Write-Error ("verification failed: {0}" -f ($Failures -join ", "))
    exit 1
}
Write-Host "all checks passed."
