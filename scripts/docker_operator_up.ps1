param(
    [string]$ServerPublicBaseUrl = "http://127.0.0.1:8000",
    [switch]$Build
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\docker_operator_setup_env.ps1" -ServerPublicBaseUrl $ServerPublicBaseUrl

if ($Build) {
    # Build the shared operator image once. The migrate/api/ui services all run
    # from this image, which avoids three repeated exports during compose build.
    docker compose -f compose.yaml --env-file .env.docker build api
}

docker compose -f compose.yaml --env-file .env.docker up -d

Write-Host ""
Write-Host "Operator Docker stack is starting." -ForegroundColor Green
Write-Host "API: $ServerPublicBaseUrl/api/v1/health"
$uiUrl = $ServerPublicBaseUrl -replace ":8000$", ":8501"
Write-Host "UI:  $uiUrl"
Write-Host ""
Write-Host "Status:"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_status.ps1"
