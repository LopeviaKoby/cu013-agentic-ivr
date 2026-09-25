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
    [string]$ProjectId = "tivit-cu013-prd",
    [string]$Region = "us-east1",
    [string]$Service = "cu013-runtime-dev",
    [string]$RuntimeSa = "cu013-cloud-run-sa@tivit-cu013-prd.iam.gserviceaccount.com",
    [string]$SecretName = "cu013-api-key-dev",
    [string]$ArtifactRepo = "cu013-containers-dev",
    # Closed allow-list: deployments never accept an arbitrary branch.
    [string[]]$AllowedBranches = @("dev")
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

Write-Host "== repository state"
Invoke-Checked { git fetch origin dev } "fetch"
$branch = (git branch --show-current).Trim()
if ($AllowedBranches -notcontains $branch) {
    Write-Error "branch is '$branch'; allowed: $($AllowedBranches -join ', ')"
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

Write-Host "== docker login (active-account token; never printed)"
$token = gcloud auth print-access-token
if ($LASTEXITCODE -ne 0) {
    Write-Error "cannot obtain an access token for the active account"
    exit 1
}
$token | docker login -u oauth2accesstoken --password-stdin us-east1-docker.pkg.dev | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker login failed"
    exit 1
}

Invoke-Checked { docker push $Tag } "docker push"

# DRS risk: if --allow-unauthenticated fails under
# iam.allowedPolicyMemberDomains, STOP & REPORT — DRS OWNER DECISION REQUIRED
# (folder/project exception or authenticated OIDC invocation); never improvise
# a proxy or a different identity.
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
} "cloud run deploy (min-instances=1 for the benchmark window)"

Write-Host "== effective configuration"
$serviceOutput = @(& gcloud run services describe $Service `
    --project $ProjectId --region $Region `
    --format=json)
if ($LASTEXITCODE -ne 0) {
    Write-Error "cannot describe deployed service (exit $LASTEXITCODE)"
    exit 1
}
$serviceText = $serviceOutput -join [Environment]::NewLine
if ([string]::IsNullOrWhiteSpace($serviceText)) {
    Write-Error "deployed service describe returned no JSON"
    exit 1
}
$serviceDescription = (ConvertFrom-Json -InputObject $serviceText)
$url = Get-PublicServiceUrl -ServiceDescription $serviceDescription -Region $Region
$revision = [string]$serviceDescription.status.latestReadyRevisionName
$minInstances = [string]$serviceDescription.spec.template.metadata.annotations."autoscaling.knative.dev/minScale"
if ([string]::IsNullOrWhiteSpace($url) -or [string]::IsNullOrWhiteSpace($revision)) {
    Write-Error "deployed service did not report a ready URL and revision"
    exit 1
}
$revisionOutput = @(& gcloud run revisions describe $revision `
    --project $ProjectId --region $Region `
    --format=json)
if ($LASTEXITCODE -ne 0) {
    Write-Error "cannot describe deployed revision (exit $LASTEXITCODE)"
    exit 1
}
$revisionText = $revisionOutput -join [Environment]::NewLine
if ([string]::IsNullOrWhiteSpace($revisionText)) {
    Write-Error "deployed revision describe returned no JSON"
    exit 1
}
$revisionDetails = ($revisionText | ConvertFrom-Json)
$digest = [string]$revisionDetails.status.imageDigest
Write-Host "url: $url"
Write-Host "revision: $revision"
Write-Host "image: $Tag"
Write-Host "image digest: $digest"
Write-Host "min instances: $minInstances"
Write-Host "REMINDER: run ops/gcp/stop-dev-benchmark.ps1 right after the window (min=0)."
