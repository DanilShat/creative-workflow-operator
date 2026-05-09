param(
    [string]$ServerPublicBaseUrl = "http://127.0.0.1:8000",
    [string]$TrustedWorkerIds = "designer-laptop-01,local-sim-worker-01",
    [string]$OllamaModel = "gemma3n:e2b"
)

$ErrorActionPreference = "Stop"

function Set-EnvValue {
    param([string]$Path, [string]$Key, [string]$Value)
    $lines = @()
    if (Test-Path $Path) {
        $lines = Get-Content -Path $Path
    }
    $pattern = "^$([regex]::Escape($Key))="
    $updated = $false
    $newLines = foreach ($line in $lines) {
        if ($line -match $pattern) {
            $updated = $true
            "$Key=$Value"
        } else {
            $line
        }
    }
    if (-not $updated) {
        $newLines += "$Key=$Value"
    }
    Set-Content -Path $Path -Value $newLines -Encoding UTF8
}

function New-ServerSecret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($bytes)
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

if (-not (Test-Path ".env.docker")) {
    Copy-Item ".env.docker.example" ".env.docker"
}

$existingSecret = ""
if (Test-Path ".env.docker") {
    $line = Get-Content ".env.docker" | Where-Object { $_ -match "^SERVER_SECRET=" } | Select-Object -First 1
    if ($line) {
        $existingSecret = $line -replace "^SERVER_SECRET=", ""
    }
}

if (-not $existingSecret -or $existingSecret -like "change-me*") {
    Set-EnvValue ".env.docker" "SERVER_SECRET" (New-ServerSecret)
}

Set-EnvValue ".env.docker" "SERVER_PUBLIC_BASE_URL" $ServerPublicBaseUrl
Set-EnvValue ".env.docker" "TRUSTED_WORKER_IDS" $TrustedWorkerIds
Set-EnvValue ".env.docker" "OLLAMA_MODEL" $OllamaModel
Set-EnvValue ".env.docker" "POSTGRES_PORT" "55432"

Write-Host "Docker operator env is ready: .env.docker" -ForegroundColor Green
Write-Host "SERVER_PUBLIC_BASE_URL=$ServerPublicBaseUrl"
Write-Host "TRUSTED_WORKER_IDS=$TrustedWorkerIds"
