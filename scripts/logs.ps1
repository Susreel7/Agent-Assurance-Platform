$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    docker compose logs -f @args
    if ($LASTEXITCODE -ne 0) { throw "docker compose logs failed ($LASTEXITCODE)" }
} finally {
    Pop-Location
}
