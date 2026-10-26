# Запуск всего стека Lectora: PostgreSQL + локальная LLM + backend.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path "frontend\dist\index.html")) {
  Write-Host "Сборка фронтенда (первый запуск)…" -ForegroundColor Cyan
  Push-Location frontend
  & npm.cmd run build
  Pop-Location
}

Write-Host "1/3 PostgreSQL" -ForegroundColor Cyan
& powershell -ExecutionPolicy Bypass -File scripts\start_pg.ps1

Write-Host "`n2/3 Локальная LLM" -ForegroundColor Cyan
& powershell -ExecutionPolicy Bypass -File scripts\start_llm.ps1

Write-Host "`n3/3 Backend" -ForegroundColor Cyan
& powershell -ExecutionPolicy Bypass -File scripts\start_server.ps1

Write-Host "`nLectora готова: http://127.0.0.1:8000" -ForegroundColor Green
Start-Process "http://127.0.0.1:8000"
