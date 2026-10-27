# Останавливает backend, локальную LLM, FreeDeepseekAPI и PostgreSQL.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "Останавливаем backend…"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*serve.py*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host "Останавливаем LLM…"
Get-Process -Name "llama-server" -ErrorAction SilentlyContinue |
  Stop-Process -Force -ErrorAction SilentlyContinue

$apiConn = Get-NetTCPConnection -LocalPort 9655 -State Listen -ErrorAction SilentlyContinue |
  Select-Object -First 1
if ($apiConn) {
  $apiProcess = Get-Process -Id $apiConn.OwningProcess -ErrorAction SilentlyContinue
  if ($apiProcess -and $apiProcess.ProcessName -eq "node") {
    Write-Host "Останавливаем FreeDeepseekAPI…"
    Stop-Process -Id $apiProcess.Id -Force -ErrorAction SilentlyContinue
  }
}

Write-Host "Останавливаем PostgreSQL…"
$pgCtl = Join-Path $root "tools\pgsql\bin\pg_ctl.exe"
$pgData = Join-Path $root "data\pgdata"
if (Test-Path $pgCtl) {
  & $pgCtl -D $pgData stop -m fast | Out-Null
}

Write-Host "Готово."

