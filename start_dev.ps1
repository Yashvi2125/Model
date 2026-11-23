# TripMate AI - Local Dev Launcher
# Runs the FastAPI backend on http://localhost:8000 (SQLite, no Docker needed).
# Usage:  .\start_dev.ps1

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

# Load .env into this process environment
Get-Content "$root\.env" | ForEach-Object {
    if ($_ -match '^\s*([^#=][^=]*)=(.*)$') {
        $key   = $matches[1].Trim()
        $value = $matches[2].Trim()
        [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
}

# SQLite for local dev (no Postgres / Docker required)
[System.Environment]::SetEnvironmentVariable("DATABASE_URL", "sqlite:///./tripmate_dev.db", "Process")
[System.Environment]::SetEnvironmentVariable("GEMINI_MODEL", "gemini-3.8-flash", "Process")
[System.Environment]::SetEnvironmentVariable("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite", "Process")

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  TripMate AI - Local Dev Server" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Backend  : http://localhost:8000" -ForegroundColor Green
Write-Host "  API Docs : http://localhost:8000/api/docs" -ForegroundColor Green
Write-Host "  Frontend : http://localhost:5173  (run start_frontend.ps1)" -ForegroundColor Green
Write-Host "  Model    : gemini-3.8-flash (fallback: gemini-3.5-flash-lite)" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Apply DB migrations (creates SQLite file on first run, no-op after)
Write-Host "[1/2] Applying database migrations..." -ForegroundColor Yellow
& "$root\.venv\Scripts\alembic.exe" upgrade head 2>&1 | Out-Null
Write-Host "      Migrations up to date." -ForegroundColor Green

# Start uvicorn (single-process, stable on Windows)
Write-Host "[2/2] Starting backend on :8000 ..." -ForegroundColor Yellow
& "$root\.venv\Scripts\uvicorn.exe" server.main:app --host 0.0.0.0 --port 8000
