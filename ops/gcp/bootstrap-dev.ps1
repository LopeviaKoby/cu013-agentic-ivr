Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectId = "cu013-xcally-agentic"
$ProjectNumber = "17280606194"
$OrganizationId = "268452702158"
$Region = "us-east1"
$ConfigurationName = "cu013-xcally-agentic"
$BootstrapUser = "ylopevia@gmail.com"

$ArtifactRepository = "cu013-containers-dev"

$SpikeServiceAccountId = "cu013-spike-firestore"
$RuntimeServiceAccountId = "cu013-runtime-dev"
$DeployerServiceAccountId = "cu013-deployer-dev"

$RequiredApis = @(
    "aiplatform.googleapis.com"
    "artifactregistry.googleapis.com"
    "firestore.googleapis.com"
    "iam.googleapis.com"
    "iamcredentials.googleapis.com"
    "run.googleapis.com"
    "secretmanager.googleapis.com"
)

$SpikeServiceAccount = "$SpikeServiceAccountId@$ProjectId.iam.gserviceaccount.com"
$RuntimeServiceAccount = "$RuntimeServiceAccountId@$ProjectId.iam.gserviceaccount.com"
$DeployerServiceAccount = "$DeployerServiceAccountId@$ProjectId.iam.gserviceaccount.com"

function Write-Step {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[STEP] $Message" -ForegroundColor Cyan
}

function Invoke-Gcloud {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )

    # Keep stderr separate so gcloud warnings never contaminate structured stdout.
    $output = @(& gcloud @Arguments)
    $exitCode = $LASTEXITCODE
    $text = $output -join [Environment]::NewLine

    if ($exitCode -ne 0 -and -not $AllowFailure) {
        throw "gcloud failed with exit code ${exitCode}: gcloud $($Arguments -join ' ')"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Text = $text
    }
}

