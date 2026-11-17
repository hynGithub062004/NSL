param([string]$Gns3VmIp = "")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path ".venv\Scripts\python.exe")) { py -3.11 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -r web\requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Python dependencies failed to install" }
if ($Gns3VmIp) {
  Write-Host "Open a SECOND PowerShell and run: ssh -N -L 18018:127.0.0.1:8018 gns3@$Gns3VmIp"
}
$env:TV4_CORE_URL = "http://127.0.0.1:18018"
Write-Host "Web: http://127.0.0.1:8080"
& .\.venv\Scripts\python.exe -m uvicorn web.app:app --host 127.0.0.1 --port 8080
