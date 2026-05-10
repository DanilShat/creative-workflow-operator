param(
    [ValidateSet("install", "test", "lint", "run")]
    [string]$Task = "test"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path $PSScriptRoot
Set-Location $RepoRoot

switch ($Task) {
    "install" {
        python -m pip install -e ".[test]"
    }
    "test" {
        python -m pytest tests -q
    }
    "lint" {
        python -m compileall src tests
    }
    "run" {
        powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\docker_operator_up.ps1" -Build
    }
}
