# Downloads every model and portable tool used by Lectora.
# Safe to run repeatedly: complete assets are detected and skipped.
param([switch]$Force)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$downloads = Join-Path $root "tools\_downloads"
New-Item -ItemType Directory -Force $downloads | Out-Null

function Write-Step([string]$Text) {
  Write-Host "`n--- $Text ---" -ForegroundColor Cyan
}

function Get-File([string]$Url, [string]$Destination) {
  if ((Test-Path $Destination) -and (Get-Item $Destination).Length -gt 0 -and -not $Force) {
    Write-Host "Файл уже загружен: $Destination" -ForegroundColor DarkGray
    return
  }
  if ($Force -and (Test-Path $Destination)) {
    Remove-Item -LiteralPath $Destination -Force
  }
  New-Item -ItemType Directory -Force (Split-Path -Parent $Destination) | Out-Null
  Write-Host "Скачиваем $Url"
  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
  if ($curl) {
    & $curl.Source -L --fail --retry 5 --retry-delay 3 --continue-at - --output $Destination $Url
    if ($LASTEXITCODE -ne 0) { throw "Не удалось скачать $Url" }
  } else {
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
  }
}

function Expand-Zip([string]$Archive, [string]$Destination) {
  New-Item -ItemType Directory -Force $Destination | Out-Null
  Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -Force
}

function Install-Vosk([string]$Name, [string]$Url) {
  $target = Join-Path $root "models\vosk\$Name"
  if ((Test-Path (Join-Path $target "conf\model.conf")) -and -not $Force) {
    Write-Host "Vosk уже установлен: $Name" -ForegroundColor Green
    return
  }
  $archive = Join-Path $downloads "$Name.zip"
  Get-File $Url $archive
  New-Item -ItemType Directory -Force (Join-Path $root "models\vosk") | Out-Null
  Expand-Zip $archive (Join-Path $root "models\vosk")
  if (-not (Test-Path (Join-Path $target "conf\model.conf"))) {
    throw "Архив Vosk распакован, но модель не найдена: $target"
  }
}

function Invoke-Hf([string[]]$Arguments) {
  $hf = Join-Path $root ".venv\Scripts\hf.exe"
  if (-not (Test-Path $hf)) { throw "Не найден hf.exe. Сначала установите Python-зависимости." }
  & $hf @Arguments
  if ($LASTEXITCODE -ne 0) { throw "Hugging Face download завершился с кодом $LASTEXITCODE" }
}

Write-Step "Модели Vosk"
Install-Vosk "vosk-model-ru-0.42" "https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip"
Install-Vosk "vosk-model-small-ru-0.22" "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"

Write-Step "Whisper"
$whisperMarker = Join-Path $root "models\whisper\models--Systran--faster-whisper-small\refs\main"
if ((Test-Path $whisperMarker) -and -not $Force) {
  Write-Host "faster-whisper-small уже установлен" -ForegroundColor Green
} else {
  New-Item -ItemType Directory -Force "models\whisper" | Out-Null
  Invoke-Hf @("download", "Systran/faster-whisper-small", "--cache-dir", "models\whisper")
}

Write-Step "Эмбеддинги BGE-M3"
$embeddingMarker = Join-Path $root "models\embeddings\bge-m3\pytorch_model.bin"
if ((Test-Path $embeddingMarker) -and -not $Force) {
  Write-Host "bge-m3 уже установлен" -ForegroundColor Green
} else {
  Invoke-Hf @(
    "download", "BAAI/bge-m3", "--local-dir", "models\embeddings\bge-m3",
    "--include", "config*.json", "modules.json", "sentence_bert_config.json", "tokenizer*",
    "special_tokens_map.json", "sentencepiece.bpe.model", "1_Pooling/*", "pytorch_model.bin"
  )
}

Write-Step "Реранкер BGE"
$rerankerMarker = Join-Path $root "models\reranker\bge-reranker-v2-m3\model.safetensors"
if ((Test-Path $rerankerMarker) -and -not $Force) {
  Write-Host "bge-reranker-v2-m3 уже установлен" -ForegroundColor Green
} else {
  Invoke-Hf @(
    "download", "BAAI/bge-reranker-v2-m3", "--local-dir", "models\reranker\bge-reranker-v2-m3",
    "--include", "config.json", "model.safetensors", "tokenizer*", "special_tokens_map.json", "sentencepiece.bpe.model"
  )
}

Write-Step "Локальная Qwen"
$qwen = Join-Path $root "models\llm\Qwen2.5-7B-Instruct-Q4_K_M.gguf"
if ((Test-Path $qwen) -and (Get-Item $qwen).Length -gt 1GB -and -not $Force) {
  Write-Host "Qwen2.5-7B уже установлен" -ForegroundColor Green
} else {
  New-Item -ItemType Directory -Force "models\llm" | Out-Null
  Invoke-Hf @(
    "download", "bartowski/Qwen2.5-7B-Instruct-GGUF", "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
    "--local-dir", "models\llm"
  )
}

