# Inicia Ad-Spy en http://localhost:8000  (clic derecho > Ejecutar con PowerShell)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "No existe el entorno .venv. Corre primero la instalacion." -ForegroundColor Red; pause; exit 1 }
Write-Host "Abriendo http://localhost:8000 ..." -ForegroundColor Green
Start-Process "http://localhost:8000"
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000
