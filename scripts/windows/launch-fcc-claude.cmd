@echo off
REM Launch Free Claude Code proxy + Claude CLI in a project you choose.
setlocal EnableExtensions

REM Resolve FCC_REPO from this script's location: ...\scripts\windows\launch-fcc-claude.cmd → repo root.
set "FCC_REPO=%~dp0..\.."
for %%I in ("%FCC_REPO%") do set "FCC_REPO=%%~fI"
if defined FCC_REPO_ROOT set "FCC_REPO=%FCC_REPO_ROOT%"
if not defined FCC_PROJECTS_ROOT set "FCC_PROJECTS_ROOT=%USERPROFILE%\projects"

set "FCC_PY=%FCC_REPO%\.venv314\Scripts\python.exe"
set "FCC_SERVER=%FCC_REPO%\.venv314\Scripts\fcc-server.exe"
set "FCC_CLAUDE=%FCC_REPO%\.venv314\Scripts\fcc-claude.exe"
set "FCC_OPEN_BROWSER=0"

cd /d "%FCC_REPO%"
if errorlevel 1 (
    echo Could not find Free Claude Code install at: %FCC_REPO%
    pause
    exit /b 1
)

start "Free Claude Code Server" cmd /k "cd /d %FCC_REPO% && set FCC_OPEN_BROWSER=0 && %FCC_SERVER%"

set "FCC_PORT=8082"
set "FCC_PORT_FILE=%TEMP%\fcc-port-%RANDOM%.txt"
if exist "%FCC_PY%" (
    "%FCC_PY%" "%FCC_REPO%\scripts\windows\get-fcc-port.py" > "%FCC_PORT_FILE%" 2>nul
    if exist "%FCC_PORT_FILE%" set /p FCC_PORT=<"%FCC_PORT_FILE%"
    del "%FCC_PORT_FILE%" 2>nul
)

echo Waiting for the proxy to become healthy on port %FCC_PORT%...
powershell -NoProfile -Command "for ($i = 0; $i -lt 30; $i++) { try { Invoke-WebRequest -Uri ('http://127.0.0.1:' + $env:FCC_PORT + '/health') -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 1 } }; exit 1"
if errorlevel 1 (
    echo.
    echo Free Claude Code proxy is not ready on http://127.0.0.1:%FCC_PORT%
    echo Check the "Free Claude Code Server" window for errors, then run this shortcut again.
    pause
    exit /b 1
)

echo.
set "FCC_PICK_FILE=%TEMP%\fcc-project-%RANDOM%.txt"
del "%FCC_PICK_FILE%" 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%FCC_REPO%\scripts\windows\pick-project.ps1" -OutputFile "%FCC_PICK_FILE%"
set "PICK_ERR=%ERRORLEVEL%"
if "%PICK_ERR%"=="2" (
    del "%FCC_PICK_FILE%" 2>nul
    echo Cancelled.
    exit /b 0
)
if not "%PICK_ERR%"=="0" (
    del "%FCC_PICK_FILE%" 2>nul
    echo Project selection failed. See errors above.
    pause
    exit /b 1
)
if not exist "%FCC_PICK_FILE%" (
    echo Project selection failed: no project path was written.
    pause
    exit /b 1
)
set /p FCC_PROJECT=<"%FCC_PICK_FILE%"
del "%FCC_PICK_FILE%" 2>nul
if not defined FCC_PROJECT (
    echo Project selection failed: empty project path.
    pause
    exit /b 1
)

echo Working in: %FCC_PROJECT%

REM Auto-bootstrap context scaffolding if the project hasn't been set up yet.
set "FCC_BOOTSTRAP=%FCC_REPO%\.venv314\Scripts\fcc-bootstrap-context.exe"
if not exist "%FCC_PROJECT%\.claude\settings.json" (
    if exist "%FCC_BOOTSTRAP%" (
        echo First run in this project — setting up context scaffolding...
        "%FCC_BOOTSTRAP%" --target "%FCC_PROJECT%"
        if errorlevel 1 (
            echo Bootstrap failed. Continuing without context layer.
        ) else (
            echo Context scaffolding ready.
        )
    )
)
echo.

"%FCC_CLAUDE%" "%FCC_PROJECT%"
if errorlevel 1 pause
endlocal
