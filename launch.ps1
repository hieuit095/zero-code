<#
.SYNOPSIS
    ZeroCode IDE — One-Click Local Launcher (Windows)
    Starts Redis (Docker), FastAPI backend, Worker, and Vite frontend.

.USAGE
    Right-click -> "Run with PowerShell"
    OR: powershell -ExecutionPolicy Bypass -File launch.ps1
#>

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$BACKEND = Join-Path $ROOT "backend"

Write-Host ""
Write-Host "  ZeroCode IDE - Local Launcher" -ForegroundColor Cyan
Write-Host "  =============================" -ForegroundColor Cyan
Write-Host ""

# --- 1. Redis ---
Write-Host "[1/4] Checking Redis..." -ForegroundColor Yellow
$redisRunning = docker ps --filter "publish=6379" --format "{{.ID}}" 2>$null
if ($redisRunning) {
    Write-Host "  OK: Redis already running" -ForegroundColor Green
} else {
    Write-Host "  Starting Redis..." -ForegroundColor Gray
    $null = docker run -d --name zerocode-redis -p 6379:6379 redis:alpine 2>$null
    if ($LASTEXITCODE -ne 0) { $null = docker start zerocode-redis 2>$null }
    Write-Host "  OK: Redis on port 6379" -ForegroundColor Green
}

# --- 2. Python deps ---
Write-Host "[2/4] Python dependencies..." -ForegroundColor Yellow
$null = python -c "import fastapi; import aiosqlite; import redis" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "  OK: All present" -ForegroundColor Green
} else {
    Write-Host "  Installing..." -ForegroundColor Gray
    pip install -r "$BACKEND\requirements.txt" aiosqlite --quiet
    Write-Host "  OK: Installed" -ForegroundColor Green
}

# --- 3. Node deps ---
Write-Host "[3/4] Node dependencies..." -ForegroundColor Yellow
if (Test-Path (Join-Path $ROOT "node_modules")) {
    Write-Host "  OK: node_modules present" -ForegroundColor Green
} else {
    Write-Host "  Installing..." -ForegroundColor Gray
    Push-Location $ROOT; npm install --silent; Pop-Location
    Write-Host "  OK: Installed" -ForegroundColor Green
}

# --- 4. Launch services in separate windows ---
Write-Host "[4/4] Launching services..." -ForegroundColor Yellow
Write-Host ""

# FastAPI backend
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$BACKEND'; Write-Host 'FastAPI Backend (port 8000)' -ForegroundColor Cyan; python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
Write-Host "  FastAPI backend  -> http://localhost:8000" -ForegroundColor Green

# Worker
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$BACKEND'; Write-Host 'Background Worker' -ForegroundColor Cyan; python -m worker"
Write-Host "  Background worker" -ForegroundColor Green

# Vite frontend
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$ROOT'; Write-Host 'Vite Frontend (port 5173)' -ForegroundColor Cyan; npm run dev"
Write-Host "  Vite frontend    -> http://localhost:5173" -ForegroundColor Green

Write-Host ""
Write-Host "  All services launched!" -ForegroundColor Cyan
Write-Host "  Opening browser in 3 seconds..." -ForegroundColor DarkGray
Write-Host "  Close the terminal windows to stop individual services." -ForegroundColor DarkGray
Write-Host ""

Start-Sleep -Seconds 3
Start-Process "http://localhost:5173"
