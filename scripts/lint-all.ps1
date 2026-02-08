# PowerShell script to lint both Python code and Dockerfile
# Usage: .\scripts\lint-all.ps1

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Running all linting checks" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check Python linting
if (Get-Command ruff -ErrorAction SilentlyContinue) {
    Write-Host "1. Linting Python code with ruff..." -ForegroundColor Yellow
    ruff check pyrest/ apps/ main.py
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Python linting passed!" -ForegroundColor Green
    } else {
        Write-Host "✗ Python linting failed!" -ForegroundColor Red
        exit 1
    }
    Write-Host ""
} else {
    Write-Host "⚠ ruff not found, skipping Python linting" -ForegroundColor Yellow
    Write-Host "  Install with: pip install ruff" -ForegroundColor Gray
    Write-Host ""
}

# Check Dockerfile linting
if (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Host "2. Linting Dockerfile with hadolint..." -ForegroundColor Yellow
    .\scripts\lint-dockerfile.ps1
    Write-Host ""
} else {
    Write-Host "⚠ Docker not found, skipping Dockerfile linting" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "All linting checks completed!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
