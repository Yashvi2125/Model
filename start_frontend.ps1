# TripMate AI - Frontend Dev Server
# Starts the Vite dev server on http://localhost:5173
# (proxies /api calls to the backend on :8000)
# Usage: .\start_frontend.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location "$root\frontend"

Write-Host ""
Write-Host "  Frontend : http://localhost:5173" -ForegroundColor Green
Write-Host "  (API proxied to http://localhost:8000)" -ForegroundColor Yellow
Write-Host ""

npm run dev
