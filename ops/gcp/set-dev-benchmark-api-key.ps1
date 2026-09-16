#requires -Version 5.1
<#
.SYNOPSIS
Loads the fixed DEV benchmark API-key secret into the current PowerShell
process without printing or persisting its value.

.NOTES
Dot-source this script so CU013_API_KEY is available to the benchmark client:
  . .\ops\gcp\set-dev-benchmark-api-key.ps1
The secret remains only in the current shell and must be removed after use.
#>
[CmdletBinding()]
param(
    [string]$ProjectId = "cu013-xcally-agentic",
    [string]$SecretName = "cu013-api-key-dev",
    [ValidatePattern("^\d+$")]
    [string]$SecretVersion = "1",
    [string]$DeployerSa = "cu013-deployer-dev@cu013-xcally-agentic.iam.gserviceaccount.com"
)

$ErrorActionPreference = "Stop"

$encodedLines = @(& gcloud secrets versions access $SecretVersion `
    --secret $SecretName `
    --project $ProjectId `
    --impersonate-service-account $DeployerSa `
    --format="get(payload.data)")
if ($LASTEXITCODE -ne 0) {
    throw "cannot access secret version metadata and payload (exit $LASTEXITCODE)"
}

$urlSafeBase64 = ($encodedLines -join "").Trim()
if ([string]::IsNullOrWhiteSpace($urlSafeBase64)) {
    throw "secret payload was empty"
}
$base64 = $urlSafeBase64.Replace("-", "+").Replace("_", "/")
$base64 = $base64.PadRight($base64.Length + ((4 - ($base64.Length % 4)) % 4), "=")

try {
    $secretBytes = [Convert]::FromBase64String($base64)
    $apiKey = [Text.Encoding]::UTF8.GetString($secretBytes)
}
catch {
    throw "secret payload was not valid UTF-8 base64 data"
}

if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "secret payload was empty"
}
if ($apiKey.IndexOfAny([char[]]@(0, 10, 13)) -ge 0) {
    Remove-Item Env:CU013_API_KEY -ErrorAction SilentlyContinue
    throw "secret version $SecretVersion contains NUL, CR or LF and cannot be used as an HTTP header"
}

Set-Item -LiteralPath "Env:CU013_API_KEY" -Value $apiKey
$apiKey = $null
$secretBytes = $null
Write-Host "CU013_API_KEY loaded into the current PowerShell process; value not printed."
