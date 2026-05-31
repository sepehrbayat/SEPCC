@echo off
REM Launch SEPCC proxy + Claude CLI in a project you choose.
setlocal EnableExtensions EnableDelayedExpansion

REM Resolve FCC_REPO from this script's location.
set "FCC_REPO=%~dp0..\.."
for %%I in ("%FCC_REPO%") do set "FCC_REPO=%%~fI"
if defined FCC_REPO_ROOT set "FCC_REPO=%FCC_REPO_ROOT%"

set "FCC_OPEN_BROWSER=0"

REM --------------------------------------------------------------------
REM Phase 0: Ensure uv is available and deps are ready
REM --------------------------------------------------------------------

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
            echo If behind a firewall, enable your proxy and try again:
            echo   V2Ray / V2RayN  -  socks5://127.0.0.1:10808
            echo   Clash / Verge   -  http://127.0.0.1:7890
            echo.
            pause
            exit /b 1
        )
    ) else (
        echo Installer not found at %FCC_REPO%\scripts\install.ps1
        echo See README for manual setup.
        pause
        exit /b 1
    )
    where uv >nul 2>&1
    if errorlevel 1 (
        echo uv is still not found after install.
        echo Open a new terminal and try again.
        pause
        exit /b 1
    )
)

REM Silent sync: uv run auto-creates venv and installs deps.
REM Use a python import check instead of starting the server.
cd /d "%FCC_REPO%"
echo Checking SEPCC environment...
uv run python -c "import cli.entrypoints; import cli.bootstrap_context" >nul 2>&1
if errorlevel 1 (
    echo.
    echo First-time setup -- installing dependencies...
    uv sync >"%TEMP%\sepcc-sync-out.txt" 2>&1
    uv run python -c "import cli.entrypoints; import cli.bootstrap_context" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo ================================================================
        echo SEPCC environment setup failed.
        echo.
        type "%TEMP%\sepcc-sync-out.txt" 2>nul
        echo.
        echo ================================================================
        del "%TEMP%\sepcc-sync-out.txt" 2>nul
        pause
        exit /b 1
    )
    del "%TEMP%\sepcc-sync-out.txt" 2>nul
    echo Dependencies ready.
)

REM --------------------------------------------------------------------
REM Phase 1: Start the proxy server
REM --------------------------------------------------------------------
set "FCC_PORT=8082"
set "FCC_PORT_FILE=%TEMP%\fcc-port-%RANDOM%.txt"
uv run python "%FCC_REPO%\scripts\windows\get-fcc-port.py" > "%FCC_PORT_FILE%" 2>nul
if exist "%FCC_PORT_FILE%" set /p FCC_PORT=<"%FCC_PORT_FILE%"
del "%FCC_PORT_FILE%" 2>nul

if exist "%FCC_REPO%\scripts\windows\stop-fcc-server-on-port.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%FCC_REPO%\scripts\windows\stop-fcc-server-on-port.ps1" -Port "%FCC_PORT%" -Repo "%FCC_REPO%"
    if errorlevel 1 (
        echo.
        echo Could not stop the existing SEPCC server on port %FCC_PORT%.
        echo Close the "SEPCC Server" window and try again.
        pause
        exit /b 1
    )
)

start "SEPCC Server" cmd /k "cd /d %FCC_REPO% && set FCC_OPEN_BROWSER=0 && uv run fcc-server"