Write-Step "FFmpeg"
$ffmpegExe = Join-Path $root "tools\ffmpeg\bin\ffmpeg.exe"
$ffprobeExe = Join-Path $root "tools\ffmpeg\bin\ffprobe.exe"
if ((Test-Path $ffmpegExe) -and (Test-Path $ffprobeExe) -and -not $Force) {
  Write-Host "FFmpeg уже установлен" -ForegroundColor Green
} else {
  $archive = Join-Path $downloads "ffmpeg.zip"
  $extract = Join-Path $downloads "ffmpeg-extract"
  Get-File "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" $archive
  if (Test-Path $extract) { Remove-Item -LiteralPath $extract -Recurse -Force }
  Expand-Zip $archive $extract
  $sourceBin = Get-ChildItem $extract -Filter ffmpeg.exe -Recurse | Select-Object -First 1 | ForEach-Object DirectoryName
  if (-not $sourceBin) { throw "ffmpeg.exe не найден в загруженном архиве" }
  New-Item -ItemType Directory -Force "tools\ffmpeg\bin" | Out-Null
  Copy-Item -LiteralPath (Join-Path $sourceBin "ffmpeg.exe") -Destination "tools\ffmpeg\bin\ffmpeg.exe" -Force
  Copy-Item -LiteralPath (Join-Path $sourceBin "ffprobe.exe") -Destination "tools\ffmpeg\bin\ffprobe.exe" -Force
  Remove-Item -LiteralPath $extract -Recurse -Force
}

Write-Step "PostgreSQL 17 portable"
$postgresExe = Join-Path $root "tools\pgsql\bin\postgres.exe"
if ((Test-Path $postgresExe) -and -not $Force) {
  Write-Host "PostgreSQL уже установлен" -ForegroundColor Green
} else {
  $archive = Join-Path $downloads "postgresql-17.6.zip"
  Get-File "https://get.enterprisedb.com/postgresql/postgresql-17.6-1-windows-x64-binaries.zip" $archive
  Expand-Zip $archive (Join-Path $root "tools")
  if (-not (Test-Path $postgresExe)) { throw "postgres.exe не найден после распаковки" }
}

Write-Step "llama.cpp Vulkan"
$llamaExe = Join-Path $root "tools\llama-vulkan\llama-server.exe"
if ((Test-Path $llamaExe) -and -not $Force) {
  Write-Host "llama.cpp Vulkan уже установлен" -ForegroundColor Green
} else {
  $headers = @{ "User-Agent" = "Lectora-Installer" }
  $release = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
  $asset = $release.assets | Where-Object { $_.name -match 'bin-win-vulkan-x64\.zip$' } | Select-Object -First 1
  if (-not $asset) { throw "В последнем релизе llama.cpp не найден архив Vulkan для Windows x64" }
  $archive = Join-Path $downloads $asset.name
  $extract = Join-Path $downloads "llama-vulkan-extract"
  Get-File $asset.browser_download_url $archive
  if (Test-Path $extract) { Remove-Item -LiteralPath $extract -Recurse -Force }
  Expand-Zip $archive $extract
  $server = Get-ChildItem $extract -Filter llama-server.exe -Recurse | Select-Object -First 1
  if (-not $server) { throw "llama-server.exe не найден в загруженном архиве" }
  New-Item -ItemType Directory -Force "tools\llama-vulkan" | Out-Null
  Copy-Item -Path (Join-Path $server.DirectoryName "*") -Destination "tools\llama-vulkan" -Recurse -Force
  Remove-Item -LiteralPath $extract -Recurse -Force
}

Write-Step "yt-dlp"
$ytdlp = Join-Path $root "tools\yt-dlp\yt-dlp.exe"
if ((Test-Path $ytdlp) -and -not $Force) {
  Write-Host "yt-dlp уже установлен" -ForegroundColor Green
} else {
  Get-File "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" $ytdlp
}

Write-Step "FreeDeepseekAPI"
$deepseek = Join-Path $root "tools\FreeDeepseekAPI\server.js"
if ((Test-Path $deepseek) -and -not $Force) {
  Write-Host "FreeDeepseekAPI уже установлен" -ForegroundColor Green
} else {
  $git = Get-Command git.exe -ErrorAction SilentlyContinue
  if ($git -and -not (Test-Path (Join-Path $root "tools\FreeDeepseekAPI"))) {
    & $git.Source clone --depth 1 https://github.com/ForgetMeAI/FreeDeepseekAPI.git "tools\FreeDeepseekAPI"
    if ($LASTEXITCODE -ne 0) { throw "Не удалось клонировать FreeDeepseekAPI" }
  } else {
    $archive = Join-Path $downloads "FreeDeepseekAPI.zip"
    $extract = Join-Path $downloads "deepseek-extract"
    Get-File "https://github.com/ForgetMeAI/FreeDeepseekAPI/archive/refs/heads/main.zip" $archive
    if (Test-Path $extract) { Remove-Item -LiteralPath $extract -Recurse -Force }
    Expand-Zip $archive $extract
    $source = Get-ChildItem $extract -Filter server.js -Recurse | Select-Object -First 1 | ForEach-Object DirectoryName
    if (-not $source) { throw "server.js не найден в архиве FreeDeepseekAPI" }
    New-Item -ItemType Directory -Force "tools\FreeDeepseekAPI" | Out-Null
    Copy-Item -Path (Join-Path $source "*") -Destination "tools\FreeDeepseekAPI" -Recurse -Force
    Remove-Item -LiteralPath $extract -Recurse -Force
  }
}

Write-Host "`nВсе модели и инструменты установлены." -ForegroundColor Green
