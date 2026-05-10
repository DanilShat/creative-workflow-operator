$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

if (-not (Test-Path ".env.server")) {
    Copy-Item ".env.server.example" ".env.server"
    Write-Host "Created .env.server from example. Edit DATABASE_URL and SERVER_PUBLIC_BASE_URL before native runs." -ForegroundColor Yellow
}

python -m pip install -e ".[test]"
python -m creative_workflow.server.cli config check
python -m creative_workflow.server.cli db migrate
python -m creative_workflow.server.cli healthcheck
