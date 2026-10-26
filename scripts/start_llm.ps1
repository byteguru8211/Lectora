# Запуск локальной LLM (llama.cpp, Vulkan-сборка — работает на любом GPU).
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root "tools\llama-vulkan\llama-server.exe"
$model = Join-Path $root "models\llm\Qwen2.5-7B-Instruct-Q4_K_M.gguf"
$logs = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null

if (-not (Test-Path $exe)) { Write-Error "llama-server не найден: tools\llama-vulkan"; exit 1 }
if (-not (Test-Path $model)) { Write-Error "Модель не найдена: models\llm\Qwen2.5-7B-Instruct-Q4_K_M.gguf"; exit 1 }

try {
  Invoke-RestMethod "http://127.0.0.1:8080/v1/models" -TimeoutSec 3 | Out-Null
  Write-Host "LLM уже запущена на 127.0.0.1:8080"
  exit 0
} catch { }

Start-Process -FilePath $exe -ArgumentList @(
  "-m", "`"$model`"",
  "-c", "8192",
  "-ngl", "99",
  "--host", "127.0.0.1",
  "--port", "8080",
  "-t", "8",
  "--alias", "qwen2.5-7b-instruct",
  "--no-warmup"
) -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $logs "llm.out.log") `
  -RedirectStandardError (Join-Path $logs "llm.err.log")

Write-Host "Загружаем модель (10-20 секунд)…"
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Seconds 2
  try {
    $models = Invoke-RestMethod "http://127.0.0.1:8080/v1/models" -TimeoutSec 3
    if ($models.data) { Write-Host "LLM готова: $($models.data[0].id)"; exit 0 }
  } catch { }
}
Write-Error "LLM не ответила за 80 секунд, см. data\logs\llm.err.log"
exit 1
