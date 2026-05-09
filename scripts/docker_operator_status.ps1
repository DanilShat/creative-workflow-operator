$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

docker compose -f compose.yaml --env-file .env.docker ps

Write-Host ""
Write-Host "API health" -ForegroundColor Cyan
try {
    Invoke-RestMethod "http://127.0.0.1:8000/api/v1/health" -TimeoutSec 10 | ConvertTo-Json -Compress
} catch {
    Write-Host "API health failed: $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Recent API logs" -ForegroundColor Cyan
docker compose -f compose.yaml --env-file .env.docker logs --tail 40 api
