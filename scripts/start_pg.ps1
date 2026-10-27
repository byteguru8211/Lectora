# Запуск локального PostgreSQL (портативная сборка в tools\pgsql).
$root = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $root "tools\pgsql\bin"
$data = Join-Path $root "data\pgdata"
$logs = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null

if (-not (Test-Path (Join-Path $bin "pg_ctl.exe"))) {
  Write-Error "PostgreSQL не найден: tools\pgsql. См. README, раздел «Установка»."
  exit 1
}
if (-not (Test-Path (Join-Path $data "PG_VERSION"))) {
  Write-Error "Кластер PostgreSQL не инициализирован: $data. Запустите scripts\setup.ps1."
  exit 1
}

& (Join-Path $bin "pg_isready.exe") -h 127.0.0.1 -p 5433 | Out-Null
if ($LASTEXITCODE -eq 0) {
  Write-Host "PostgreSQL уже запущен на 127.0.0.1:5433"
  exit 0
}

Start-Process -FilePath (Join-Path $bin "postgres.exe") `
  -ArgumentList @("-D", "`"$data`"", "-p", "5433") `
  -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $logs "pg.out.log") `
  -RedirectStandardError (Join-Path $logs "pg.err.log")

for ($i = 0; $i -lt 10; $i++) {
  Start-Sleep -Seconds 2
  & (Join-Path $bin "pg_isready.exe") -h 127.0.0.1 -p 5433 | Out-Null
  if ($LASTEXITCODE -eq 0) {
    Write-Host "PostgreSQL готов"
    exit 0
  }
}
Write-Error "PostgreSQL не стартовал, см. data\logs\pg.err.log"
exit 1
