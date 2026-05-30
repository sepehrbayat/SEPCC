# Pick a project folder under FCC_PROJECTS_ROOT (default: %USERPROFILE%\projects).
param(
    [string] $ProjectsRoot = $(if ($env:FCC_PROJECTS_ROOT) { $env:FCC_PROJECTS_ROOT } else { Join-Path $env:USERPROFILE 'projects' }),
    [string] $OutputFile = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-ProjectDirectory {
    param([string] $Path)
    return (Test-Path -LiteralPath $Path -PathType Container)
}

function Write-SelectedPath {
    param([string] $Path)
    if ($OutputFile) {
        Set-Content -LiteralPath $OutputFile -Value $Path -Encoding ascii -NoNewline
    } else {
        Write-Output $Path
    }
}

if (-not (Test-ProjectDirectory $ProjectsRoot)) {
    try {
        New-Item -ItemType Directory -Path $ProjectsRoot -Force | Out-Null
        Write-Host "Created projects folder: $ProjectsRoot"
    } catch {
        Write-Error "Could not create projects folder: $ProjectsRoot ($($_.Exception.Message))"
        exit 1
    }
}

$projects = @(Get-ChildItem -LiteralPath $ProjectsRoot -Directory |
    Where-Object { -not $_.Attributes.HasFlag([IO.FileAttributes]::Hidden) } |
    Sort-Object Name)

if ($projects.Count -eq 0) {
    Write-Error "No project folders found in: $ProjectsRoot"
    exit 1
}

Write-Host ''
Write-Host 'Free Claude Code - choose a project'
Write-Host "Root: $ProjectsRoot"
Write-Host ''

for ($i = 0; $i -lt $projects.Count; $i++) {
    Write-Host ('  [{0,2}] {1}' -f ($i + 1), $projects[$i].Name)
}

Write-Host ''
Write-Host '  [ B] Browse for another folder...'
Write-Host '  [ 0] Type a path manually'
Write-Host ''

$choice = Read-Host "Enter number (1-$($projects.Count)), B, or 0"

$selected = $null
switch -Regex ($choice.Trim()) {
    '^[Bb]$' {
        Add-Type -AssemblyName System.Windows.Forms
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = 'Select the project folder for Claude Code'
        $dialog.SelectedPath = $ProjectsRoot
        $dialog.ShowNewFolderButton = $false
        if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
            Write-Host 'Cancelled.'
            exit 2
        }
        $selected = $dialog.SelectedPath
    }
    '^0$' {
        $typed = Read-Host 'Full path to project folder'
        if (-not $typed.Trim()) {
            Write-Host 'Cancelled.'
            exit 2
        }
        $selected = $typed.Trim()
    }
    default {
        if (-not ($choice -match '^\d+$')) {
            Write-Error "Invalid choice: $choice"
            exit 1
        }
        $index = [int]$choice - 1
        if ($index -lt 0 -or $index -ge $projects.Count) {
            Write-Error "Invalid choice: $choice (use 1-$($projects.Count), B, or 0)"
            exit 1
        }
        $selected = $projects[$index].FullName
    }
}

$selected = [IO.Path]::GetFullPath($selected)
if (-not (Test-ProjectDirectory $selected)) {
    Write-Error "Not a folder: $selected"
    exit 1
}

Write-Host ''
Write-Host "Opening: $selected"
Write-SelectedPath -Path $selected
exit 0
