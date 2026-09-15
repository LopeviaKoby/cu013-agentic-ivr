Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectId = "cu013-xcally-agentic"
$ProjectNumber = "17280606194"
$OrganizationId = "268452702158"
$Region = "us-east1"
$ConfigurationName = "cu013-xcally-agentic"
$BootstrapUser = "ylopevia@gmail.com"
$ArtifactRepository = "cu013-containers-dev"

$SpikeServiceAccount = "cu013-spike-firestore@$ProjectId.iam.gserviceaccount.com"
$RuntimeServiceAccount = "cu013-runtime-dev@$ProjectId.iam.gserviceaccount.com"
$DeployerServiceAccount = "cu013-deployer-dev@$ProjectId.iam.gserviceaccount.com"

$RequiredApis = @(
    "aiplatform.googleapis.com"
    "artifactregistry.googleapis.com"
    "firestore.googleapis.com"
    "iam.googleapis.com"
    "iamcredentials.googleapis.com"
    "run.googleapis.com"
    "secretmanager.googleapis.com"
)

$script:FailureCount = 0

function Write-Pass {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Write-WarningResult {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Failure {
    param([Parameter(Mandatory)][string]$Message)
    $script:FailureCount++
    Write-Host "[FAIL] $Message" -ForegroundColor Red
}

function Invoke-GcloudJson {
    param([Parameter(Mandatory)][string[]]$Arguments)

    # Keep stderr separate so gcloud warnings never contaminate structured stdout.
    $output = @(& gcloud @Arguments "--format=json")
    $exitCode = $LASTEXITCODE
    $text = $output -join [Environment]::NewLine
    if ($exitCode -ne 0) {
        throw "Read-only gcloud query failed with exit code ${exitCode}: gcloud $($Arguments -join ' ')"
    }
    if ([string]::IsNullOrWhiteSpace($text)) {
        return [pscustomobject]@{ Data = @() }
    }
    return [pscustomobject]@{ Data = ($text | ConvertFrom-Json) }
}

function Get-NestedConfigValue {
    param(
        [Parameter(Mandatory)][System.Collections.IDictionary]$Configuration,
        [Parameter(Mandatory)][string]$Section,
        [Parameter(Mandatory)][string]$Name
    )

    if (-not $Configuration.Contains("properties")) { return $null }
    $properties = $Configuration["properties"]
    if (-not $properties.Contains($Section)) { return $null }
    $sectionProperties = $properties[$Section]
    if (-not $sectionProperties.Contains($Name)) { return $null }
    return [string]$sectionProperties[$Name]
}

function Test-IamBinding {
    param(
        [Parameter(Mandatory)]$Policy,
        [Parameter(Mandatory)][string]$Role,
        [Parameter(Mandatory)][string]$Member
    )

    $bindings = if ($Policy.PSObject.Properties.Name -contains "bindings") { @($Policy.bindings) } else { @() }
    foreach ($binding in $bindings) {
        $hasCondition = $binding.PSObject.Properties.Name -contains "condition" -and $null -ne $binding.condition
        if ($binding.role -eq $Role -and @($binding.members) -contains $Member -and -not $hasCondition) {
            return $true
        }
    }
    return $false
}

function Test-ExpectedBindings {
    param(
        [Parameter(Mandatory)]$Policy,
        [Parameter(Mandatory)][hashtable[]]$ExpectedBindings
    )

    $allPresent = $true
    foreach ($expected in $ExpectedBindings) {
        if (-not (Test-IamBinding -Policy $Policy -Role $expected.Role -Member $expected.Member)) {
            Write-Failure "Missing unconditional IAM binding $($expected.Role) -> $($expected.Member)"
            $allPresent = $false
        }
    }
    return $allPresent
}

function Write-RelatedExtras {
    param(
        [Parameter(Mandatory)]$Policy,
        [Parameter(Mandatory)][string[]]$RelatedMembers,
        [Parameter(Mandatory)][hashtable[]]$ExpectedBindings,
        [Parameter(Mandatory)][string]$ScopeName
    )

    $bindings = if ($Policy.PSObject.Properties.Name -contains "bindings") { @($Policy.bindings) } else { @() }
    foreach ($binding in $bindings) {
        foreach ($member in @($binding.members)) {
            if ($member -notin $RelatedMembers) { continue }
            $expected = $ExpectedBindings | Where-Object {
                $_.Role -eq $binding.role -and $_.Member -eq $member
            }
            if (-not $expected) {
                Write-WarningResult "Additional related binding at ${ScopeName}: $($binding.role) -> $member"
            }
        }
    }
}

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Failure "Google Cloud SDK (gcloud) is not installed."
    exit 1
}

try {
    $configurationRaw = (Invoke-GcloudJson -Arguments @(
        "config", "configurations", "describe", $ConfigurationName, "--all"
    )).Data | ConvertTo-Json -Depth 20
    $configuration = $configurationRaw | ConvertFrom-Json -AsHashtable

    $configurationChecks = @(
        @{ Section = "core"; Name = "account"; Expected = $BootstrapUser }
        @{ Section = "core"; Name = "project"; Expected = $ProjectId }
        @{ Section = "compute"; Name = "region"; Expected = $Region }
        @{ Section = "run"; Name = "region"; Expected = $Region }
        @{ Section = "artifacts"; Name = "location"; Expected = $Region }
    )
    $configurationValid = $true
    foreach ($check in $configurationChecks) {
        $actual = Get-NestedConfigValue $configuration $check.Section $check.Name
        if ($actual -ne $check.Expected) {
            Write-Failure "Configuration $($check.Section)/$($check.Name) is '$actual'; expected '$($check.Expected)'."
            $configurationValid = $false
        }
    }

    $project = (Invoke-GcloudJson -Arguments @(
        "projects", "describe", $ProjectId, "--configuration=$ConfigurationName"
    )).Data
    if ([string]$project.projectNumber -ne $ProjectNumber) {
        Write-Failure "Project number is $($project.projectNumber); expected $ProjectNumber."
        $configurationValid = $false
    }
    if ($project.parent.type -ne "organization" -or [string]$project.parent.id -ne $OrganizationId) {
        Write-Failure "Project organization is not $OrganizationId."
        $configurationValid = $false
    }
    if ($configurationValid) { Write-Pass "Project/configuration" }

    $enabledApis = @((Invoke-GcloudJson -Arguments @(
        "services", "list", "--enabled", "--project=$ProjectId",
        "--configuration=$ConfigurationName"
    )).Data | ForEach-Object { $_.config.name })
    $missingApis = @($RequiredApis | Where-Object { $_ -notin $enabledApis })
    if ($missingApis.Count -eq 0) {
        Write-Pass "Required APIs"
    } else {
        Write-Failure "Missing APIs: $($missingApis -join ', ')"
    }

    $firestore = (Invoke-GcloudJson -Arguments @(
        "firestore", "databases", "describe", "--database=(default)",
        "--project=$ProjectId", "--configuration=$ConfigurationName"
    )).Data
    if ($firestore.locationId -eq $Region -and $firestore.type -eq "FIRESTORE_NATIVE" -and $firestore.databaseEdition -eq "STANDARD") {
        Write-Pass "Firestore"
    } else {
        Write-Failure "Firestore (default) must be Native/Standard in $Region."
    }

    $repository = (Invoke-GcloudJson -Arguments @(
        "artifacts", "repositories", "describe", $ArtifactRepository,
        "--location=$Region", "--project=$ProjectId",
        "--configuration=$ConfigurationName"
    )).Data
    $expectedRepositoryName = "projects/$ProjectId/locations/$Region/repositories/$ArtifactRepository"
    if ($repository.name -eq $expectedRepositoryName -and $repository.format -eq "DOCKER" -and $repository.mode -eq "STANDARD_REPOSITORY") {
        Write-Pass "Artifact Registry"
    } else {
        Write-Failure "Artifact Registry repository has incompatible name, location, format, or mode."
    }

    $serviceAccounts = @((Invoke-GcloudJson -Arguments @(
        "iam", "service-accounts", "list", "--project=$ProjectId",
        "--configuration=$ConfigurationName"
    )).Data | ForEach-Object { $_.email })
    if ($SpikeServiceAccount -in $serviceAccounts) { Write-Pass "Spike SA" } else { Write-Failure "Spike SA is missing." }
    if ($RuntimeServiceAccount -in $serviceAccounts) { Write-Pass "Runtime SA" } else { Write-Failure "Runtime SA is missing." }
    if ($DeployerServiceAccount -in $serviceAccounts) { Write-Pass "Deployer SA" } else { Write-Failure "Deployer SA is missing." }

    $projectPolicy = (Invoke-GcloudJson -Arguments @(
        "projects", "get-iam-policy", $ProjectId,
        "--configuration=$ConfigurationName"
    )).Data
    $repositoryPolicy = (Invoke-GcloudJson -Arguments @(
        "artifacts", "repositories", "get-iam-policy", $ArtifactRepository,
        "--location=$Region", "--project=$ProjectId",
        "--configuration=$ConfigurationName"
    )).Data
    $spikePolicy = (Invoke-GcloudJson -Arguments @(
        "iam", "service-accounts", "get-iam-policy", $SpikeServiceAccount,
        "--project=$ProjectId", "--configuration=$ConfigurationName"
    )).Data
    $runtimePolicy = (Invoke-GcloudJson -Arguments @(
        "iam", "service-accounts", "get-iam-policy", $RuntimeServiceAccount,
        "--project=$ProjectId", "--configuration=$ConfigurationName"
    )).Data

    $projectExpected = @(
        @{ Role = "roles/datastore.user"; Member = "serviceAccount:$SpikeServiceAccount" }
        @{ Role = "roles/datastore.user"; Member = "serviceAccount:$RuntimeServiceAccount" }
        @{ Role = "roles/aiplatform.user"; Member = "serviceAccount:$RuntimeServiceAccount" }
        @{ Role = "roles/run.developer"; Member = "serviceAccount:$DeployerServiceAccount" }
    )
    $repositoryExpected = @(
        @{ Role = "roles/artifactregistry.writer"; Member = "serviceAccount:$DeployerServiceAccount" }
    )
    $spikeExpected = @(
        @{ Role = "roles/iam.serviceAccountTokenCreator"; Member = "user:$BootstrapUser" }
    )
    $runtimeExpected = @(
        @{ Role = "roles/iam.serviceAccountUser"; Member = "serviceAccount:$DeployerServiceAccount" }
    )

    $iamValid = $true
    if (-not (Test-ExpectedBindings $projectPolicy $projectExpected)) { $iamValid = $false }
    if (-not (Test-ExpectedBindings $repositoryPolicy $repositoryExpected)) { $iamValid = $false }
    if (-not (Test-ExpectedBindings $spikePolicy $spikeExpected)) { $iamValid = $false }
    if (-not (Test-ExpectedBindings $runtimePolicy $runtimeExpected)) { $iamValid = $false }
    if ($iamValid) { Write-Pass "IAM (7 bindings)" }

    Write-RelatedExtras $projectPolicy @(
        "serviceAccount:$SpikeServiceAccount",
        "serviceAccount:$RuntimeServiceAccount",
        "serviceAccount:$DeployerServiceAccount"
    ) $projectExpected "project"
    Write-RelatedExtras $repositoryPolicy @("serviceAccount:$DeployerServiceAccount") $repositoryExpected "Artifact Registry"
    Write-RelatedExtras $spikePolicy @("user:$BootstrapUser") $spikeExpected "spike SA"
    Write-RelatedExtras $runtimePolicy @("serviceAccount:$DeployerServiceAccount") $runtimeExpected "runtime SA"

    $cloudRunServices = @((Invoke-GcloudJson -Arguments @(
        "run", "services", "list", "--region=$Region", "--project=$ProjectId",
        "--configuration=$ConfigurationName"
    )).Data)
    if ($cloudRunServices.Count -eq 0) {
        Write-Pass "Cloud Run baseline"
    } else {
        Write-Failure "Expected 0 Cloud Run services in $Region; found $($cloudRunServices.Count). This check must evolve when runtime is deployed."
    }

    if ("secretmanager.googleapis.com" -in $enabledApis) {
        Write-Pass "Secret Manager API"
    } else {
        Write-Failure "Secret Manager API is not enabled."
    }
} catch {
    Write-Failure $_.Exception.Message
}

if ($script:FailureCount -gt 0) {
    Write-Host "[FAIL] Verification completed with $script:FailureCount critical failure(s)." -ForegroundColor Red
    exit 1
}

Write-Host "[PASS] GCP DEV/SPIKE baseline verified." -ForegroundColor Green
exit 0
