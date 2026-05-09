param(
    [switch]$Volumes
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$args = @("compose", "-f", "compose.yaml", "--env-file", ".env.docker", "down")
if ($Volumes) {
    $args += "--volumes"
}

docker @args
