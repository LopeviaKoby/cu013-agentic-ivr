"""Exercise the Cloud Run zero-minimum scripts with an isolated gcloud fake."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell unavailable")
def test_rotation_accepts_unset_cloud_run_minimum() -> None:
    script_path = Path(__file__).resolve().parents[1] / "ops/gcp/rotate-dev-benchmark-api-key.ps1"
    quoted_path = str(script_path).replace("'", "''")
    harness = r"""
$global:rotated = $false
$global:secretBytes = $null
$global:image = 'us-east1-docker.pkg.dev/tivit-cu013-prd/' +
    'cu013-containers-dev/cu013-runtime-dev:exp-prompt-protocols'
$global:digest = 'us-east1-docker.pkg.dev/tivit-cu013-prd/' +
    'cu013-containers-dev/cu013-runtime-dev@sha256:' +
    '4dffcd59001312396912e4cac1c739e1c11d45ca8ff4a77185b3d046312b902a'
function global:gcloud {
    $global:LASTEXITCODE = 0
    $tokens = @($args)
    $command = $tokens[0..2] -join ' '
    if ($command -eq 'run services describe') {
        $version = if ($global:rotated) { '2' } else { '1' }
        $revision = if ($global:rotated) {
            'cu013-runtime-dev-00004-mock'
        } else {
            'cu013-runtime-dev-00003-j8n'
        }
        $templateAnnotations = @{
            'autoscaling.knative.dev/maxScale'='1'
            'run.googleapis.com/cpu-throttling'='true'
        }
        if ($global:rotated) { $templateAnnotations['autoscaling.knative.dev/minScale'] = '1' }
        $result = @{
            metadata = @{name='cu013-runtime-dev';namespace='731118338507';labels=@{'cloud.googleapis.com/location'='us-east1'};annotations=@{'run.googleapis.com/urls'='["https://cu013-runtime-dev-731118338507.us-east1.run.app"]'}}
            spec = @{template=@{metadata=@{annotations=$templateAnnotations};spec=@{
                containerConcurrency=1;serviceAccountName='cu013-cloud-run-sa@tivit-cu013-prd.iam.gserviceaccount.com'
                containers=@(@{image=$global:image;resources=@{limits=@{cpu='1';memory='512Mi'}};env=@(@{name='CU013_API_KEY';valueFrom=@{secretKeyRef=@{name='cu013-api-key-dev';key=$version}}})})
            }}}
            status = @{url='https://cu013-runtime-dev-731118338507.us-east1.run.app';latestReadyRevisionName=$revision;conditions=@(@{type='Ready';status='True'})}
        }
        ConvertTo-Json -InputObject $result -Depth 20
        return
    }
    if ($command -eq 'run revisions describe') {
        ConvertTo-Json -InputObject @{status=@{imageDigest=$global:digest}} -Depth 10
        return
    }
    if ($command -eq 'secrets versions list') {
        $versions = @(@{name='projects/mock/secrets/cu013-api-key-dev/versions/1'})
        ConvertTo-Json -InputObject $versions -Depth 10
        return
    }
    if ($command -eq 'secrets versions add') {
        $fileArgument = @($tokens | Where-Object { $_ -like '--data-file=*' })
        if ($fileArgument.Count -ne 1) { throw 'mock expected exactly one data file' }
        $global:secretBytes = [IO.File]::ReadAllBytes($fileArgument[0].Substring(12))
        $value = [Text.Encoding]::ASCII.GetString($global:secretBytes)
        if ($global:secretBytes.Length -ne 44 -or
            $value.IndexOfAny([char[]]@(0,10,13)) -ge 0) {
            throw 'invalid secret bytes'
        }
        $version = @{name='projects/mock/secrets/cu013-api-key-dev/versions/2'}
        ConvertTo-Json -InputObject $version -Depth 10
        return
    }
    if ($command -eq 'secrets versions access') {
        [Convert]::ToBase64String($global:secretBytes).TrimEnd('=').Replace('+','-').Replace('/','_')
        return
    }
    if ($command -eq 'run services update') {
        if ($null -eq $global:secretBytes) { throw 'update before secret creation' }
        $global:rotated = $true
        return
    }
    throw "unexpected gcloud invocation: $command"
}
& '__SCRIPT_PATH__' -ExpectedImage $global:image -ExpectedImageDigest $global:digest
if (-not $global:rotated) { throw 'rotation did not complete' }
""".replace("__SCRIPT_PATH__", quoted_path)

    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", harness],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "preflight passed: expected image, secret version 1, min=0" in result.stdout
    assert "PASS min_instances: min=1 (revision=1 service=0 expected 1)" in result.stdout
    assert "all checks passed." in result.stdout
