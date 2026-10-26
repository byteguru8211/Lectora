# Запуск backend-сервера Lectora (waitress) в фоне.
# Использование:  powershell -ExecutionPolicy Bypass -File scripts\start_server.ps1
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$backend = Join-Path $root "backend"
$logs = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null

if (-not (Test-Path $python)) { Write-Error "Не найдено виртуальное окружение .venv — запустите scripts\setup.ps1"; exit 1 }

Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*serve.py*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Start-Process -FilePath $python `
  -ArgumentList "serve.py" `
  -WorkingDirectory $backend `
  -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $logs "server.out.log") `
  -RedirectStandardError (Join-Path $logs "server.err.log")

Start-Sleep -Seconds 6
try {
  $health = Invoke-RestMethod "http://127.0.0.1:8000/api/health" -TimeoutSec 20
  Write-Host "Lectora: $($health.status)  (база: $($health.checks.database.ok), LLM: $($health.checks.llm.available))"
  Write-Host "Откройте http://127.0.0.1:8000"
} catch {
  Write-Error "Сервер не ответил. Смотрите data\logs\server.err.log"
}
