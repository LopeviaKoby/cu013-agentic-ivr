# Collects the read-only Cloud Run pre-state required before any Exp 0009
# burst authorization. NEVER mutates traffic, revisions, scaling or IAM.
# Usage:
#   powershell -File ops/gcp/collect-burst-prestate.ps1 -Service cu013-runtime-dev
param(
  [string]$Service = "cu013-runtime-dev",
  [string]$Region = "us-east1",
  [string]$Project = "cu013-xcally-agentic",
  [string]$OutDir = "evals/results"
)

$ErrorActionPreference = "Stop"

$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmss")
$outFile = Join-Path $OutDir ("burst-prestate-" + $stamp + ".json")
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$serviceJson = gcloud run services describe $Service `
  --region $Region --project $Project --format json
$revisionsJson = gcloud run revisions list `
  --service $Service --region $Region --project $Project --format json

$capture = [ordered]@{
  captured_at_utc = (Get-Date).ToUniversalTime().ToString("o")
  service         = $Service
  region          = $Region
  project         = $Project
  service_spec    = ($serviceJson | ConvertFrom-Json)
  revisions       = ($revisionsJson | ConvertFrom-Json)
  note            = "Compare spec.traffic (percentages, tags, latestRevision vs revisionName), " +
  "service/revision scaling, image digests and min_instances=0 against this " +
  "capture before AND after any authorized temporary revision. Never run " +
  "--to-latest while an experimental revision could become serving latest."
}
$capture | ConvertTo-Json -Depth 40 | Set-Content -Path $outFile -Encoding utf8
Write-Output ("prestate=" + $outFile)
