@echo off
REM Double-click this to create an SEPCC desktop shortcut.
REM It spawns PowerShell so no manual command is needed.

set "SCRIPT_DIR=%~dp0"
set "PS1_PATH=%SCRIPT_DIR%create-desktop-shortcut.ps1"

if not exist "%PS1_PATH%" (
    echo Could not find create-desktop-shortcut.ps1 in %SCRIPT_DIR%
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1_PATH%"
pause
