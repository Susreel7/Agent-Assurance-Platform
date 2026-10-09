$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    docker compose down -v --remove-orphans
    if ($LASTEXITCODE -ne 0) { throw "docker compose down failed ($LASTEXITCODE)" }
    docker system prune -f
    if ($LASTEXITCODE -ne 0) { throw "docker system prune failed ($LASTEXITCODE)" }
    docker compose build --no-cache @args
    if ($LASTEXITCODE -ne 0) { throw "docker compose build failed ($LASTEXITCODE)" }
    docker compose up -d
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed ($LASTEXITCODE)" }
} finally {
    Pop-Location
}
