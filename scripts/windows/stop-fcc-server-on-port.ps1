param(
    [Parameter(Mandatory = $true)]
    [int]$Port,

    [Parameter(Mandatory = $true)]
    [string]$Repo
)

$ErrorActionPreference = "Stop"

function Normalize-PathText {
    param([string]$PathText)

    return [System.IO.Path]::GetFullPath($PathText).TrimEnd("\")
}

function Test-IsSepccServer {
    param(
        [object]$ProcessInfo,
        [string]$RepoRoot
    )

    $commandLine = [string]$ProcessInfo.CommandLine
    if (-not $commandLine) {
        return $false
    }

    $isConsoleScript = $commandLine.IndexOf("fcc-server", [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    $isPythonRunner = (
        $commandLine.IndexOf("run-entrypoint.py", [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        $commandLine.IndexOf(" serve", [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    )

    return (
        $commandLine.IndexOf($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        ($isConsoleScript -or $isPythonRunner)
    )
}

$repoRoot = Normalize-PathText -PathText $Repo

try {
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
} catch {
    exit 0
}

$serverPids = @()
foreach ($connection in $connections) {
    $owningPid = [int]$connection.OwningProcess
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $owningPid" -ErrorAction SilentlyContinue
    if ($null -ne $processInfo -and (Test-IsSepccServer -ProcessInfo $processInfo -RepoRoot $repoRoot)) {
        $serverPids += $owningPid
    }
}

$serverPids = @($serverPids | Sort-Object -Unique)
if ($serverPids.Count -eq 0) {
    exit 0
}

Write-Host "Stopping existing SEPCC server on port $Port..."
foreach ($serverPid in $serverPids) {
    Stop-Process -Id $serverPid -Force -ErrorAction Stop
}

for ($i = 0; $i -lt 20; $i++) {
    $stillListening = @()
    try {
        $stillListening = @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
                Where-Object { $serverPids -contains [int]$_.OwningProcess }
        )
    } catch {
        $stillListening = @()
    }

    if ($stillListening.Count -eq 0) {
        exit 0
    }

    Start-Sleep -Milliseconds 250
}

Write-Error "Timed out waiting for the existing SEPCC server on port $Port to stop."
exit 1
