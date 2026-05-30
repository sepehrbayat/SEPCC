@echo off
REM Launch SEPCC proxy + Claude CLI in a project you choose.
setlocal EnableExtensions EnableDelayedExpansion

REM Resolve FCC_REPO from this script's location: ...\scripts\windows\launch-fcc-claude.cmd → repo root.
set "FCC_REPO=%~dp0..\.."
for %%I in ("%FCC_REPO%") do set "FCC_REPO=%%~fI"
if defined FCC_REPO_ROOT set "FCC_REPO=%FCC_REPO_ROOT%"

set "VENV=%FCC_REPO%\.venv314"
set "VENV_SCRIPTS=%VENV%\Scripts"
set "FCC_PY=%VENV_SCRIPTS%\python.exe"
set "FCC_SERVER=%VENV_SCRIPTS%\fcc-server.exe"
set "FCC_CLAUDE=%VENV_SCRIPTS%\fcc-claude.exe"
set "FCC_BOOTSTRAP=%VENV_SCRIPTS%\fcc-bootstrap-context.exe"
set "FCC_OPEN_BROWSER=0"

REM --------------------------------------------------------------------
REM Phase 0: Ensure dependencies are installed (first-launch auto-setup)
REM --------------------------------------------------------------------

REM Check if uv is available. If not, run the full installer.
where uv >nul 2>&1
if errorlevel 1 (
    echo.
    echo uv is not installed. Running the SEPCC installer first...
    echo This only happens once — dependencies will be cached afterwards.
    echo.
    if exist "%FCC_REPO%\scripts\install.ps1" (
        powershell -NoProfile -ExecutionPolicy Bypass -File "%FCC_REPO%\scripts\install.ps1"
        if errorlevel 1 (
            echo.
            echo ================================================================
            echo Installation failed.
            echo.
            echo If you are behind a firewall or internet restriction, you
            echo may need to enable a proxy first:
            echo.
            echo   V2Ray / V2RayN:  port 10808  (SOCKS5)
            echo   Clash / Verge:    port 7890   (HTTP)
            echo   Shadowsocks:      port 1080   (SOCKS5)
            echo   Generic HTTP:     port 3128, 8888
            echo.
            echo Enable your proxy, then run this shortcut again.
            echo ================================================================
            echo.
            pause
            exit /b 1
        )
    ) else (
        echo installer script not found at %FCC_REPO%\scripts\install.ps1
        echo Please follow the manual install steps in the README.
        pause
        exit /b 1
    )
    REM Re-check uv after installer
    where uv >nul 2>&1
    if errorlevel 1 (
        echo uv still not found after install. Try opening a new terminal or
        echo adding uv to your PATH: https://docs.astral.sh/uv/getting-started/installation/
        pause
        exit /b 1
    )
)

REM Ensure Python 3.14 venv and dependencies are installed.
if not exist "%VENV_SCRIPTS%\python.exe" (
    echo.
    echo Setting up Python 3.14 environment...  ^(first launch only^)
    cd /d "%FCC_REPO%"

    uv python install 3.14.0 2>nul
    uv venv --python 3.14.0 .venv314 2>nul
    if not exist "%VENV_SCRIPTS%\python.exe" (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo Python environment created.
)

REM Sync dependencies if the server executable is missing.
if not exist "%FCC_SERVER%" (
    echo.
    echo Installing SEPCC dependencies...  ^(first launch only^)
    cd /d "%FCC_REPO%"

    uv sync --no-dev 2>"%TEMP%\sepcc-sync-error.txt"
    if not exist "%FCC_SERVER%" (
        echo.
        echo ================================================================
        echo Dependency installation failed.
        echo.

        REM Check what went wrong: network error or something else?
        findstr /i "connect timeout resolve refused unreachable SSL TLS certificate" "%TEMP%\sepcc-sync-error.txt" >nul 2>&1
        if not errorlevel 1 (
            echo It looks like a network connectivity issue. If you are
            echo behind a firewall or internet restriction, enable your
            echo proxy and try again:
            echo.
            echo   Common proxy ports:
            echo     V2Ray / V2RayN  →  socks5://127.0.0.1:10808
            echo     Clash / Verge   →  http://127.0.0.1:7890
            echo     Shadowsocks     →  socks5://127.0.0.1:1080
            echo     V2Ray HTTP      →  http://127.0.0.1:10809
            echo     Generic HTTP    →  port 3128, 8118, or 8888
            echo.
            echo After enabling your proxy, set it in the terminal:
            echo.
            echo   set HTTP_PROXY=http://127.0.0.1:10809
            echo   set HTTPS_PROXY=http://127.0.0.1:10809
            echo.
            echo Then run this shortcut again.
        ) else (
            echo Check the error log: %TEMP%\sepcc-sync-error.txt
        )
        echo ================================================================
        echo.
        del "%TEMP%\sepcc-sync-error.txt" 2>nul
        pause
        exit /b 1
    )
    del "%TEMP%\sepcc-sync-error.txt" 2>nul
    echo Dependencies ready.
)

REM --------------------------------------------------------------------
REM Phase 1: Start the proxy server
REM --------------------------------------------------------------------
cd /d "%FCC_REPO%"
if errorlevel 1 (
    echo Could not find SEPCC install at: %FCC_REPO%
    pause
    exit /b 1
)

start "SEPCC Server" cmd /k "cd /d %FCC_REPO% && set FCC_OPEN_BROWSER=0 && %FCC_SERVER%"

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

REM --------------------------------------------------------------------
REM Phase 4: Launch Claude Code
REM --------------------------------------------------------------------
if not exist "%FCC_CLAUDE%" (
    echo SEPCC launcher not found: %FCC_CLAUDE%
    echo Try running: uv sync
    pause
    exit /b 1
)

"%FCC_CLAUDE%" "%FCC_PROJECT%"
if errorlevel 1 pause
endlocal
