$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$stateDirectory = Join-Path $PSScriptRoot '.local'
$pidFile = Join-Path $stateDirectory 'queryvault-server.pid'
$stopFile = Join-Path $stateDirectory 'queryvault-server.stop'
$stdinFile = Join-Path $stateDirectory 'queryvault-server.stdin'
$stdoutFile = Join-Path $stateDirectory 'queryvault-server.stdout.log'
$stderrFile = Join-Path $stateDirectory 'queryvault-server.stderr.log'
$port = 8000
if ($env:QUERYVAULT_LOCAL_PORT) {
    $port = 0
    if (-not [int]::TryParse($env:QUERYVAULT_LOCAL_PORT, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        throw 'QUERYVAULT_LOCAL_PORT must be a port between 1 and 65535.'
    }
}
$healthUri = "http://127.0.0.1:$port/health"

function Test-QueryVaultHealth {
    try {
        $health = Invoke-RestMethod -Uri $healthUri -Method Get -TimeoutSec 2
        return $health.mode -eq 'local' -and $health.database -eq 'connected'
    } catch {
        return $false
    }
}

# Reuse only servers started by this launcher. An older foreground Uvicorn
# process has no stop-file watcher, so don't imply that stop.ps1 controls it.
if (Test-QueryVaultHealth) {
    $existingPid = 0
    if (Test-Path -LiteralPath $pidFile) {
        [void][int]::TryParse((Get-Content -LiteralPath $pidFile -Raw), [ref]$existingPid)
    }
    if ($existingPid -gt 0 -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        Write-Host "QueryVault is already healthy at http://127.0.0.1:$port (process $existingPid)."
        Write-Host 'Use .\stop.ps1 to stop it gracefully.'
        return
    }
    throw "An older unmanaged QueryVault process is already healthy on port $port. Stop it with Ctrl+C in its original PowerShell window, then run .\start.ps1 again."
}

& $python (Join-Path $PSScriptRoot 'setup_local.py')
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL setup failed' }

New-Item -ItemType Directory -Force -Path $stateDirectory | Out-Null
if (Test-Path -LiteralPath $pidFile) {
    $recordedPid = 0
    [void][int]::TryParse((Get-Content -LiteralPath $pidFile -Raw), [ref]$recordedPid)
    if ($recordedPid -gt 0 -and (Get-Process -Id $recordedPid -ErrorAction SilentlyContinue)) {
        throw "QueryVault server process $recordedPid is still present but health is unavailable. Inspect .local\queryvault-server.stderr.log before starting another instance."
    }
    Remove-Item -LiteralPath $pidFile -Force
}
if (Test-Path -LiteralPath $stopFile) { Remove-Item -LiteralPath $stopFile -Force }

# An empty redirected stdin deliberately gives Python EOF. Uvicorn does not use
# stdin as its lifetime signal; the hidden child is detached from this shell's
# console and the stop-file watcher provides an explicit graceful stop path.
$emptyInput = [System.IO.File]::Create($stdinFile)
$emptyInput.Dispose()
$launcher = Join-Path $PSScriptRoot 'local_server.py'
$arguments = '-u "' + $launcher + '" ' + $port
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $PSScriptRoot `
    -WindowStyle Hidden -PassThru -RedirectStandardInput $stdinFile `
    -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile

$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    $recordedPid = 0
    if (Test-Path -LiteralPath $pidFile) {
        [void][int]::TryParse((Get-Content -LiteralPath $pidFile -Raw), [ref]$recordedPid)
    }
    $recordedProcess = if ($recordedPid -gt 0) { Get-Process -Id $recordedPid -ErrorAction SilentlyContinue } else { $null }
    if ((Test-QueryVaultHealth) -and $recordedProcess) {
        Write-Host "QueryVault is healthy at http://127.0.0.1:$port and will keep running after this PowerShell command returns."
        Write-Host "Server process: $recordedPid. Logs: .local\queryvault-server.stderr.log"
        Write-Host 'Use .\stop.ps1 to request graceful shutdown.'
        return
    }
    if ($process.HasExited) {
        if (Test-QueryVaultHealth) {
            Write-Host "QueryVault is already healthy at http://127.0.0.1:$port; another instance owns this port."
            Write-Host 'No second server process was left running.'
            return
        }
        throw "QueryVault exited during startup (code $($process.ExitCode)). See .local\queryvault-server.stderr.log."
    }
    Start-Sleep -Milliseconds 300
}

throw 'QueryVault did not become healthy within 30 seconds. The process was left running for inspection; see .local\queryvault-server.stderr.log.'
