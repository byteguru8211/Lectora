# Ставит PyTorch с CUDA, если в системе есть NVIDIA GPU.
# Без GPU (или при несовместимом драйвере) оставляет рабочую CPU-сборку.
# Запуск: powershell -ExecutionPolicy Bypass -File scripts\install_gpu.ps1 [-Force]
param([switch]$Force)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  Write-Error "Не найден .venv. Сначала запустите scripts\setup.ps1."
  exit 1
}

function Get-TorchStatus {
  $raw = & $python -c "import json; `ntry:`n import torch`n print(json.dumps({'version': torch.__version__, 'cuda': torch.version.cuda, 'available': bool(torch.cuda.is_available()), 'device': torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}))`nexcept Exception as exc:`n print(json.dumps({'error': str(exc)}))" 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $raw) { return $null }
  try { return ($raw | ConvertFrom-Json) } catch { return $null }
}

function Install-CpuTorch {
  Write-Host "Устанавливаем PyTorch для CPU…"
  & $python -m pip install --upgrade --quiet torch --index-url https://download.pytorch.org/whl/cpu
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "Не удалось установить PyTorch. Проверьте интернет и повторите setup."
  }
}

function Test-CudaRuntime {
  & $python -c "import torch; x = torch.randn(512, 512, device='cuda'); (x @ x).sum().item(); print('CUDA OK:', torch.cuda.get_device_name(0), '| PyTorch', torch.__version__)" 2>&1
  return $LASTEXITCODE -eq 0
}

$status = Get-TorchStatus
if (-not $Force -and $status -and $status.available) {
  Write-Host "CUDA уже доступна: $($status.device) (PyTorch $($status.version))" -ForegroundColor Green
  exit 0
}

$smi = (Get-Command nvidia-smi -ErrorAction SilentlyContinue).Source
if (-not $smi) {
  $fallback = Join-Path $env:SystemRoot "System32\nvidia-smi.exe"
  if (Test-Path $fallback) { $smi = $fallback }
}
if (-not $smi) {
  Write-Host "NVIDIA GPU не найден — используем CPU-сборку PyTorch." -ForegroundColor Yellow
  if (-not $status) { Install-CpuTorch }
  exit 0
}

$driver = (& $smi --query-gpu=driver_version --format=csv,noheader 2>$null | Select-Object -First 1)
$gpuName = (& $smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
if (-not $driver) {
  Write-Warning "nvidia-smi не вернул версию драйвера — оставляем CPU-сборку."
  if (-not $status) { Install-CpuTorch }
  exit 0
}
$driver = "$driver".Trim()
$gpuName = "$gpuName".Trim()
$major = 0
try { $major = [int]($driver.Split(".")[0]) } catch { $major = 0 }
Write-Host "Обнаружена видеокарта: $gpuName, драйвер $driver"

# Индекс wheel-ов выбираем по версии драйвера; при сбое пробуем более старую CUDA.
$indexes = @()
if ($major -ge 560) { $indexes = @("cu126", "cu124", "cu118") }
elseif ($major -ge 525) { $indexes = @("cu124", "cu121", "cu118") }
elseif ($major -ge 450) { $indexes = @("cu118") }

if ($indexes.Count -eq 0) {
  Write-Warning "Драйвер $driver слишком старый для CUDA-сборки. Обновите драйвер NVIDIA; пока используется CPU."
  if (-not $status) { Install-CpuTorch }
  exit 0
}

foreach ($index in $indexes) {
  Write-Host "Пробуем PyTorch $index…" -ForegroundColor Cyan
  & $python -m pip install --upgrade --quiet torch --index-url "https://download.pytorch.org/whl/$index"
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "Не удалось скачать PyTorch $index."
    continue
  }
  if (Test-CudaRuntime) {
    Write-Host "GPU-ускорение готово." -ForegroundColor Green
    exit 0
  }
  Write-Warning "PyTorch $index установлен, но CUDA не запустилась. Пробуем другой вариант."
}

Write-Warning "CUDA не заработала. Оставляем CPU-сборку, приложение продолжит работать."
Install-CpuTorch
exit 0
