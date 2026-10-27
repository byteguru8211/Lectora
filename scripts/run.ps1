# Запуск компонентов PowerShell явно в отдельном процессе.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path (Join-Path $root ".env"))) {
  Copy-Item (Join-Path $root ".env.example") (Join-Path $root ".env")
  Write-Host "Создан .env из .env.example" -ForegroundColor Yellow
}

function Invoke-ProjectScript([string]$Name) {
  $path = Join-Path $PSScriptRoot $Name
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $path
  if ($LASTEXITCODE -ne 0) {
    throw "Project script $Name exited with code $LASTEXITCODE"
  }
}

$distIndex = Join-Path $root "frontend\dist\index.html"
if (-not (Test-Path $distIndex)) {
  $frontend = Join-Path $root "frontend"
  if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "Устанавливаем зависимости фронтенда (первый запуск)…" -ForegroundColor Cyan
    Push-Location $frontend
    try {
      & npm.cmd install --no-fund --no-audit
      if ($LASTEXITCODE -ne 0) { throw "npm install завершился ошибкой" }
    } finally {
      Pop-Location
    }
  }
  Write-Host "Сборка фронтенда (первый запуск)…" -ForegroundColor Cyan
  Push-Location $frontend
  try {
    if (Get-Command pnpm.cmd -ErrorAction SilentlyContinue) {
      & pnpm.cmd run build
    } else {
      & npm.cmd run build
    }
    if ($LASTEXITCODE -ne 0) { throw "Сборка фронтенда завершилась ошибкой" }
  } finally {
    Pop-Location
  }
}

Write-Host "1/4 PostgreSQL" -ForegroundColor Cyan
Invoke-ProjectScript "start_pg.ps1"

Write-Host "`n2/4 Локальная LLM" -ForegroundColor Cyan
Invoke-ProjectScript "start_llm.ps1"

$authFile = Join-Path $root "tools\FreeDeepseekAPI\deepseek-auth.json"
if (Test-Path $authFile) {
  Write-Host "`n3/4 DeepSeek API (FreeDeepseekAPI, опционально)" -ForegroundColor Cyan
  try {
    Invoke-ProjectScript "start_api_llm.ps1"
  } catch {
    Write-Warning "DeepSeek API не запустился — режим API будет недоступен. $_"
  }
} else {
  Write-Host "`n3/4 DeepSeek API пропущен: нет tools\FreeDeepseekAPI\deepseek-auth.json" -ForegroundColor DarkGray
}

Write-Host "`n4/4 Backend" -ForegroundColor Cyan
Invoke-ProjectScript "start_server.ps1"

Write-Host "`nLectora готова: http://127.0.0.1:8000" -ForegroundColor Green
Start-Process -FilePath "http://127.0.0.1:8000"


