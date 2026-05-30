@echo off
REM Launch SEPCC proxy + Claude CLI in a project you choose.
setlocal EnableExtensions EnableDelayedExpansion

REM Resolve FCC_REPO from this script's location: ...\scripts\windows\launch-fcc-claude.cmd → repo root.
set "FCC_REPO=%~dp0..\.."
for %%I in ("%FCC_REPO%") do set "FCC_REPO=%%~fI"
if defined FCC_REPO_ROOT set "FCC_REPO=%FCC_REPO_ROOT%"

set "FCC_OPEN_BROWSER=0"

REM --------------------------------------------------------------------
REM Phase 0: Ensure uv is available
REM --------------------------------------------------------------------
REM We use `uv run` for everything — it manages venv and dependencies
REM automatically. No need to check for pre-built binaries.

where uv >nul 2>&1
if errorlevel 1 (
    echo.
    echo ================================================================
    echo uv is not installed. Running the SEPCC installer first...
    echo This only happens once.
    echo ================================================================
    echo.
    if exist "%FCC_REPO%\scripts\install.ps1" (
        powershell -NoProfile -ExecutionPolicy Bypass -File "%FCC_REPO%\scripts\install.ps1"
        if errorlevel 1 (
            echo.
            echo Installation failed.
            echo.
            findstr /i "connect timeout resolve refused unreachable" "%TEMP%\sepcc-install-error.txt" >nul 2>&1
            if not errorlevel 1 (
                echo This looks like a network issue. If you use a proxy,
                echo enable it and run this shortcut again:
                echo.
                echo   V2Ray / V2RayN  →  socks5://127.0.0.1:10808
                echo   Clash / Verge   →  http://127.0.0.1:7890
                echo.
            )
            pause
            exit /b 1
        )
    ) else (
        echo Installer not found. See README for manual setup.
        pause
        exit /b 1
    )
    where uv >nul 2>&1
    if errorlevel 1 (
        echo uv still not found. Open a new terminal and try again.
        pause
        exit /b 1
    )
)

REM First `uv run` from the repo will auto-create the venv and sync if needed.
REM Do a silent warm-up to trigger any first-time setup before we fork the server.
cd /d "%FCC_REPO%"
echo Checking SEPCC environment...
uv run fcc-server --help >nul 2>&1
if errorlevel 1 (
    REM `uv run` failed — likely first-run venv creation or dep install issue.
    REM Try explicitly syncing and show the error if it fails.
    echo.
    uv sync >"%TEMP%\sepcc-sync-out.txt" 2>&1
    set "SYNC_ERR=!ERRORLEVEL!"
    uv run fcc-server --help >nul 2>&1
    if errorlevel 1 (
        echo.
        echo ================================================================
        echo SEPCC environment setup failed (exit code !SYNC_ERR!).
        echo.
        type "%TEMP%\sepcc-sync-out.txt" 2>nul
        echo.
        findstr /i "connect timeout resolve refused unreachable" "%TEMP%\sepcc-sync-out.txt" >nul 2>&1
        if not errorlevel 1 (
            powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://github.com' -UseBasicParsing -TimeoutSec 5; exit 0 } catch { exit 1 }" >nul 2>&1
            if errorlevel 1 (
                echo This appears to be a network problem. Enable your proxy:
                echo   V2Ray / V2RayN  →  socks5://127.0.0.1:10808
                echo   Clash / Verge   →  http://127.0.0.1:7890
                echo Then run this shortcut again.
            )
        )
        echo ================================================================
        del "%TEMP%\sepcc-sync-out.txt" 2>nul
        pause
        exit /b 1
    )
    del "%TEMP%\sepcc-sync-out.txt" 2>nul
)

REM --------------------------------------------------------------------
REM Phase 1: Start the proxy server
REM --------------------------------------------------------------------
start "SEPCC Server" cmd /k "cd /d %FCC_REPO% && set FCC_OPEN_BROWSER=0 && uv run fcc-server"

set "FCC_PORT=8082"
set "FCC_PORT_FILE=%TEMP%\fcc-port-%RANDOM%.txt"
uv run python "%FCC_REPO%\scripts\windows\get-fcc-port.py" > "%FCC_PORT_FILE%" 2>nul
if exist "%FCC_PORT_FILE%" set /p FCC_PORT=<"%FCC_PORT_FILE%"
del "%FCC_PORT_FILE%" 2>nul

echo Waiting for the proxy to become healthy on port %FCC_PORT%...
powershell -NoProfile -Command "for ($i = 0; $i -lt 30; $i++) { try { Invoke-WebRequest -Uri ('http://127.0.0.1:' + $env:FCC_PORT + '/health') -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 1 } }; exit 1"
if errorlevel 1 (
    echo.
    echo SEPCC proxy is not ready on http://127.0.0.1:%FCC_PORT%
    echo Check the "SEPCC Server" window for errors, then run this shortcut again.
    pause
    exit /b 1
)

REM --------------------------------------------------------------------
REM Phase 2: Pick a project
REM --------------------------------------------------------------------
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

REM --------------------------------------------------------------------
REM Phase 3: Project-level setup
REM --------------------------------------------------------------------

REM Detect empty folder — nothing inside (no files, no subdirs).
dir /b "%FCC_PROJECT%" 2>nul | findstr . >nul
if errorlevel 1 (
    echo.
    echo ================================================================
    echo This folder is empty: %FCC_PROJECT%
    echo.
    echo If you have an existing project somewhere else, copy its contents
    echo into this folder, then re-launch this shortcut. This keeps your
    echo projects organized under one root so the picker can find them.
    echo.
    echo Otherwise, Claude Code can help you scaffold a new project from
    echo scratch — just continue below.
    echo ================================================================
    echo.
    set /p EMPTY_CHOICE="Press Enter to start fresh, or type q to quit: "
    if /i "!EMPTY_CHOICE!"=="q" (
        echo Come back when your project is ready.
        pause
        exit /b 0
    )
)

REM Auto-bootstrap context scaffolding if the project hasn't been set up yet.
if not exist "%FCC_PROJECT%\.claude\settings.json" (
    echo First run in this project — setting up context scaffolding...
    uv run fcc-bootstrap-context --target "%FCC_PROJECT%"
    if errorlevel 1 (
        echo Bootstrap failed. Continuing without context layer.
    ) else (
        echo Context scaffolding ready.
    )
)
echo.

REM --------------------------------------------------------------------
REM Phase 4: Launch Claude Code
REM --------------------------------------------------------------------
uv run fcc-claude "%FCC_PROJECT%"
if errorlevel 1 pause
endlocal
