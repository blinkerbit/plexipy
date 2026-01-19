# Build Docker images for PyRest (Windows PowerShell)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Building PyRest Docker Images" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# Build main PyRest image
Write-Host ""
Write-Host "Building main PyRest image..." -ForegroundColor Yellow
docker build -t pyrest:latest -f Dockerfile .

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Build complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "To run:" -ForegroundColor Cyan
    Write-Host "  docker run -p 8000:8000 pyrest:latest"
    Write-Host ""
    Write-Host "Or use docker-compose:" -ForegroundColor Cyan
    Write-Host "  docker-compose up -d"
} else {
    Write-Host "Build failed!" -ForegroundColor Red
    exit 1
}
