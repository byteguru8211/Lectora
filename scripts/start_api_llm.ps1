# Запуск FreeDeepseekAPI (DeepSeek Web -> OpenAI-совместимый прокси) в фоне.
# Использование: powershell -ExecutionPolicy Bypass -File scripts\start_api_llm.ps1
$root = Split-Path -Parent $PSScriptRoot
$apiDir = Join-Path $root "tools\FreeDeepseekAPI"
$logs = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null

if (-not (Test-Path (Join-Path $apiDir "server.js"))) {
  Write-Error "FreeDeepseekAPI не найден: tools\FreeDeepseekAPI"
  exit 1
}

try {
  $health = Invoke-RestMethod "http://127.0.0.1:9655/health" -TimeoutSec 3
  $ready = @($health.accounts | Where-Object { $_.ready }).Count
  Write-Host "FreeDeepseekAPI уже запущен (аккаунтов готово: $ready)"
  exit 0
} catch { }

$node = (Get-Command node -ErrorAction SilentlyContinue)
if (-not $node) { Write-Error "Node.js 18+ не найден в PATH"; exit 1 }

$env:NON_INTERACTIVE = "1"
Start-Process -FilePath $node.Source `
  -ArgumentList "server.js" `
  -WorkingDirectory $apiDir `
  -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $logs "deepseek-api.out.log") `
  -RedirectStandardError (Join-Path $logs "deepseek-api.err.log")

Write-Host "Запускаем FreeDeepseekAPI на 127.0.0.1:9655…"
for ($i = 0; $i -lt 20; $i++) {
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-RestMethod "http://127.0.0.1:9655/health" -TimeoutSec 3
    $ready = @($health.accounts | Where-Object { $_.ready }).Count
    Write-Host "DeepSeek API готов: $($health.status), аккаунтов готово: $ready, моделей: $($health.models.Count)"
    exit 0
  } catch { }
}
Write-Error "FreeDeepseekAPI не ответил за 40 секунд, см. data\logs\deepseek-api.err.log"
exit 1
