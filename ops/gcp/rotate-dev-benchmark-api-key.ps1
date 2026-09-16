#requires -Version 5.1
<#
.SYNOPSIS
Adds a valid API-key version to the DEV secret and points Cloud Run at it.

.NOTES
Owner-run only. Creates a 44-character base64 key from 32 random bytes.
Writes exact bytes to a temporary file for gcloud, then removes that file.
Never prints the key. The active gcloud account adds the secret version;
the deployer service account updates Cloud Run.
#>
[CmdletBinding()]
param(
    [string]$ProjectId = "cu013-xcally-agentic",
    [string]$Region = "us-east1",
    [string]$Service = "cu013-runtime-dev",
    [string]$SecretName = "cu013-api-key-dev",
    [string]$DeployerSa = "cu013-deployer-dev@cu013-xcally-agentic.iam.gserviceaccount.com",
    [string]$ExpectedImage = "us-east1-docker.pkg.dev/cu013-xcally-agentic/cu013-containers-dev/cu013-runtime-dev:a17e15545542e438a218538bf6e10745b88a0af8",
    [string]$ExpectedImageDigest = "us-east1-docker.pkg.dev/cu013-xcally-agentic/cu013-containers-dev/cu013-runtime-dev@sha256:4dffcd59001312396912e4cac1c739e1c11d45ca8ff4a77185b3d046312b902a"
)

$ErrorActionPreference = "Stop"

function Get-GcloudJson {
    param([Parameter(Mandatory)][string[]]$CommandArguments)

    $lines = @(& gcloud @CommandArguments "--format=json")
    if ($LASTEXITCODE -ne 0) { throw "gcloud query failed (exit $LASTEXITCODE)" }
    $jsonText = $lines -join [Environment]::NewLine
    if ([string]::IsNullOrWhiteSpace($jsonText)) { throw "gcloud query returned no JSON" }
    return ConvertFrom-Json -InputObject $jsonText
}

Write-Host "== read-only preflight"
$serviceDescription = Get-GcloudJson -CommandArguments @(
    "run", "services", "describe", $Service,
    "--project", $ProjectId, "--region", $Region,
    "--impersonate-service-account", $DeployerSa
)
$containers = @($serviceDescription.spec.template.spec.containers)
if ($containers.Count -ne 1 -or $containers[0].image -cne $ExpectedImage) {
    throw "Cloud Run image or container count differs from the expected benchmark revision"
}
$currentRef = @($containers[0].env | Where-Object { $_.name -eq "CU013_API_KEY" })
if ($currentRef.Count -ne 1 -or
    $currentRef[0].valueFrom.secretKeyRef.name -ne $SecretName -or
    [string]$currentRef[0].valueFrom.secretKeyRef.key -ne "1") {
    throw "Cloud Run is not pinned to the expected secret version 1"
}
$minInstances = [string]$serviceDescription.spec.template.metadata.annotations."autoscaling.knative.dev/minScale"
if ($minInstances -ne "0") {
    throw "Cloud Run must be idle (min-instances=0) before rotating the benchmark key"
}
$revisionName = [string]$serviceDescription.status.latestReadyRevisionName
$currentRevision = Get-GcloudJson -CommandArguments @(
    "run", "revisions", "describe", $revisionName,
    "--project", $ProjectId, "--region", $Region,
    "--impersonate-service-account", $DeployerSa
)
if ($currentRevision.status.imageDigest -cne $ExpectedImageDigest) {
    throw "Cloud Run image digest differs from the expected benchmark image"
}
$existingVersions = @(
    Get-GcloudJson -CommandArguments @(
        "secrets", "versions", "list", $SecretName, "--project", $ProjectId
    )
)
if ($existingVersions.Count -ne 1 -or
    [string]$existingVersions[0].name -notmatch "/versions/1$") {
    throw "unexpected secret version inventory; inspect it before adding another version"
}
Write-Host "preflight passed: expected image, secret version 1, min=0"

$randomBytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($randomBytes) } finally { $rng.Dispose() }
$apiKey = [Convert]::ToBase64String($randomBytes)
$keyBytes = [Text.Encoding]::ASCII.GetBytes($apiKey)
if ($apiKey.Length -ne 44 -or $apiKey.IndexOfAny([char[]]@(0, 10, 13)) -ge 0) {
    throw "generated key is not a valid 44-character HTTP header value"
}

$temporaryFile = [IO.Path]::GetTempFileName()
try {
    [IO.File]::WriteAllBytes($temporaryFile, $keyBytes)
    $versionDescription = Get-GcloudJson -CommandArguments @(
        "secrets", "versions", "add", $SecretName,
        "--data-file=$temporaryFile", "--project", $ProjectId
    )
    $versionName = [string]$versionDescription.name
    if ($versionName -notmatch "/versions/([1-9][0-9]*)$") {
        throw "new secret version was created, but its numeric ID could not be read"
    }
    $newVersion = $Matches[1]
    Write-Host "created secret version $newVersion (value not printed)"

    $accessArguments = @(
        "secrets", "versions", "access", $newVersion,
        "--secret", $SecretName, "--project", $ProjectId,
        "--impersonate-service-account", $DeployerSa,
        "--format=get(payload.data)"
    )
    $encodedLines = @(& gcloud @accessArguments)
    if ($LASTEXITCODE -ne 0) {
        throw "new secret version could not be read back (exit $LASTEXITCODE)"
    }
    $urlSafeBase64 = ($encodedLines -join "").Trim()
    $base64 = $urlSafeBase64.Replace("-", "+").Replace("_", "/")
    $base64 = $base64.PadRight($base64.Length + ((4 - ($base64.Length % 4)) % 4), "=")
    $readBackBytes = [Convert]::FromBase64String($base64)
    if ([Convert]::ToBase64String($readBackBytes) -cne [Convert]::ToBase64String($keyBytes)) {
        throw "new secret version does not match the generated bytes"
    }
    Write-Host "secret version byte-for-byte verification passed"
}
finally {
    if (Test-Path -LiteralPath $temporaryFile) {
        Remove-Item -LiteralPath $temporaryFile -Force
    }
    [Array]::Clear($randomBytes, 0, $randomBytes.Length)
    [Array]::Clear($keyBytes, 0, $keyBytes.Length)
    if ($null -ne $readBackBytes) {
        [Array]::Clear($readBackBytes, 0, $readBackBytes.Length)
    }
    $apiKey = $null
}

Write-Host "== update existing Cloud Run image secret reference and warm minimum"
$secretBinding = "CU013_API_KEY={0}:{1}" -f $SecretName, $newVersion
$updateArguments = @(
    "run", "services", "update", $Service,
    "--project", $ProjectId, "--region", $Region,
    "--update-secrets", $secretBinding, "--min-instances", "1",
    "--impersonate-service-account", $DeployerSa
)
& gcloud @updateArguments | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Cloud Run update failed; secret version $newVersion exists but is not confirmed active"
}

$verifier = Join-Path $PSScriptRoot "verify-dev-benchmark.ps1"
& $verifier -ProjectId $ProjectId -Region $Region -Service $Service -DeployerSa $DeployerSa -SecretName $SecretName -ExpectedMinInstances 1 -ExpectedSecretVersion $newVersion -ExpectedImage $ExpectedImage -ExpectedImageDigest $ExpectedImageDigest
if ($LASTEXITCODE -ne 0) {
    throw "post-update verification failed; run stop-dev-benchmark.ps1 before continuing"
}
Write-Host "new secret version: $newVersion"
Write-Host "REMINDER: run stop-dev-benchmark.ps1 after the benchmark window."
