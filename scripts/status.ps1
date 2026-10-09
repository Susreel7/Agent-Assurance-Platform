$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    docker compose ps @args
    if ($LASTEXITCODE -ne 0) { throw "docker compose ps failed ($LASTEXITCODE)" }
} finally {
    Pop-Location
}
