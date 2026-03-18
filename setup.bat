@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title ZeroCode IDE — Developer Setup

:: ╔══════════════════════════════════════════════════════════════════════╗
:: ║             ZeroCode IDE — One-Click Developer Setup (Windows)      ║
:: ╚══════════════════════════════════════════════════════════════════════╝

set "ERRORS=0"

echo.
echo ━━━ Phase A: Environment Verification ━━━
echo.

:: ─── Python ─────────────────────────────────────────────────────────────────
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   X  Python — not found
    echo      Install: https://www.python.org/downloads/
    set /a ERRORS+=1
) else (
    for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
    echo   OK Python v!PYVER!
)

:: ─── Node.js ────────────────────────────────────────────────────────────────
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo   X  Node.js — not found
    echo      Install: https://nodejs.org/
    set /a ERRORS+=1
) else (
    for /f "tokens=1 delims=" %%v in ('node --version 2^>^&1') do set NODEVER=%%v
    echo   OK Node.js !NODEVER!
)

:: ─── npm ────────────────────────────────────────────────────────────────────
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo   X  npm — not found
    echo      Install: https://nodejs.org/
    set /a ERRORS+=1
) else (
    echo   OK npm
)

:: ─── Docker ─────────────────────────────────────────────────────────────────
where docker >nul 2>&1
if %errorlevel% neq 0 (
    echo   X  Docker — not found
    echo      Install: https://docs.docker.com/get-docker/
    set /a ERRORS+=1
) else (
    echo   OK Docker
)

:: ─── Docker Compose ─────────────────────────────────────────────────────────
docker compose version >nul 2>&1
if %errorlevel% neq 0 (
    where docker-compose >nul 2>&1
    if %errorlevel% neq 0 (
        echo   X  Docker Compose — not found
        echo      Install: https://docs.docker.com/compose/install/
        set /a ERRORS+=1
    ) else (
        echo   OK Docker Compose (standalone^)
    )
) else (
    echo   OK Docker Compose (plugin^)
)

if !ERRORS! gtr 0 (
    echo.
    echo X  !ERRORS! missing dependency(ies^). Please install them and re-run this script.
    exit /b 1
)

echo.
echo All dependencies verified.

:: ═════════════════════════════════════════════════════════════════════════════
:: PHASE B — Environment Variables
:: ═════════════════════════════════════════════════════════════════════════════

echo.
echo ━━━ Phase B: Environment Variables ━━━
echo.

if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo   !  Root .env created from .env.example
    )
) else (
    echo   OK Root .env (already exists^)
)

if not exist "backend\.env" (
    if exist "backend\.env.example" (
        copy "backend\.env.example" "backend\.env" >nul
        echo   !  Backend .env created from .env.example
    )
) else (
    echo   OK Backend .env (already exists^)
)

echo.
echo   WARNING: .env files created. Please open them and add your LLM API Keys before running the app!

:: ═════════════════════════════════════════════════════════════════════════════
:: PHASE C — Backend Setup (Python)
:: ═════════════════════════════════════════════════════════════════════════════

echo.
echo ━━━ Phase C: Backend Setup (Python) ━━━
echo.

if not exist "backend\venv" (
    echo   Creating virtual environment...
    python -m venv backend\venv
    echo   OK Virtual environment created at backend\venv
) else (
    echo   OK Virtual environment (already exists^)
)

echo   Installing Python dependencies...
call backend\venv\Scripts\activate.bat

python -m pip install --upgrade pip --quiet
python -m pip install -r backend\requirements.txt --quiet

echo   OK Python dependencies installed

call deactivate 2>nul

:: ═════════════════════════════════════════════════════════════════════════════
:: PHASE D — Frontend Setup (Node.js)
:: ═════════════════════════════════════════════════════════════════════════════

echo.
echo ━━━ Phase D: Frontend Setup (Node.js) ━━━
echo.

echo   Running npm install...
call npm install --silent 2>nul || call npm install
echo   OK Node.js dependencies installed

:: ═════════════════════════════════════════════════════════════════════════════
:: PHASE E — Infrastructure (Docker)
:: ═════════════════════════════════════════════════════════════════════════════

echo.
echo ━━━ Phase E: Infrastructure (Docker) ━━━
echo.

set "COMPOSE_FILE=infra\staging\docker-compose.yml"

if exist "%COMPOSE_FILE%" (
    echo   Starting Redis via Docker Compose...
    docker compose -f "%COMPOSE_FILE%" up -d redis 2>nul && (
        echo   OK Redis container running
    ) || (
        docker-compose -f "%COMPOSE_FILE%" up -d redis 2>nul && (
            echo   OK Redis container running
        ) || (
            echo   !  Could not start Redis — is Docker Desktop running?
        )
    )
) else (
    echo   !  docker-compose.yml not found. Make sure Redis is available at localhost:6379
)

:: ═════════════════════════════════════════════════════════════════════════════
:: PHASE F — Success Handoff
:: ═════════════════════════════════════════════════════════════════════════════

cls

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║                                                          ║
echo  ║   ZEROCODE IDE — SETUP COMPLETE                          ║
echo  ║                                                          ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.
echo  Next Steps:
echo.
echo    1. Edit your .env file with your LLM API keys:
echo       notepad .env
echo.
echo    2. Start the Backend (Terminal 1):
echo       backend\venv\Scripts\activate
echo       cd backend ^&^& python -m uvicorn app.main:app --reload --port 8000
echo.
echo    3. Start the Worker (Terminal 2):
echo       backend\venv\Scripts\activate
echo       cd backend ^&^& python -m worker
echo.
echo    4. Start the Frontend (Terminal 3):
echo       npm run dev
echo.
echo    Open http://localhost:5173 and start building!
echo.

endlocal
