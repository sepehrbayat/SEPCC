# Pick a project folder. First run: choose a projects root folder and save it.
# Subsequent runs: use the saved root. Always pick a project INSIDE the root.
param(
    [string] $OutputFile = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ConfigDir = Join-Path $env:APPDATA 'SEPCC'
$ConfigFile = Join-Path $ConfigDir 'projects-root.txt'
$LegacyDefault = Join-Path $env:USERPROFILE 'projects'
$SuggestedDefault = Join-Path $env:USERPROFILE 'Projects'

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
function Test-Directory {
    param([string] $Path)
    if (-not $Path) { return $false }
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

function Test-WriteAccess {
    param([string] $ParentPath)
    if (-not (Test-Directory $ParentPath)) { return $false }
    try {
        $testFile = Join-Path $ParentPath '.sepcc-write-test'
        [IO.File]::WriteAllText($testFile, 'ok')
        Remove-Item $testFile -Force
        return $true
    } catch {
        return $false
    }
}

function Test-LocalDisk {
    param([string] $Path)
    try {
        $root = [IO.Path]::GetPathRoot($Path)
        $drive = (Get-PSDrive -Name $root.TrimEnd('\:') -ErrorAction Stop)
        return ($drive.Provider.Name -eq 'FileSystem')
    } catch {
        return $false
    }
}

function Save-ProjectsRoot {
    param([string] $Path)
    New-Item -Path $ConfigDir -ItemType Directory -Force -ErrorAction Stop | Out-Null
    $normalized = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    # Atomic write: temp file then rename
    $tmp = Join-Path $ConfigDir 'projects-root.tmp'
    Set-Content -LiteralPath $tmp -Value $normalized -Encoding ascii -NoNewline
    if (Test-Path -LiteralPath $ConfigFile) {
        [IO.File]::Replace($tmp, $ConfigFile, $null)
    } else {
        Move-Item -LiteralPath $tmp -Destination $ConfigFile -Force
    }
}

function Load-ProjectsRoot {
    if (-not (Test-Path $ConfigFile)) { return $null }
    try {
        $raw = (Get-Content -LiteralPath $ConfigFile -Raw -Encoding ascii).Trim()
        if ($raw -and (Test-Directory $raw)) {
            return [IO.Path]::GetFullPath($raw).TrimEnd('\')
        }
        # Stored path is gone — clean up so we re-prompt
        Remove-Item $ConfigFile -Force -ErrorAction SilentlyContinue
        return $null
    } catch {
        return $null
    }
}

# --------------------------------------------------------------------
# Phase 1: resolve projects root (first-run wizard or load from config)
# --------------------------------------------------------------------
$ProjectsRoot = $null

# Env var override always wins (advanced users who want full control)
if ($env:FCC_PROJECTS_ROOT) {
    $ProjectsRoot = [IO.Path]::GetFullPath($env:FCC_PROJECTS_ROOT).TrimEnd('\')
} else {
    $ProjectsRoot = Load-ProjectsRoot
}

# No saved root — run first-run setup
if (-not $ProjectsRoot) {
    # Detect legacy default with existing projects — adopt silently
    if ((Test-Directory $LegacyDefault) -and (Test-WriteAccess $LegacyDefault)) {
        $existing = @(Get-ChildItem -LiteralPath $LegacyDefault -Directory -ErrorAction SilentlyContinue |
            Where-Object { -not $_.Attributes.HasFlag([IO.FileAttributes]::Hidden) })
        if ($existing.Count -gt 0) {
            Save-ProjectsRoot $LegacyDefault
            $ProjectsRoot = $LegacyDefault
        }
    }
}

if (-not $ProjectsRoot) {
    Write-Host ''
    Write-Host '============================================================'
    Write-Host '  SEPCC — First-Time Setup'
    Write-Host '============================================================'
    Write-Host ''
    Write-Host 'Where should your projects live?'
    Write-Host ''
    Write-Host "  Suggested: $SuggestedDefault"
    Write-Host ''
    Write-Host '  [Enter]  Accept the suggestion above'
    Write-Host '  [    B]  Browse for a different folder'
    Write-Host '  [    0]  Type a path manually'
    Write-Host ''

    $setupChoice = Read-Host "Press Enter, B, or 0"
    $chosenRoot = $null

    switch -Regex ($setupChoice.Trim()) {
        '^[Bb]$' {
            Add-Type -AssemblyName System.Windows.Forms
            $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
            $dialog.Description = 'Choose where your SEPCC project folders will live'
            $dialog.SelectedPath = [Environment]::GetFolderPath('UserProfile')
            $dialog.ShowNewFolderButton = $true
            if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
                Write-Host 'Setup cancelled.'
                exit 2
            }
            $chosenRoot = $dialog.SelectedPath
        }
        '^0$' {
            $typed = Read-Host 'Full path for projects root'
            if (-not $typed.Trim()) {
                Write-Host 'Setup cancelled.'
                exit 2
            }
            $chosenRoot = $typed.Trim()
        }
        default {
            # Enter or anything else → accept suggestion
            $chosenRoot = $SuggestedDefault
        }
    }

    $chosenRoot = [IO.Path]::GetFullPath($chosenRoot).TrimEnd('\')

    # Validate
    if (-not (Test-LocalDisk $chosenRoot)) {
        Write-Error "Projects root must be on a local disk: $chosenRoot"
        exit 1
    }

    # Create the folder if it doesn't exist
    if (-not (Test-Directory $chosenRoot)) {
        Write-Host ''
        $confirm = Read-Host "Create '$chosenRoot' as your projects folder? [Y/n]"
        if ($confirm.Trim() -and $confirm.Trim() -notmatch '^[Yy]') {
            Write-Host 'Setup cancelled. Run again when ready.'
            exit 2
        }
        try {
            New-Item -ItemType Directory -Path $chosenRoot -Force | Out-Null
            Write-Host "Created: $chosenRoot"
        } catch {
            Write-Error "Could not create folder: $chosenRoot ($($_.Exception.Message))"
            exit 1
        }
    }

    if (-not (Test-WriteAccess $chosenRoot)) {
        Write-Error "Cannot write to: $chosenRoot. Pick a folder with write access."
        exit 1
    }

    Save-ProjectsRoot $chosenRoot
    $ProjectsRoot = $chosenRoot
    Write-Host "Projects root saved: $ProjectsRoot"
    Write-Host '(To change it later, delete %APPDATA%\SEPCC\projects-root.txt)'
}

# --------------------------------------------------------------------
# Phase 2: pick a project INSIDE the projects root
# --------------------------------------------------------------------
$projects = @(Get-ChildItem -LiteralPath $ProjectsRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { -not $_.Attributes.HasFlag([IO.FileAttributes]::Hidden) } |
    Sort-Object Name)

Write-Host ''
Write-Host 'SEPCC — Choose a project'
Write-Host "Projects root: $ProjectsRoot"
Write-Host ''

if ($projects.Count -eq 0) {
    Write-Host '  No project folders found yet.'
    Write-Host ''
    Write-Host '  What to do:'
    Write-Host '    1. Create a subfolder here for your project, then re-launch.'
    Write-Host '    2. Copy an existing project folder into this location.'
    Write-Host '    3. Use B to browse to a project outside this root (not recommended).'
    Write-Host ''
}

for ($i = 0; $i -lt $projects.Count; $i++) {
    Write-Host ('  [{0,2}] {1}' -f ($i + 1), $projects[$i].Name)
}

Write-Host ''
if ($projects.Count -gt 0) {
    Write-Host '  [    B]  Browse for another folder'
    Write-Host '  [    0]  Type a path manually'
    if (-not $env:FCC_PROJECTS_ROOT) {
        Write-Host '  [    R]  Change projects root folder'
    }
    $promptMsg = "Enter number (1-$($projects.Count)), B, 0$(if (-not $env:FCC_PROJECTS_ROOT) { ', R' } else { '' })"
} else {
    Write-Host '  [    B]  Browse for a project folder'
    Write-Host '  [    0]  Type a path manually'
    if (-not $env:FCC_PROJECTS_ROOT) {
        Write-Host '  [    R]  Change projects root folder'
    }
    $promptMsg = "Enter B, 0$(if (-not $env:FCC_PROJECTS_ROOT) { ', R' } else { '' })"
}
Write-Host ''

$choice = Read-Host $promptMsg

$selected = $null
switch -Regex ($choice.Trim()) {
    '^[Bb]$' {
        Add-Type -AssemblyName System.Windows.Forms
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = 'Select the project folder for Claude Code'
        $dialog.SelectedPath = $ProjectsRoot
        $dialog.ShowNewFolderButton = $true
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
    '^[Rr]$' {
        if ($env:FCC_PROJECTS_ROOT) {
            Write-Error 'Cannot change root when FCC_PROJECTS_ROOT is set.'
            exit 1
        }
        Remove-Item $ConfigFile -Force -ErrorAction SilentlyContinue
        Write-Host 'Projects root cleared. Re-launch to pick a new one.'
        exit 2
    }
    default {
        if (-not ($choice -match '^\d+$')) {
            Write-Error "Invalid choice: $choice"
            exit 1
        }
        $index = [int]$choice - 1
        if ($index -lt 0 -or $index -ge $projects.Count) {
            Write-Error "Invalid choice: $choice (use 1-$($projects.Count))"
            exit 1
        }
        $selected = $projects[$index].FullName
    }
}

$selected = [IO.Path]::GetFullPath($selected).TrimEnd('\')

# Guard: don't let the projects root itself be treated as a project
if ($selected -eq $ProjectsRoot) {
    Write-Error "Cannot use the projects root itself as a project. Create a subfolder inside '$ProjectsRoot' instead."
    exit 1
}

# Warn if selected path is outside the projects root
if (-not $selected.StartsWith($ProjectsRoot, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host ''
    Write-Host "Note: '$selected' is outside your projects root ($ProjectsRoot)."
    Write-Host 'Consider moving it into the projects root so the picker finds it next time.'
    Write-Host ''
}

if (-not (Test-Directory $selected)) {
    Write-Error "Not a folder: $selected"
    exit 1
}

Write-Host ''
Write-Host "Opening: $selected"
Write-SelectedPath -Path $selected
exit 0
