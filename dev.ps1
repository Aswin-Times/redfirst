<#
.SYNOPSIS
  Start REDFIRST locally: the API, the worker and the web UI, each in its own window.

.DESCRIPTION
  Works in Windows PowerShell 5.1 and PowerShell 7. Safe to run again.
  On first run it creates backend/.env from .env.example (SQLite, no secrets), installs
  dependencies that are missing and applies database migrations. Close a window to stop that
  service.

  The worker needs Docker and the sandbox image. Without them it explains what is missing and
  stops; investigations stay queued until a worker that can run them starts.

.PARAMETER NoWorker
  Do not start the worker (for example while Docker is not set up yet).

.PARAMETER NoBrowser
  Do not open the web UI in the browser.

.EXAMPLE
  .\dev.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\dev.ps1 -NoWorker
#>
[CmdletBinding()]
param([switch]$NoWorker, [switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

function Assert-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is not installed or not on PATH. $Hint"
    }
}

function Test-PortInUse([int]$Port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Invoke-Checked([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
}

function Start-RedfirstWindow([string]$Title, [string]$Directory, [string]$Command) {
    $dir = $Directory.Replace("'", "''")
    $script = "`$Host.UI.RawUI.WindowTitle = 'REDFIRST $Title'; Set-Location '$dir'; $Command"
    Start-Process powershell -ArgumentList "-NoExit", "-NoProfile", "-Command", $script | Out-Null
}

Assert-Command "uv" "Install it with: winget install --id astral-sh.uv"
Assert-Command "pnpm" "Install Node.js 20.9 or newer, then: npm install -g pnpm"

function Test-Answers([string]$Url, [string]$Expect) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return ($response.StatusCode -eq 200) -and ($response.Content -match $Expect)
    } catch {
        return $false
    }
}

# Reuse a REDFIRST API or web UI that is already running (from an earlier run, say); refuse only
# when a port is taken by something else.
$apiRunning = $false
$webRunning = $false
if (Test-PortInUse 8000) {
    if (-not (Test-Answers "http://127.0.0.1:8000/api/projects" "^\[")) {
        throw "Port 8000 is in use by something that is not the REDFIRST API. Close it and run this again."
    }
    $apiRunning = $true
    Write-Host "The REDFIRST API is already running on port 8000; using it."
}
if (Test-PortInUse 3000) {
    if (-not (Test-Answers "http://127.0.0.1:3000/" "REDFIRST")) {
        throw "Port 3000 is in use by something that is not the REDFIRST web UI. Close it and run this again."
    }
    $webRunning = $true
    Write-Host "The REDFIRST web UI is already running on port 3000; using it."
}

$envFile = Join-Path $backend ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root ".env.example") $envFile
    Write-Host "Created backend\.env from .env.example (SQLite database, no API key yet)."
}

Push-Location $backend
try {
    if (-not (Test-Path ".venv")) { Invoke-Checked "Installing backend dependencies" { uv sync } }
    Write-Host "Applying database migrations..."
    Invoke-Checked "Database migration" { uv run python -m alembic upgrade head }
} finally {
    Pop-Location
}

if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Push-Location $frontend
    try { Invoke-Checked "Installing web UI dependencies" { pnpm install } } finally { Pop-Location }
}

if (-not $apiRunning) {
    Start-RedfirstWindow "API" $backend "uv run python -m uvicorn redfirst.api.app:create_app --factory --host 127.0.0.1 --port 8000"
}
if (-not $NoWorker) {
    Start-RedfirstWindow "worker" $backend "uv run python -m redfirst.worker"
}
if (-not $webRunning) {
    Start-RedfirstWindow "web" $frontend "pnpm dev"
}

Write-Host "Waiting for the web UI on http://localhost:3000 ..."
$deadline = (Get-Date).AddMinutes(3)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:3000/" -UseBasicParsing -TimeoutSec 10
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $ready) {
    Write-Warning "The web UI did not answer within 3 minutes. Check the 'REDFIRST web' window for errors."
    exit 1
}

Write-Host ""
Write-Host "REDFIRST is running: http://localhost:3000"
Write-Host "Close the REDFIRST windows to stop it."
if ($NoWorker) {
    Write-Host "The worker was not started, so new investigations stay queued."
} else {
    Write-Host "If the 'REDFIRST worker' window says Docker is not available, see README: Running a real investigation."
}
if (-not $NoBrowser) { Start-Process "http://localhost:3000" }
