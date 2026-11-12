$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$stateDirectory = Join-Path $PSScriptRoot '.local'
$pidFile = Join-Path $stateDirectory 'queryvault-server.pid'
$stopFile = Join-Path $stateDirectory 'queryvault-server.stop'
$port = 8000
if ($env:QUERYVAULT_LOCAL_PORT) { $port = [int]$env:QUERYVAULT_LOCAL_PORT }

if (-not (Test-Path -LiteralPath $pidFile)) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -Method Get -TimeoutSec 2
        if ($health.mode -eq 'local' -and $health.database -eq 'connected') {
            Write-Host "An unmanaged QueryVault server is responding on port $port. Stop it with Ctrl+C in its original PowerShell window."
            return
        }
    } catch {}
    Write-Host 'No managed QueryVault server is running.'
    return
}

$serverPid = 0
if (-not [int]::TryParse((Get-Content -LiteralPath $pidFile -Raw), [ref]$serverPid) -or $serverPid -le 0) {
    throw 'The QueryVault PID file is invalid; inspect .local before stopping anything.'
}

$process = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
if (-not $process) {
    Remove-Item -LiteralPath $pidFile -Force
    Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
    Write-Host 'Removed a stale QueryVault PID record; no process was stopped.'
    return
}

# The server watches this local marker and sets Uvicorn's should_exit flag,
# which runs the normal ASGI lifespan shutdown. This script never force-kills it.
[System.IO.File]::WriteAllText($stopFile, 'stop', [System.Text.Encoding]::ASCII)
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    if (-not (Get-Process -Id $serverPid -ErrorAction SilentlyContinue)) {
        Write-Host 'QueryVault stopped gracefully.'
        return
    }
    Start-Sleep -Milliseconds 250
}

throw "QueryVault process $serverPid did not stop within 30 seconds. It was not force-killed; inspect .local\queryvault-server.stderr.log."
