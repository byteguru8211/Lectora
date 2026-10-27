# Установка и запуск Lectora

Актуальная инструкция для Windows 10/11. Обычному пользователю достаточно одной команды;
остальные разделы нужны для диагностики и ручного обслуживания.

## Установка и запуск одной командой

Откройте PowerShell в корне репозитория:

```powershell
.\start.bat
```

При первом запуске сценарий:

1. проверяет Python 3.12 и Node.js 20+; при необходимости ставит их через `winget`;
2. создаёт `.venv` и устанавливает backend-зависимости;
3. определяет NVIDIA GPU и выбирает CUDA- или CPU-сборку PyTorch;
4. скачивает Vosk, faster-whisper-small, bge-m3, reranker и Qwen GGUF;
5. устанавливает portable FFmpeg, PostgreSQL 17, llama.cpp Vulkan и yt-dlp;
6. получает FreeDeepseekAPI и предлагает однократную авторизацию DeepSeek;
7. создаёт базу `lectora`, собирает React-фронтенд и запускает сервисы;
8. открывает `http://127.0.0.1:8000`.

Первая установка занимает 12–15 ГБ. Загрузки возобновляются после обрыва, готовые файлы
при следующих запусках пропускаются.

## Параметры

```powershell
# Не устанавливать CUDA-сборку PyTorch
.\start.bat -Cpu

# Не открывать интерактивную авторизацию DeepSeek
.\start.bat -SkipDeepSeekAuth -LlmBackend local

# Запустить только DeepSeek API, без локальной Qwen
.\start.bat -LlmBackend api

# Запустить локальную Qwen
.\start.bat -LlmBackend local

# Запустить обе LLM (рекомендуется от 8 ГБ VRAM)
.\start.bat -LlmBackend both
```

Перевод RU↔EN доступен только при работающем DeepSeek API. Локальный режим продолжает
поддерживать конспекты и Q&A, но не выполняет перевод.

## Что и куда устанавливается

| Компонент | Путь |
|---|---|
| Python-окружение | `.venv/` |
| Vosk | `models/vosk/` |
| faster-whisper-small | `models/whisper/` |
| bge-m3 | `models/embeddings/bge-m3/` |
| bge-reranker-v2-m3 | `models/reranker/bge-reranker-v2-m3/` |
| Qwen GGUF | `models/llm/` |
| FFmpeg | `tools/ffmpeg/bin/` |
| PostgreSQL | `tools/pgsql/` и `data/pgdata/` |
| llama.cpp Vulkan | `tools/llama-vulkan/` |
| FreeDeepseekAPI | `tools/FreeDeepseekAPI/` |
| yt-dlp | `tools/yt-dlp/` |
| пользовательские медиа | `storage/media/` |
| журналы | `data/logs/` |

## Раздельные команды для разработчика

```powershell
# Python/Node-зависимости, БД и production-сборка
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# Только модели и portable-инструменты
powershell -ExecutionPolicy Bypass -File scripts\install_assets.ps1

# Установка зависимостей вместе с моделями
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -DownloadAssets

# Только запуск уже установленного проекта
powershell -ExecutionPolicy Bypass -File scripts\run.ps1

# Остановка фоновых компонентов
powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
```

## Проверка после установки

Откройте `http://127.0.0.1:8000/api/health`. Нормальный ответ содержит:

- `database.ok=true`;
- `ffmpeg.ok=true`;
- обе модели Vosk в `asr_models.profiles`;
- `embeddings.ok=true` и `reranker.ok=true`;
- `llm_api.available=true`, если выполнен вход DeepSeek;
- `llm.available=true`, если запущена локальная Qwen.

## Частые проблемы

| Симптом | Решение |
|---|---|
| Найден Python 3.14 | установите 3.12; `bootstrap.ps1` делает это через `winget` |
| PyTorch долго скачивается | CUDA-wheel занимает несколько гигабайт; первая установка может идти 10–20 минут |
| CUDA недоступна | обновите драйвер NVIDIA или запустите с `-Cpu`; приложение продолжит работать |
| NVENC недоступен | обновите драйвер; Whisper/BGE всё равно могут использовать CUDA |
| DeepSeek не готов | в `tools/FreeDeepseekAPI` выполните `npm run auth`, затем повторите запуск |
| Перевод недоступен | выберите режим DeepSeek API и проверьте `llm_api` в `/api/health` |
| yt-dlp не импортирует ссылку | повторно запустите `scripts/install_assets.ps1` |
| Порт 5433 занят | остановите другой PostgreSQL или измените `DATABASE_URL` и настройки запуска |
| Сервер не стартует | проверьте `data/logs/server.err.log` |

Файл `.env` создаётся из `.env.example` один раз и при повторной установке не
перезаписывается, поэтому локальные настройки и ключи сохраняются.
