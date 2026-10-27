# Подготовка окружения Lectora: venv, зависимости, база, фронтенд.
# Запуск:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
param([switch]$Cuda, [switch]$Cpu, [switch]$DownloadAssets)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Write-Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }

Write-Step "Проверяем Python и Node"
$pythonExe = $null
foreach ($versionFlag in @("-3.12", "-3.11")) {
  try {
    $candidate = & py $versionFlag -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and (Test-Path $candidate)) {
      $pythonExe = $candidate
      $version = & $pythonExe -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
      Write-Host "Python $version OK ($pythonExe)"
      break
    }
  } catch { }
}
if (-not $pythonExe) {
  # Some Windows environments ship python.exe without the py launcher.
  foreach ($command in @("python", "python3")) {
    try {
      $candidate = & $command -c "import sys; print(sys.executable)" 2>$null
      if ($LASTEXITCODE -eq 0 -and (Test-Path $candidate)) {
        $version = & $candidate -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
        if ($version -in @("3.11", "3.12")) {
          $pythonExe = $candidate
          Write-Host "Python $version OK ($pythonExe)"
          break
        }
      }
    } catch { }
  }
}
if (-not $pythonExe) { Write-Error "Установите Python 3.12 или 3.11: Python 3.14 пока несовместим с CUDA-сборкой PyTorch"; exit 1 }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Write-Error "Node.js не найден в PATH"; exit 1 }
Write-Host "Node $(node -v) OK"

Write-Step "Виртуальное окружение и зависимости Python"
if (Test-Path ".venv\Scripts\python.exe") {
  $venvVersion = & ".venv\Scripts\python.exe" -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
  if ($venvVersion -notin @("3.11", "3.12")) {
    $backup = ".venv-python$($venvVersion.Replace('.', ''))-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Write-Warning "Текущее окружение использует Python $venvVersion; переносим его в $backup"
    Move-Item -LiteralPath ".venv" -Destination $backup
  }
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  & $pythonExe -m venv .venv
  if ($LASTEXITCODE -ne 0) { Write-Error "Не удалось создать .venv"; exit 1 }
}
& ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { Write-Error "Не удалось обновить pip"; exit 1 }
if ($Cpu) {
  Write-Host "Устанавливаем PyTorch для CPU (запрошено -Cpu)"
  & ".venv\Scripts\python.exe" -m pip install --upgrade --quiet torch --index-url https://download.pytorch.org/whl/cpu
  if ($LASTEXITCODE -ne 0) { Write-Error "Не удалось установить PyTorch"; exit 1 }
} else {
  # Автовыбор: NVIDIA GPU + совместимый драйвер => CUDA-сборка, иначе CPU.
  $gpuArgs = @()
  if ($Cuda) { $gpuArgs = @("-Force") }
  & powershell -ExecutionPolicy Bypass -File scripts\install_gpu.ps1 @gpuArgs
  if ($LASTEXITCODE -ne 0) { Write-Warning "Не удалось подготовить PyTorch; пробуем CPU-сборку"; & ".venv\Scripts\python.exe" -m pip install --upgrade --quiet torch --index-url https://download.pytorch.org/whl/cpu }
}
& ".venv\Scripts\python.exe" -m pip install --quiet -r backend\requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Error "Не удалось установить зависимости backend"; exit 1 }
Write-Host "Зависимости установлены"

if ($DownloadAssets) {
  Write-Step "Загружаем модели и переносимые инструменты"
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install_assets.ps1
  if ($LASTEXITCODE -ne 0) { Write-Error "Не удалось установить модели или инструменты"; exit 1 }
}

Write-Step "Дополнительные инструменты"
if (-not (Test-Path "tools\yt-dlp\yt-dlp.exe")) {
  Write-Host "Скачиваем yt-dlp для импорта видео по ссылке"
  New-Item -ItemType Directory -Force "tools\yt-dlp" | Out-Null
  try {
    Invoke-WebRequest -Uri "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" -OutFile "tools\yt-dlp\yt-dlp.exe"
  } catch {
    Remove-Item -LiteralPath "tools\yt-dlp\yt-dlp.exe" -Force -ErrorAction SilentlyContinue
    Write-Warning "Не удалось скачать yt-dlp: $($_.Exception.Message)"
  }
}

if (-not (Test-Path "tools\FreeDeepseekAPI\server.js")) {
  if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Host "Клонируем FreeDeepseekAPI для подробных конспектов"
    if (Test-Path "tools\FreeDeepseekAPI") {
      Write-Warning "tools\FreeDeepseekAPI существует, но server.js отсутствует — автоматическая установка пропущена"
    } else {
      & git clone --depth 1 https://github.com/ForgetMeAI/FreeDeepseekAPI.git "tools\FreeDeepseekAPI"
      if ($LASTEXITCODE -ne 0) { Write-Warning "Не удалось клонировать FreeDeepseekAPI" }
    }
  } else {
    Write-Warning "Git не найден: FreeDeepseekAPI нужно скачать вручную в tools\FreeDeepseekAPI"
  }
}

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
  @{ Path = "tools\llama-vulkan\llama-server.exe"; Hint = "llama.cpp (Vulkan) в tools\llama-vulkan" },
  @{ Path = "tools\yt-dlp\yt-dlp.exe"; Hint = "yt-dlp.exe в tools\yt-dlp (импорт по ссылке)" }
  @{ Path = "tools\FreeDeepseekAPI\server.js"; Hint = "FreeDeepseekAPI в tools\FreeDeepseekAPI (подробный конспект DeepSeek)" }
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
  if ($LASTEXITCODE -ne 0) { Write-Error "PostgreSQL не запустился"; exit 1 }
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
if ((Test-Path "tools\FreeDeepseekAPI\server.js") -and -not (Test-Path "tools\FreeDeepseekAPI\deepseek-auth.json")) {
  Write-Warning "Для DeepSeek остался один интерактивный шаг: cd tools\FreeDeepseekAPI; npm run auth"
}
