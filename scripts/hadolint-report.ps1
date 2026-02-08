# Run hadolint on all Dockerfiles and save results to hadolint-report.txt
# Usage: .\scripts\hadolint-report.ps1
# Requires: Docker running, or hadolint in PATH

param(
    [string]$OutFile = "hadolint-report.txt"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

$report = @()
$report += "Hadolint scan results"
$report += "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$report += ""

$dockerfiles = @("Dockerfile", "Dockerfile.isolated")
$configPath = Join-Path $root ".hadolint.yaml"
$hasDocker = Get-Command docker -ErrorAction SilentlyContinue
$hasHadolint = Get-Command hadolint -ErrorAction SilentlyContinue

if (-not $hasDocker -and -not $hasHadolint) {
    $report += "ERROR: Neither Docker nor hadolint found. Install hadolint (scoop install hadolint) or start Docker and re-run."
    $report | Set-Content -Path $OutFile -Encoding utf8
    Write-Host ($report -Join "`n")
    exit 1
}

foreach ($df in $dockerfiles) {
    $path = Join-Path $root $df
    if (-not (Test-Path $path)) { continue }
    $report += "========== $df =========="
    try {
        if ($hasDocker) {
            if (Test-Path $configPath) {
                $result = Get-Content $path | docker run --rm -i -v "${root}/.hadolint.yaml:/root/.hadolint.yaml" hadolint/hadolint hadolint - 2>&1
            } else {
                $result = Get-Content $path | docker run --rm -i hadolint/hadolint hadolint - 2>&1
            }
        } else {
            $result = & hadolint $path 2>&1
        }
        if ($result) {
            $report += $result
        } else {
            $report += "No issues found."
        }
    } catch {
        $report += "Error: $_"
    }
    $report += ""
}

$report += "========== End of report =========="
$report | Set-Content -Path $OutFile -Encoding utf8
Write-Host "Report written to $OutFile"
Write-Host ""
Write-Host ($report -Join "`n")
