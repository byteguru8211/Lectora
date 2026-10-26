# Останавливает backend, локальную LLM и PostgreSQL.
$root = Split-Path -Parent $PSScriptRoot

Write-Host "Останавливаем backend…"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*serve.py*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host "Останавливаем LLM…"
Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host "Останавливаем PostgreSQL…"
$pgCtl = Join-Path $root "tools\pgsql\bin\pg_ctl.exe"
if (Test-Path $pgCtl) {
  & $pgCtl -D (Join-Path $root "data\pgdata") stop -m fast | Out-Null
}

Write-Host "Готово."
