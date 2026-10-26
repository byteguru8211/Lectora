# Подготовка окружения Lectora: venv, зависимости, база, фронтенд.
# Запуск:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Write-Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }

Write-Step "Проверяем Python и Node"
$pythonOk = $false
foreach ($candidate in @("python", "py")) {
  try {
    $version = & $candidate -c "import sys; print('.'.join(map(str, sys.version_info[:2])))" 2>$null
    if ($version -eq "3.12") { $pythonOk = $true; Write-Host "Python $version OK"; break }
  } catch { }
}
if (-not $pythonOk) { Write-Warning "Нужен Python 3.12 в PATH (текущая версия может не подойти для vosk/torch)" }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Write-Error "Node.js не найден в PATH"; exit 1 }
Write-Host "Node $(node -v) OK"

Write-Step "Виртуальное окружение и зависимости Python"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  python -m venv .venv
}
& ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& ".venv\Scripts\python.exe" -m pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu
& ".venv\Scripts\python.exe" -m pip install --quiet -r backend\requirements.txt
Write-Host "Зависимости установлены"

Write-Step "Конфигурация"
if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "Создан .env из .env.example"
} else {
  Write-Host ".env уже существует — не трогаем"
}

Write-Step "Проверяем инструменты и модели"
$checks = @(
  @{ Path = "tools\ffmpeg\bin\ffmpeg.exe"; Hint = "ffmpeg.exe и ffprobe.exe в tools\ffmpeg\bin" },
  @{ Path = "tools\pgsql\bin\postgres.exe"; Hint = "PostgreSQL binaries в tools\pgsql" },
  @{ Path = "models\vosk\vosk-model-ru-0.42"; Hint = "Vosk ru-0.42 в models\vosk" },
  @{ Path = "models\embeddings\bge-m3"; Hint = "bge-m3 в models\embeddings" },
  @{ Path = "models\reranker\bge-reranker-v2-m3"; Hint = "bge-reranker-v2-m3 в models\reranker" },
  @{ Path = "models\llm\Qwen2.5-7B-Instruct-Q4_K_M.gguf"; Hint = "GGUF-модель в models\llm" },
  @{ Path = "tools\llama-vulkan\llama-server.exe"; Hint = "llama.cpp (Vulkan) в tools\llama-vulkan" }
)
$missing = @()
foreach ($check in $checks) {
  if (Test-Path $check.Path) { Write-Host "  OK   $($check.Path)" -ForegroundColor Green }
  else { Write-Host "  НЕТ  $($check.Path)" -ForegroundColor Yellow; $missing += $check.Hint }
}

Write-Step "База данных"
if ((Test-Path "tools\pgsql\bin\initdb.exe") -and -not (Test-Path "data\pgdata\PG_VERSION")) {
  New-Item -ItemType Directory -Force "data" | Out-Null
  Set-Content -Path "data\pgpass.txt" -Value "lectora" -NoNewline -Encoding ASCII
  & "tools\pgsql\bin\initdb.exe" -D "data\pgdata" -U lectora --auth=scram-sha-256 --pwfile="data\pgpass.txt" -E UTF8 --locale=C | Out-Null
  Remove-Item "data\pgpass.txt" -Force
  Add-Content -Path "data\pgdata\postgresql.conf" -Value "`nport = 5433`nlisten_addresses = '127.0.0.1'`nmax_connections = 60`nshared_buffers = 256MB`n"
  Write-Host "Кластер PostgreSQL инициализирован"
} elseif (Test-Path "data\pgdata\PG_VERSION") {
  Write-Host "Кластер PostgreSQL уже существует"
} else {
  Write-Host "Пропускаем: PostgreSQL не установлен"
}

if (Test-Path "tools\pgsql\bin\pg_isready.exe") {
  & powershell -ExecutionPolicy Bypass -File scripts\start_pg.ps1
  $env:PGPASSWORD = "lectora"
  $exists = & "tools\pgsql\bin\psql.exe" -h 127.0.0.1 -p 5433 -U lectora -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='lectora'" 2>$null
  if ("$exists".Trim() -ne "1") {
    & "tools\pgsql\bin\createdb.exe" -h 127.0.0.1 -p 5433 -U lectora lectora
    Write-Host "База lectora создана"
  } else {
    Write-Host "База lectora уже существует"
  }
}

Write-Step "Сборка фронтенда"
Push-Location frontend
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
  Pop-Location
  Write-Error "npm.cmd не найден в PATH — установите Node.js LTS (>=20)"
}
if (-not (Test-Path "node_modules")) {
  & npm.cmd install --no-fund --no-audit
  if ($LASTEXITCODE -ne 0) { Pop-Location; Write-Error "npm install завершился ошибкой"; exit 1 }
}
& npm.cmd run build
if ($LASTEXITCODE -ne 0) { Pop-Location; Write-Error "сборка фронтенда завершилась ошибкой"; exit 1 }
Pop-Location

Write-Step "Готово"
if ($missing.Count -gt 0) {
  Write-Warning "Не хватает файлов:"
  $missing | ForEach-Object { Write-Warning "  - $_" }
  Write-Host "Инструкции по загрузке — в README.md, раздел «Установка моделей и инструментов»."
} else {
  Write-Host "Всё на месте. Запуск: powershell -ExecutionPolicy Bypass -File scripts\run.ps1"
}
