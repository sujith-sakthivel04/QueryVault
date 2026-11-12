$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { python -m venv .venv }
& .\.venv\Scripts\python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
& .\.venv\Scripts\python setup_local.py
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL setup failed' }
Push-Location frontend
try {
    npm.cmd ci --legacy-peer-deps
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies failed' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Pop-Location }
Write-Output 'Setup complete. Run .\start.ps1 to open the local application.'