function Invoke-GcloudJson {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $result = Invoke-Gcloud -Arguments ($Arguments + "--format=json")
    if ([string]::IsNullOrWhiteSpace($result.Text)) {
        return [pscustomobject]@{ Data = @() }
    }

    return [pscustomobject]@{ Data = ($result.Text | ConvertFrom-Json) }
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

function Ensure-ConfigurationProperty {
    param(
        [Parameter(Mandatory)][System.Collections.IDictionary]$Configuration,
        [Parameter(Mandatory)][string]$Property,
        [Parameter(Mandatory)][string]$Section,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$ExpectedValue
    )

    $currentValue = Get-NestedConfigValue -Configuration $Configuration -Section $Section -Name $Name
    if ([string]::IsNullOrWhiteSpace($currentValue)) {
        Write-Host "[CREATE] Set $Property in configuration $ConfigurationName"
        Invoke-Gcloud -Arguments @(
            "config", "set", $Property, $ExpectedValue,
            "--configuration=$ConfigurationName"
        ) | Out-Null
        return
    }

    if ($currentValue -ne $ExpectedValue) {
        throw "Configuration $ConfigurationName has $Property=$currentValue; expected $ExpectedValue. Refusing to overwrite it."
    }

    Write-Host "[OK] Configuration property $Property"
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

function Ensure-ProjectBinding {
    param(
        [Parameter(Mandatory)][string]$Role,
        [Parameter(Mandatory)][string]$Member
    )

    $policy = (Invoke-GcloudJson -Arguments @(
        "projects", "get-iam-policy", $ProjectId,
        "--configuration=$ConfigurationName"
    )).Data
    if (Test-IamBinding -Policy $policy -Role $Role -Member $Member) {
        Write-Host "[OK] Project IAM $Role -> $Member"
        return
    }

    Write-Host "[CREATE] Project IAM $Role -> $Member"
    Invoke-Gcloud -Arguments @(
        "projects", "add-iam-policy-binding", $ProjectId,
        "--member=$Member", "--role=$Role", "--condition=None",
        "--configuration=$ConfigurationName", "--quiet"
    ) | Out-Null
}

function Ensure-RepositoryBinding {
    param(
        [Parameter(Mandatory)][string]$Role,
        [Parameter(Mandatory)][string]$Member
    )

    $policy = (Invoke-GcloudJson -Arguments @(
        "artifacts", "repositories", "get-iam-policy", $ArtifactRepository,
        "--location=$Region", "--project=$ProjectId",
        "--configuration=$ConfigurationName"
    )).Data
    if (Test-IamBinding -Policy $policy -Role $Role -Member $Member) {
        Write-Host "[OK] Artifact Registry IAM $Role -> $Member"
        return
    }

    Write-Host "[CREATE] Artifact Registry IAM $Role -> $Member"
    Invoke-Gcloud -Arguments @(
        "artifacts", "repositories", "add-iam-policy-binding", $ArtifactRepository,
        "--location=$Region", "--project=$ProjectId",
        "--member=$Member", "--role=$Role", "--condition=None",
        "--configuration=$ConfigurationName", "--quiet"
    ) | Out-Null
}

function Ensure-ServiceAccountBinding {
    param(
        [Parameter(Mandatory)][string]$ServiceAccount,
        [Parameter(Mandatory)][string]$Role,
        [Parameter(Mandatory)][string]$Member
    )

    $policy = (Invoke-GcloudJson -Arguments @(
        "iam", "service-accounts", "get-iam-policy", $ServiceAccount,
        "--project=$ProjectId", "--configuration=$ConfigurationName"
    )).Data
    if (Test-IamBinding -Policy $policy -Role $Role -Member $Member) {
        Write-Host "[OK] Service account IAM $Role -> $Member"
        return
    }

    Write-Host "[CREATE] Service account IAM $Role -> $Member"
    Invoke-Gcloud -Arguments @(
        "iam", "service-accounts", "add-iam-policy-binding", $ServiceAccount,
        "--project=$ProjectId", "--member=$Member", "--role=$Role",
        "--condition=None", "--configuration=$ConfigurationName", "--quiet"
    ) | Out-Null
}

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    throw "Google Cloud SDK (gcloud) is required."
}

Write-Step "Verify authenticated bootstrap account"
$authenticatedAccounts = @((Invoke-GcloudJson -Arguments @("auth", "list")).Data)
if (-not ($authenticatedAccounts | Where-Object { $_.account -eq $BootstrapUser })) {
    throw "$BootstrapUser is not authenticated. Run gcloud auth login manually."
}

Write-Step "Ensure dedicated gcloud configuration"
$configurations = @((Invoke-GcloudJson -Arguments @("config", "configurations", "list")).Data)
$configurationExists = $null -ne ($configurations | Where-Object { $_.name -eq $ConfigurationName })
if (-not $configurationExists) {
    Invoke-Gcloud -Arguments @(
        "config", "configurations", "create", $ConfigurationName, "--no-activate"
    ) | Out-Null
}

$configurationResult = Invoke-Gcloud -Arguments @(
    "config", "configurations", "describe", $ConfigurationName, "--format=json"
)
$configuration = $configurationResult.Text | ConvertFrom-Json -AsHashtable
Ensure-ConfigurationProperty $configuration "core/account" "core" "account" $BootstrapUser
Ensure-ConfigurationProperty $configuration "core/project" "core" "project" $ProjectId
Ensure-ConfigurationProperty $configuration "compute/region" "compute" "region" $Region
Ensure-ConfigurationProperty $configuration "run/region" "run" "region" $Region
Ensure-ConfigurationProperty $configuration "artifacts/location" "artifacts" "location" $Region

Write-Step "Verify project identity"
$project = (Invoke-GcloudJson -Arguments @(
    "projects", "describe", $ProjectId, "--configuration=$ConfigurationName"
)).Data
if ([string]$project.projectNumber -ne $ProjectNumber) {
    throw "Project number mismatch: $($project.projectNumber); expected $ProjectNumber."
}
if ($project.parent.type -ne "organization" -or [string]$project.parent.id -ne $OrganizationId) {
    throw "Project parent mismatch; expected organization $OrganizationId."
}

Write-Step "Enable required APIs"
$enabledServices = @((Invoke-GcloudJson -Arguments @(
    "services", "list", "--enabled", "--project=$ProjectId",
    "--configuration=$ConfigurationName"
)).Data | ForEach-Object { $_.config.name })
$missingApis = @($RequiredApis | Where-Object { $_ -notin $enabledServices })
if ($missingApis.Count -gt 0) {
    $enableArguments = @(
        "services", "enable"
    ) + $missingApis + @(
        "--project=$ProjectId", "--configuration=$ConfigurationName", "--quiet"
    )
    Invoke-Gcloud -Arguments $enableArguments | Out-Null
} else {
    Write-Host "[OK] Required APIs are enabled"
}

Write-Step "Ensure Firestore default database"
$firestoreDescribeArguments = @(
    "firestore", "databases", "describe", "--database=(default)",
    "--project=$ProjectId", "--configuration=$ConfigurationName", "--format=json"
)
$firestoreResult = Invoke-Gcloud -Arguments $firestoreDescribeArguments -AllowFailure
if ($firestoreResult.ExitCode -ne 0) {
    $databases = @((Invoke-GcloudJson -Arguments @(
        "firestore", "databases", "list", "--project=$ProjectId",
        "--configuration=$ConfigurationName"
    )).Data)
    $defaultDatabaseName = "projects/$ProjectId/databases/(default)"
    if ($databases | Where-Object { $_.name -eq $defaultDatabaseName }) {
        throw "Firestore describe failed although the default database appears in list output. Refusing to create."
    }

    Invoke-Gcloud -Arguments @(
        "firestore", "databases", "create", "--database=(default)",
        "--location=$Region", "--type=firestore-native", "--edition=standard",
        "--project=$ProjectId", "--configuration=$ConfigurationName", "--quiet"
    ) | Out-Null
    $firestoreResult = Invoke-Gcloud -Arguments $firestoreDescribeArguments
}
$firestore = $firestoreResult.Text | ConvertFrom-Json
if ($firestore.locationId -ne $Region -or $firestore.type -ne "FIRESTORE_NATIVE" -or $firestore.databaseEdition -ne "STANDARD") {
    throw "Firestore exists with incompatible location, type, or edition. Refusing to modify it."
}
Write-Host "[OK] Firestore"

Write-Step "Ensure Artifact Registry repository"
$repositoryArguments = @(
    "artifacts", "repositories", "describe", $ArtifactRepository,
    "--location=$Region", "--project=$ProjectId",
    "--configuration=$ConfigurationName", "--format=json"
)
$repositoryResult = Invoke-Gcloud -Arguments $repositoryArguments -AllowFailure
if ($repositoryResult.ExitCode -ne 0) {
    $repositories = @((Invoke-GcloudJson -Arguments @(
        "artifacts", "repositories", "list", "--location=$Region",
        "--project=$ProjectId", "--configuration=$ConfigurationName"
    )).Data)
    $expectedRepositoryName = "projects/$ProjectId/locations/$Region/repositories/$ArtifactRepository"
    if ($repositories | Where-Object { $_.name -eq $expectedRepositoryName }) {
        throw "Artifact Registry describe failed although the repository appears in list output. Refusing to create."
    }

    Invoke-Gcloud -Arguments @(
        "artifacts", "repositories", "create", $ArtifactRepository,
        "--repository-format=docker", "--location=$Region", "--project=$ProjectId",
        "--configuration=$ConfigurationName", "--quiet"
    ) | Out-Null
    $repositoryResult = Invoke-Gcloud -Arguments $repositoryArguments
}
$repository = $repositoryResult.Text | ConvertFrom-Json
$expectedRepositoryName = "projects/$ProjectId/locations/$Region/repositories/$ArtifactRepository"
if ($repository.name -ne $expectedRepositoryName -or $repository.format -ne "DOCKER" -or $repository.mode -ne "STANDARD_REPOSITORY") {
    throw "Artifact Registry repository exists with incompatible location, format, or mode."
}
Write-Host "[OK] Artifact Registry"

Write-Step "Ensure service accounts"
$serviceAccounts = @((Invoke-GcloudJson -Arguments @(
    "iam", "service-accounts", "list", "--project=$ProjectId",
    "--configuration=$ConfigurationName"
)).Data)
$serviceAccountDefinitions = @(
    @{ Id = $SpikeServiceAccountId; Email = $SpikeServiceAccount; DisplayName = "CU013 Firestore spike" }
    @{ Id = $RuntimeServiceAccountId; Email = $RuntimeServiceAccount; DisplayName = "CU013 runtime DEV" }
    @{ Id = $DeployerServiceAccountId; Email = $DeployerServiceAccount; DisplayName = "CU013 deployer DEV" }
)
foreach ($definition in $serviceAccountDefinitions) {
    if ($serviceAccounts | Where-Object { $_.email -eq $definition.Email }) {
        Write-Host "[OK] Service account $($definition.Email)"
        continue
    }

    Write-Host "[CREATE] Service account $($definition.Email)"
    Invoke-Gcloud -Arguments @(
        "iam", "service-accounts", "create", $definition.Id,
        "--display-name=$($definition.DisplayName)", "--project=$ProjectId",
        "--configuration=$ConfigurationName", "--quiet"
    ) | Out-Null
}

Write-Step "Ensure seven approved IAM bindings"
Ensure-ProjectBinding "roles/datastore.user" "serviceAccount:$SpikeServiceAccount"
Ensure-ProjectBinding "roles/datastore.user" "serviceAccount:$RuntimeServiceAccount"
Ensure-ProjectBinding "roles/aiplatform.user" "serviceAccount:$RuntimeServiceAccount"
Ensure-ProjectBinding "roles/run.developer" "serviceAccount:$DeployerServiceAccount"
Ensure-RepositoryBinding "roles/artifactregistry.writer" "serviceAccount:$DeployerServiceAccount"
Ensure-ServiceAccountBinding $SpikeServiceAccount "roles/iam.serviceAccountTokenCreator" "user:$BootstrapUser"
Ensure-ServiceAccountBinding $RuntimeServiceAccount "roles/iam.serviceAccountUser" "serviceAccount:$DeployerServiceAccount"

Write-Host ""
Write-Host "[DONE] GCP DEV/SPIKE baseline is configured." -ForegroundColor Green
Write-Host "Run ADC impersonation manually when needed:"
Write-Host "gcloud auth application-default login --impersonate-service-account=$SpikeServiceAccount"
Write-Host "Then verify with: pwsh -NoProfile -File .\ops\gcp\verify-dev.ps1"
