# PowerShell script to lint Dockerfile using hadolint
# Usage: .\scripts\lint-dockerfile.ps1 [Dockerfile path]

param(
    [string]$Dockerfile = "Dockerfile"
)

$ErrorActionPreference = "Stop"

Write-Host "Linting Dockerfile: $Dockerfile" -ForegroundColor Cyan

# Check if Docker is available
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Docker is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Please install Docker Desktop or use hadolint directly" -ForegroundColor Yellow
    exit 1
}

$HadolintImage = "hadolint/hadolint:latest"

# Check if hadolint image exists, pull if not
Write-Host "Checking for hadolint image..." -ForegroundColor Gray
docker image inspect $HadolintImage 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Pulling hadolint image..." -ForegroundColor Gray
    docker pull $HadolintImage
}

# Run hadolint
if (Test-Path ".hadolint.yaml") {
    Write-Host "Using .hadolint.yaml configuration" -ForegroundColor Gray
    Get-Content $Dockerfile | docker run --rm -i `
        -v "${PWD}/.hadolint.yaml:/root/.hadolint.yaml" `
        $HadolintImage
} else {
    Write-Host "No .hadolint.yaml found, using default rules" -ForegroundColor Gray
    Get-Content $Dockerfile | docker run --rm -i $HadolintImage
}

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Dockerfile linting passed!" -ForegroundColor Green
} else {
    Write-Host "✗ Dockerfile linting failed!" -ForegroundColor Red
    exit 1
}