echo Waiting for the proxy to become healthy on port %FCC_PORT%...
powershell -NoProfile -Command "for ($i = 0; $i -lt 30; $i++) { try { Invoke-WebRequest -Uri ('http://127.0.0.1:' + $env:FCC_PORT + '/health') -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 1 } }; exit 1"
if errorlevel 1 (
    echo.
    echo SEPCC proxy is not ready on http://127.0.0.1:%FCC_PORT%
    echo Check the "SEPCC Server" window for errors, then try again.
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

dir /b "%FCC_PROJECT%" 2>nul | findstr . >nul
if errorlevel 1 (
    echo.
    echo ================================================================
    echo This folder is empty: %FCC_PROJECT%
    echo.
    echo If you have an existing project somewhere else, copy its contents
    echo into this folder, then re-launch this shortcut.
    echo.
    echo Otherwise, Claude Code can help you scaffold a new project from
    echo scratch -- just continue below.
    echo ================================================================
    echo.
    set /p EMPTY_CHOICE="Press Enter to start fresh, or type q to quit: "
    if /i "!EMPTY_CHOICE!"=="q" (
        echo Come back when your project is ready.
        pause
        exit /b 0
    )
)

REM Check if the full bootstrap scaffold is in place (not just settings.json).
REM A partial setup (e.g. only settings.json from an older CLI) needs refresh.
set "BOOTSTRAP_MISSING=0"
set "BOOTSTRAP_OUTDATED=0"
set "BOOTSTRAP_NEW=0"
if not exist "%FCC_PROJECT%\.claude\settings.json" set "BOOTSTRAP_NEW=1"
if not exist "%FCC_PROJECT%\.claude\agents\" set "BOOTSTRAP_MISSING=1"
if not exist "%FCC_PROJECT%\.claude\skills\" set "BOOTSTRAP_MISSING=1"
if not exist "%FCC_PROJECT%\.claude\commands\" set "BOOTSTRAP_MISSING=1"
if not exist "%FCC_PROJECT%\.fcc\context\handoff.md" set "BOOTSTRAP_MISSING=1"

if "%BOOTSTRAP_NEW%"=="1" (
    echo.
    echo This project hasn't been set up for SEPCC yet.
    echo Running context bootstrap to install hooks, agents, skills,
    echo commands, and the handoff system ^(50+ scaffolding files^)...
    echo.
    uv run fcc-bootstrap-context --target "%FCC_PROJECT%"
    if errorlevel 1 (
        echo Bootstrap failed. Continuing without context layer.
    ) else (
        echo Context scaffolding ready.
    )
    echo.
) else if "%BOOTSTRAP_MISSING%"=="1" (
    echo.
    echo ================================================================
    echo This project has a partial SEPCC setup.
    echo Some scaffolding files are missing.
    echo.
    echo What is present:
    for %%F in (".claude\settings.json" ".claude\agents" ".claude\skills" ".claude\commands" ".fcc\context\handoff.md") do (
        if exist "%FCC_PROJECT%\%%~F" (
            echo   [OK]  %%~F
        ) else (
            echo   [--]  %%~F  ^(missing^)
        )
    )
    echo.
    echo Running fcc-bootstrap-context will fill in the missing pieces
    echo without removing your existing settings or handoff content.
    echo ================================================================
    echo.
    set /p BOOTSTRAP_CHOICE="Run bootstrap now to complete the setup? [Y/n] "
    if /i "!BOOTSTRAP_CHOICE!"=="" set "BOOTSTRAP_CHOICE=y"
    if /i "!BOOTSTRAP_CHOICE!"=="y" (
        echo.
        uv run fcc-bootstrap-context --target "%FCC_PROJECT%"
        if errorlevel 1 (
            echo Bootstrap failed. You can retry later with:
            echo   uv run fcc-bootstrap-context --force
        ) else (
            echo All scaffolding files are now in place.
        )
    ) else (
        echo.
        echo Skipped. You can run this later with:
        echo   uv run fcc-bootstrap-context --force
    )
    echo.
) else (
    REM Full bootstrap already in place -- silent skip.
    echo.
)

REM --------------------------------------------------------------------
REM Phase 4: Launch Claude Code
REM --------------------------------------------------------------------
where wt >nul 2>&1
if not errorlevel 1 (
    echo Starting in Windows Terminal...
    wt -d "!FCC_PROJECT!" cmd /k "cd /d !FCC_REPO! && uv run fcc-claude ""!FCC_PROJECT!"""
) else (
    uv run fcc-claude "%FCC_PROJECT%"
    if errorlevel 1 pause
)
endlocal
