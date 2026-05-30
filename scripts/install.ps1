param(
    [switch] $VoiceNim,
    [switch] $VoiceLocal,
    [switch] $VoiceAll,
    [string] $TorchBackend = "",
    [switch] $DryRun,
    [switch] $Help,
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]] $RemainingArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoGitUrl = "git+https://github.com/Alishahryar1/free-claude-code.git"
$PythonVersion = "3.14.0"
$UvInstallUrl = "https://astral.sh/uv/install.ps1"

function Show-Usage {
    @"
Usage: install.ps1 [options]

Installs or updates Claude Code, uv, Python 3.14.0, and Free Claude Code.

Options:
  -VoiceNim              Install NVIDIA NIM voice transcription support.
  -VoiceLocal            Install local Whisper voice transcription support.
  -VoiceAll              Install all voice transcription backends.
  -TorchBackend VALUE    Use a uv PyTorch backend, such as cu130. Requires local voice.
  -DryRun                Print commands without running them.
  -Help                  Show this help text.
"@
}

function Write-Step {
    param([string] $Message)

    Write-Host ""
    Write-Host "==> $Message"
}

function Format-Argument {
    param([string] $Value)

    if ($Value -match '^[A-Za-z0-9_./:@%+=,\[\]-]+$') {
        return $Value
    }

    return "'" + ($Value -replace "'", "''") + "'"
}

function Invoke-InstallCommand {
    param(
        [string] $FilePath,
        [string[]] $Arguments = @()
    )

    $parts = @($FilePath) + $Arguments
    $commandText = ($parts | ForEach-Object { Format-Argument ([string] $_) }) -join " "
    Write-Host "+ $commandText"

    if (-not $DryRun) {
        & $FilePath @Arguments
    }
}

function Invoke-UvInstaller {
    Write-Host "+ irm $UvInstallUrl | iex"

    if (-not $DryRun) {
        Invoke-RestMethod $UvInstallUrl | Invoke-Expression
    }
}

function Add-PathEntry {
    param([string] $PathEntry)

    if ([string]::IsNullOrWhiteSpace($PathEntry)) {
        return
    }

    $separator = [IO.Path]::PathSeparator
    $entries = @()
    if (-not [string]::IsNullOrEmpty($env:Path)) {
        $entries = $env:Path -split [regex]::Escape([string] $separator)
    }

    if ($entries -notcontains $PathEntry) {
        $env:Path = "$PathEntry$separator$env:Path"
    }
}

function Add-UvToPath {
    Add-PathEntry (Join-Path $HOME ".local\bin")
    Add-PathEntry (Join-Path $HOME ".cargo\bin")
}

function Assert-CommandAvailable {
    param([string] $Name)

    if ((-not $DryRun) -and (-not (Get-Command $Name -ErrorAction SilentlyContinue))) {
        throw "$Name is required. Install it first, then rerun this installer."
    }
}

function Test-NpmClaudePath {
    param([string] $ClaudePath)

    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        return $false
    }

    if ($DryRun) {
        return $true
    }

    $prefix = (& npm prefix -g 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($prefix)) {
        return $false
    }

    $prefixPath = [IO.Path]::GetFullPath([string] $prefix)
    $resolvedClaude = [IO.Path]::GetFullPath($ClaudePath)
    return $resolvedClaude.StartsWith($prefixPath, [System.StringComparison]::OrdinalIgnoreCase)
}

function Install-OrUpdateClaude {
    $claudeCommand = Get-Command claude -ErrorAction SilentlyContinue
    if ($claudeCommand) {
        if (Test-NpmClaudePath $claudeCommand.Source) {
            Invoke-InstallCommand -FilePath "npm" -Arguments @("install", "-g", "@anthropic-ai/claude-code@latest")
            return
        }

        $previousAutoUpdate = $env:CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE
        $env:CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE = "1"
        try {
            Invoke-InstallCommand -FilePath $claudeCommand.Source -Arguments @("update")
        }
        finally {
            if ($null -eq $previousAutoUpdate) {
                Remove-Item Env:\CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE -ErrorAction SilentlyContinue
            }
            else {
                $env:CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE = $previousAutoUpdate
            }
        }
        return
    }

    Assert-CommandAvailable "npm"
    Invoke-InstallCommand -FilePath "npm" -Arguments @("install", "-g", "@anthropic-ai/claude-code@latest")
}

function Install-OrUpdateUv {
    Add-UvToPath

    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Invoke-InstallCommand -FilePath "uv" -Arguments @("self", "update")
        return
    }

    Invoke-UvInstaller
    Add-UvToPath

    if ((-not $DryRun) -and (-not (Get-Command uv -ErrorAction SilentlyContinue))) {
        throw "uv was installed, but it is not available on PATH. Open a new terminal or add uv's bin directory to PATH."
    }
}

function Get-PackageSpec {
    $includeNim = $VoiceNim
    $includeLocal = $VoiceLocal

    if ($VoiceAll) {
        $includeNim = $true
        $includeLocal = $true
    }

    if ((-not [string]::IsNullOrWhiteSpace($TorchBackend)) -and (-not $includeLocal)) {
        throw "-TorchBackend requires -VoiceLocal or -VoiceAll."
    }

    if ($includeNim -and $includeLocal) {
        return "free-claude-code[voice,voice_local] @ $RepoGitUrl"
    }

    if ($includeNim) {
        return "free-claude-code[voice] @ $RepoGitUrl"
    }

    if ($includeLocal) {
        return "free-claude-code[voice_local] @ $RepoGitUrl"
    }

    return $RepoGitUrl
}

function Install-FreeClaudeCode {
    $packageSpec = Get-PackageSpec
    $toolArgs = @("tool", "install", "--force")

    if (-not [string]::IsNullOrWhiteSpace($TorchBackend)) {
        $toolArgs += @("--torch-backend", $TorchBackend)
    }

    $toolArgs += $packageSpec
    Invoke-InstallCommand -FilePath "uv" -Arguments $toolArgs
}

if ($Help) {
    Show-Usage
    return
}

if ($RemainingArgs.Count -gt 0) {
    Show-Usage
    throw "Unknown option: $($RemainingArgs -join ' ')"
}

if ((-not [string]::IsNullOrWhiteSpace($TorchBackend)) -and (-not ($VoiceLocal -or $VoiceAll))) {
    throw "-TorchBackend requires -VoiceLocal or -VoiceAll."
}

Write-Step "Installing or updating Claude Code"
Install-OrUpdateClaude

Write-Step "Installing uv if missing, updating if present"
Install-OrUpdateUv

Write-Step "Installing Python $PythonVersion"
Invoke-InstallCommand -FilePath "uv" -Arguments @("python", "install", $PythonVersion)

Write-Step "Installing or updating Free Claude Code"
Install-FreeClaudeCode

Write-Host ""
Write-Host "Free Claude Code is installed. Start the proxy with: fcc-server"
