# Запуск компонентов PowerShell явно в отдельном процессе.
param(
  [ValidateSet("auto", "api", "local", "both")]
  [string]$LlmBackend = "auto"
)
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

$llmModeLine = Get-Content (Join-Path $root ".env") | Where-Object { $_ -match '^LLM_MODE=' } | Select-Object -First 1
$llmMode = if ($llmModeLine) { ($llmModeLine -split '=', 2)[1].Trim().ToLowerInvariant() } else { "local" }
$authFile = Join-Path $root "tools\FreeDeepseekAPI\deepseek-auth.json"
$apiInstalled = Test-Path $authFile

if ($LlmBackend -eq "auto") {
  $defaultChoice = if ($llmMode -eq "api" -and $apiInstalled) { "1" } else { "2" }
  Write-Host "`nВыберите движок конспекта и вопросов:" -ForegroundColor Cyan
  if ($apiInstalled) {
    Write-Host "  1 — DeepSeek API (рекомендуется для видеокарт с 6 ГБ VRAM)"
  } else {
    Write-Host "  1 — DeepSeek API (недоступен: сначала выполните npm run auth)" -ForegroundColor DarkGray
  }
  Write-Host "  2 — Локальная Qwen (без интернета, занимает около 5–6 ГБ VRAM)"
  Write-Host "  3 — Обе модели (резервирование, рекомендуется от 8 ГБ VRAM)"
  $answer = Read-Host "Выбор [$defaultChoice]"
  if ([string]::IsNullOrWhiteSpace($answer)) { $answer = $defaultChoice }
  $LlmBackend = switch ($answer.Trim()) {
    "1" { "api" }
    "2" { "local" }
    "3" { "both" }
    default { if ($defaultChoice -eq "1") { "api" } else { "local" } }
  }
}

if ($LlmBackend -eq "api" -and -not $apiInstalled) {
  Write-Warning "DeepSeek API не авторизован — переключаемся на локальную Qwen"
  $LlmBackend = "local"
}
if ($LlmBackend -eq "both" -and -not $apiInstalled) {
  Write-Warning "DeepSeek API не авторизован — будет запущена только локальная Qwen"
  $LlmBackend = "local"
}
if ($LlmBackend -eq "both") {
  Write-Warning "Одновременный запуск двух LLM может переполнить VRAM на видеокартах с 6 ГБ"
}

$apiReady = $false
if ($LlmBackend -in @("api", "both") -and $apiInstalled) {
  Write-Host "`n2/4 DeepSeek API (FreeDeepseekAPI, опционально)" -ForegroundColor Cyan
  try {
    Invoke-ProjectScript "start_api_llm.ps1"
    $apiReady = $true
  } catch {
    Write-Warning "DeepSeek API не запустился — режим API будет недоступен. $_"
  }
} else {
  Write-Host "`n2/4 DeepSeek API пропущен по выбору пользователя" -ForegroundColor DarkGray
}

if ($LlmBackend -in @("local", "both") -or ($LlmBackend -eq "api" -and -not $apiReady)) {
  Write-Host "`n3/4 Локальная LLM" -ForegroundColor Cyan
  Invoke-ProjectScript "start_llm.ps1"
} else {
  Write-Host "`n3/4 Локальная LLM пропущена по выбору пользователя — сохраняем VRAM для Whisper и BGE" -ForegroundColor DarkGray
}

Write-Host "`n4/4 Backend" -ForegroundColor Cyan
Invoke-ProjectScript "start_server.ps1"

Write-Host "`nLectora готова: http://127.0.0.1:8000" -ForegroundColor Green
Start-Process -FilePath "http://127.0.0.1:8000"


