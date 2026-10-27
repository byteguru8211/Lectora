# One-command installation and launch for a clean Windows machine.
param(
  [ValidateSet("auto", "api", "local", "both")]
  [string]$LlmBackend = "auto",
  [switch]$Cpu,
  [switch]$SkipDeepSeekAuth
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Refresh-ProcessPath {
  $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $user = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$machine;$user"
}

function Install-Prerequisite([string]$Command, [string]$WingetId, [string]$Title, [switch]$Upgrade) {
  if ((Get-Command $Command -ErrorAction SilentlyContinue) -and -not $Upgrade) { return }
  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw "$Title не найден. Установите его вручную: winget недоступен."
  }
  Write-Host "Устанавливаем $Title…" -ForegroundColor Cyan
  if ($Upgrade) {
    & $winget.Source upgrade --exact --id $WingetId --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) {
      & $winget.Source install --exact --id $WingetId --accept-package-agreements --accept-source-agreements --silent --force
    }
  } else {
    & $winget.Source install --exact --id $WingetId --accept-package-agreements --accept-source-agreements --silent
  }
  if ($LASTEXITCODE -ne 0) { throw "Не удалось установить $Title через winget" }
  Refresh-ProcessPath
}

$pythonReady = $false
try {
  $pythonVersion = & py.exe -3.12 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
  $pythonReady = ($LASTEXITCODE -eq 0 -and "$pythonVersion".Trim() -eq "3.12")
} catch { }
if (-not $pythonReady) {
  Install-Prerequisite "py.exe" "Python.Python.3.12" "Python 3.12" -Upgrade
}

$nodeReady = $false
try {
  $nodeMajor = [int]((& node.exe -p "process.versions.node.split('.')[0]" 2>$null).Trim())
  $nodeReady = ($LASTEXITCODE -eq 0 -and $nodeMajor -ge 20)
} catch { }
if (-not $nodeReady) {
  Install-Prerequisite "node.exe" "OpenJS.NodeJS.LTS" "Node.js LTS" -Upgrade
}

$setupArgs = @("-DownloadAssets")
if ($Cpu) { $setupArgs += "-Cpu" }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "setup.ps1") @setupArgs
if ($LASTEXITCODE -ne 0) { throw "Установка Lectora завершилась ошибкой" }

$deepseekDir = Join-Path $root "tools\FreeDeepseekAPI"
$authFile = Join-Path $deepseekDir "deepseek-auth.json"
if (-not $SkipDeepSeekAuth -and -not (Test-Path $authFile)) {
  Write-Host "`nДля перевода и DeepSeek-конспектов требуется однократный вход." -ForegroundColor Yellow
  Write-Host "Сейчас откроется авторизация DeepSeek; после входа вернитесь в это окно."
  Push-Location $deepseekDir
  try {
    & npm.cmd run auth
    if ($LASTEXITCODE -ne 0) { Write-Warning "Авторизация DeepSeek не завершена. Локальный режим всё равно доступен." }
  } finally {
    Pop-Location
  }
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "run.ps1") -LlmBackend $LlmBackend
if ($LASTEXITCODE -ne 0) { throw "Не удалось запустить Lectora" }
