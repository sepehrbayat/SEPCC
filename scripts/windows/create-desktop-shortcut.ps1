# Creates a desktop shortcut to launch SEPCC.
# Run once after cloning the repo: pwsh scripts/windows/create-desktop-shortcut.ps1
# The created shortcut points to launch-fcc-claude.cmd in this same directory.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Launcher = Join-Path $ScriptDir 'launch-fcc-claude.cmd'

if (-not (Test-Path $Launcher)) {
    Write-Error "Launcher not found at: $Launcher"
    exit 1
}

$Desktop = [Environment]::GetFolderPath('Desktop')
$ShortcutPath = Join-Path $Desktop 'SEPCC.lnk'

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Launcher
$Shortcut.WorkingDirectory = $ScriptDir
$Shortcut.Description = 'SEPCC — Unlimited Claude Code'
$Shortcut.WindowStyle = 7  # minimized
$Shortcut.Save()

Write-Host "Desktop shortcut created: $ShortcutPath"
Write-Host "Double-click it to start SEPCC and pick a project."
