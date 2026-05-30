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
REM Phase 0: Resolve the SEPCC toolchain — system install, repo venv, or build
REM --------------------------------------------------------------------
REM Priority order:
REM   1. System-wide install (uv tool install) — PATH + known uv directories
REM   2. Repo venv (.venv314\Scripts) — already built in this clone
REM   3. Auto-build — create venv and sync (asks permission first)
REM
REM Desktop shortcuts on Windows don't always inherit the full user PATH,
REM so we check explicit uv tool directories in addition to `where`.

set "TOOLS_FROM=repo-venv"

REM Build list of known uv tool bin directories
set "UV_BIN_DIRS=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin"
REM Also ask uv where it puts tools, if uv is on PATH
where uv >nul 2>&1
if not errorlevel 1 (
    for /f "usebackq delims=" %%D in (`uv tool dir 2^>nul`) do (
        set "UV_TOOL_DIR=%%D"
    )
    if defined UV_TOOL_DIR set "UV_BIN_DIRS=!UV_TOOL_DIR!;%UV_BIN_DIRS%"
)

REM --- Tier 1a: where (checks inherited PATH) ---
where fcc-server >nul 2>&1
if not errorlevel 1 (
    for %%I in (fcc-server.exe) do set "FCC_SERVER=%%~$PATH:I"
    for %%I in (fcc-claude.exe) do set "FCC_CLAUDE=%%~$PATH:I"
    for %%I in (fcc-bootstrap-context.exe) do set "FCC_BOOTSTRAP=%%~$PATH:I"
)

REM --- Tier 1b: explicit search in known uv tool bin directories ---
if not exist "%FCC_SERVER%" (
    for %%D in ("%UV_BIN_DIRS:;=" "%") do (
        if not exist "%FCC_SERVER%" (
            if exist "%%~D\fcc-server.exe" (
                set "FCC_SERVER=%%~D\fcc-server.exe"
                set "FCC_CLAUDE=%%~D\fcc-claude.exe"
                set "FCC_BOOTSTRAP=%%~D\fcc-bootstrap-context.exe"
            )
        )
    )
)

REM Resolve python and confirm system install is usable
if exist "%FCC_SERVER%" (
    for %%I in ("%FCC_SERVER%") do set "TOOLS_BIN=%%~dpI"
    if exist "!TOOLS_BIN!python.exe" set "FCC_PY=!TOOLS_BIN!python.exe"
    set "TOOLS_FROM=system"
)

REM --- Tier 2: fall back to repo venv if system tools not found ---
if "%TOOLS_FROM%"=="repo-venv" (
    if exist "%FCC_SERVER%" (
        set "TOOLS_FROM=repo-venv"
    ) else (
        REM --- Tier 3: need to build. First check uv is available. ---
        where uv >nul 2>&1
        if errorlevel 1 (
            echo.
            echo ================================================================
            echo SEPCC tools are not installed and uv was not found on PATH.
            echo.
            echo Searched: where fcc-server ^(PATH^)
            for %%D in ("%UV_BIN_DIRS:;=" "%") do echo            %%~D
            echo.
            echo Run the installer once to set everything up:
            echo   powershell -File "%FCC_REPO%\scripts\install.ps1"
            echo ================================================================
            echo.
            pause
            exit /b 1
        )

        echo.
        echo SEPCC tools aren't set up yet in this clone.
        echo I can create the Python environment and install dependencies now.
        echo This only needs to happen once.
        echo.
        set /p BUILD_CHOICE="Proceed with setup? [Y/n] "
        if /i not "!BUILD_CHOICE!"=="" if /i not "!BUILD_CHOICE!"=="y" if /i not "!BUILD_CHOICE!"=="yes" (
            echo.
            echo Skipped. You can run this later with:
            echo   cd /d "%FCC_REPO%" ^&^& uv sync --no-dev
            pause
            exit /b 0
        )

        cd /d "%FCC_REPO%"

        REM Create venv if missing — capture stderr so we can diagnose
        if not exist "%VENV_SCRIPTS%\python.exe" (
            echo.
            echo Creating Python 3.14 virtual environment...
            uv python install 3.14 2>"%TEMP%\sepcc-py-error.txt"
            if errorlevel 1 (
                echo Python 3.14 install failed:
                type "%TEMP%\sepcc-py-error.txt" 2>nul
                del "%TEMP%\sepcc-py-error.txt" 2>nul
                echo.
                echo Try installing Python manually:
                echo   uv python install 3.14
                pause
                exit /b 1
            )
            del "%TEMP%\sepcc-py-error.txt" 2>nul

            uv venv --python 3.14 .venv314 2>"%TEMP%\sepcc-venv-error.txt"
            if not exist "%VENV_SCRIPTS%\python.exe" (
                echo Venv creation failed:
                type "%TEMP%\sepcc-venv-error.txt" 2>nul
                del "%TEMP%\sepcc-venv-error.txt" 2>nul
                pause
                exit /b 1
            )
            del "%TEMP%\sepcc-venv-error.txt" 2>nul
            echo Python environment created.
        )

        REM Sync dependencies — capture both stdout and stderr
        echo Installing SEPCC dependencies...
        uv sync --no-dev >"%TEMP%\sepcc-sync-out.txt" 2>&1
        set "SYNC_ERR=%ERRORLEVEL%"
        if not exist "%FCC_SERVER%" (
            echo.
            echo ================================================================
            echo Dependency installation failed ^(exit code !SYNC_ERR!^).
            echo.
            echo Full uv sync output:
            echo ----8<----
            type "%TEMP%\sepcc-sync-out.txt" 2>nul
            echo ----8<----
            echo.

            REM Check if this looks like a network issue
            findstr /i "connect timeout resolve refused unreachable SSL TLS certificate" "%TEMP%\sepcc-sync-out.txt" >nul 2>&1
            if not errorlevel 1 (
                REM Verify: actually try to reach the internet
                powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'https://github.com' -UseBasicParsing -TimeoutSec 5; exit 0 } catch { exit 1 }" >nul 2>&1
                if errorlevel 1 (
                    echo This appears to be a network connectivity problem.
                    echo If you use a proxy, enable it and try again:
                    echo.
                    echo   V2Ray / V2RayN  →  socks5://127.0.0.1:10808
                    echo   Clash / Verge   →  http://127.0.0.1:7890
                    echo   Shadowsocks     →  socks5://127.0.0.1:1080
                    echo   V2Ray HTTP      →  http://127.0.0.1:10809
                    echo.
                    echo Set the proxy in your terminal, then run this shortcut again.
                ) else (
                    echo Your internet connection is working. This may be a
                    echo different issue — check the error details above.
                )
            ) else (
                echo If the output above mentions a missing file or tool,
                echo that dependency may need to be installed separately.
            )
            echo ================================================================
            echo.
            del "%TEMP%\sepcc-sync-out.txt" 2>nul
            pause
            exit /b 1
        )
        del "%TEMP%\sepcc-sync-out.txt" 2>nul
        echo Dependencies ready.
        set "TOOLS_FROM=repo-venv"
    )
)

REM --------------------------------------------------------------------
REM Phase 1: Start the proxy server
REM --------------------------------------------------------------------
if "%TOOLS_FROM%"=="system" (
    echo Using SEPCC tools from system install: %FCC_SERVER%
) else (
    echo Using SEPCC tools from repo venv: %FCC_SERVER%
)
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
