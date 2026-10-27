# Lectora — семантический поиск по видеолекциям

Локальный продукт для студентов и преподавателей: загружаете видеолекцию — получаете
транскрипт с таймкодами, поиск по смыслу, конспект со структурой и возможность задавать
вопросы по содержанию. Всё работает **офлайн на своём железе**: ни API-ключей, ни облака.

![Библиотека лекций](docs/screenshots/01-library.png)

<p align="center">
  <img src="docs/screenshots/03-lecture-search.png" width="49%" alt="Поиск внутри лекции" />
  <img src="docs/screenshots/04-lecture-qa.png" width="49%" alt="Вопросы по лекции" />
</p>

---

## Что умеет

| Возможность | Как реализовано |
|---|---|
| Загрузка MP4/WebM/MOV/MKV и ссылок YouTube/Vimeo | потоковая запись на диск, ffprobe/ffmpeg, `yt-dlp` |
| Автоматическое название лекции | LLM придумывает осмысленное имя по содержанию, если пользователь не задал своё |
| Автоматическая транскрибация | **Vosk** (`ru-0.42` — точная, `small-ru` — быстрая), два профиля на выбор |
| Таймкоды до секунды | слово-уровневые тайминги Vosk → субтитры и сегменты транскрипта |
| Семантический поиск | **bge-m3** (эмбеддинги) + полнотекстовый индекс PostgreSQL + **bge-reranker-v2-m3** |
| Поиск по всему курсу | гибридный поиск по всем готовым лекциям сразу, с переходом на таймкод |
| Конспект и структура лекции | локальная LLM **Qwen2.5-7B-Instruct (GGUF)** через `llama.cpp`, с экстрактивным фолбэком |
| Просмотр с навигацией | **Plyr**, главы прямо в плеере (работают и в полноэкранном режиме), синхронные субтитры, транскрипт по главам |
| Вопросы по лекции | RAG: поиск фрагментов + ответ локальной LLM со ссылками на таймкоды |
| Красивый интерфейс | React 19 + TypeScript, тёмная/светлая тема, командная палитра `Ctrl+K` |

Дополнительно: очередь обработки с восстановлением после перезапуска, SSE-прогресс,
аналитика поиска, health-check, статистика, докачиваемые модели, CLI для пакетной обработки.

### Поиск по всему курсу

![Поиск по курсу](docs/screenshots/05-course-search.png)

### Плеер с главами

![Главы в плеере](docs/screenshots/06-player-chapters.png)

---

## Быстрый старт

> Проверено на Windows 11, Python 3.12, Node.js 24, PostgreSQL 17.6, GPU RTX 2080 Super (8 ГБ).

```powershell
# 1. подготовка окружения (venv, зависимости, база, сборка фронтенда)
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# 2. запуск всего стека (PostgreSQL + локальная LLM + backend)
powershell -ExecutionPolicy Bypass -File scripts\run.ps1

# 3. опционально: DeepSeek API для самых подробных конспектов
powershell -ExecutionPolicy Bypass -File scripts\start_api_llm.ps1
```

Откройте <http://127.0.0.1:8000>. Остановить всё: `scripts\stop.ps1`.

**Первые 3–4 минуты после старта** идёт прогрев моделей (Vosk читает 3,4 ГБ модели).
Интерфейс доступен сразу, но первая загрузка лекции будет ждать загрузку ASR-модели.
Для защиты нажмите «Загрузить» через пару минут после `run.ps1`.

### Три режима конспекта

Транскрибация всегда остаётся локальной (Vosk или Whisper). Для конспекта, структуры,
ключевых терминов и Q&A есть три режима; режим по умолчанию задаёт `LLM_MODE` в `.env`,
а конкретное видео можно переключить в диалоге загрузки или кнопкой «Конспект» на
странице лекции (расшифровка при этом не пересчитывается).

| Режим | Что делает | Когда использовать |
|---|---|---|
| `api` | DeepSeek Web через локальный прокси `tools/FreeDeepseekAPI` | самый подробный конспект: 6–14 разделов, 180–300 слов обзора, 4–6 тезисов и markdown-конспект по каждому разделу, вопросы для самопроверки |
| `local` | Qwen2.5-7B через llama.cpp на этом компьютере | без интернета, компактный конспект |
| `offline` | экстрактивный алгоритм без ИИ | демо, отладка, аварийный режим — работает всегда |

**Почему API-режим устроен осторожно.** FreeDeepseekAPI управляет обычным веб-аккаунтом
DeepSeek, а не платным API: один ответ на чат, общие лимиты, возможные кулдауны. Поэтому
Lectora:

* выполняет запросы последовательно (`API_LLM_MAX_CONCURRENT=1`) с паузой
  `API_LLM_MIN_INTERVAL_SEC` и ретраями на `429`/`5xx` с учётом `Retry-After`;
* держит промпт ниже лимита прокси (`API_LLM_MAX_PROMPT_CHARS=42000` против
  `DEEPSEEK_MAX_PROMPT_CHARS=80000` по умолчанию) и режет длинные лекции на окна;
* изолирует каждый запрос одноразовым ключом сессии и сбрасывает чат после ответа —
  лекции не смешиваются, а прокси не копит историю;
* собирает конспект в четыре прохода: тезисы по фрагментам (для длинных записей) →
  план разделов → подробные конспекты разделов → общий обзор, термины и вопросы.
  Если API отвалился посреди работы, включается локальная модель, затем офлайн-алгоритм;
  фактический режим виден в интерфейсе (`llm_mode_used`).

Проверить доступность режимов и собрать конспект по уже обработанной лекции без
пересчёта видео:

```powershell
.venv\Scripts\python.exe scripts\check_llm_modes.py
.venv\Scripts\python.exe scripts\check_llm_modes.py --lecture-id <uuid> --mode api
```

### Требования

* Windows 10/11, PowerShell 5.1+
* Python 3.12 (venv)
* Node.js 20+ (сборка фронтенда)
* ~16 ГБ RAM, 8 ГБ VRAM (для 7B-модели), 15 ГБ на диске под модели и инструменты
* GPU не обязателен: без него LLM пойдёт на CPU (медленнее, но работает)

---

## Установка моделей и инструментов

Всё складывается в `models/` и `tools/` — эти папки не коммитятся (12+ ГБ), их нужно
подготовить один раз. Полный список с размерами:

| Что | Куда | Размер | Ссылка |
|---|---|---|---|
| Vosk RU (точная) | `models/vosk/vosk-model-ru-0.42/` | 1,8 ГБ | <https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip> |
| Vosk RU (быстрая) | `models/vosk/vosk-model-small-ru-0.22/` | 45 МБ | <https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip> |
| Эмбеддинги bge-m3 | `models/embeddings/bge-m3/` | 2,3 ГБ | <https://huggingface.co/BAAI/bge-m3> |
| Реранкер bge-reranker-v2-m3 | `models/reranker/bge-reranker-v2-m3/` | 2,3 ГБ | <https://huggingface.co/BAAI/bge-reranker-v2-m3> |
| `models/llm/Qwen2.5-7B-Instruct-Q4_K_M.gguf` | LLM Qwen2.5-7B Q4_K_M (GGUF) | 4,7 ГБ | <https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF> |
| PostgreSQL 17 (portable) | `tools/pgsql/` | 330 МБ | <https://www.enterprisedb.com/download-postgresql-binaries> |
| ffmpeg + ffprobe | `tools/ffmpeg/bin/` | 190 МБ | <https://github.com/BtbN/FFmpeg-Builds/releases> |
| llama.cpp (Vulkan) | `tools/llama-vulkan/` | 35 МБ | <https://github.com/ggml-org/llama.cpp/releases> |
| yt-dlp | `tools/yt-dlp/yt-dlp.exe` | 17 МБ | <https://github.com/yt-dlp/yt-dlp/releases> |

Команды для HuggingFace-моделей (нужен `pip install -U huggingface_hub`):

```powershell
hf download BAAI/bge-m3 --local-dir models\embeddings\bge-m3 `
  --include "config*.json" "modules.json" "sentence_bert_config.json" "tokenizer*" `
            "special_tokens_map.json" "sentencepiece.bpe.model" "1_Pooling/*" "pytorch_model.bin"

hf download BAAI/bge-reranker-v2-m3 --local-dir models\reranker\bge-reranker-v2-m3 `
  --include "config.json" "model.safetensors" "tokenizer*" "special_tokens_map.json" "sentencepiece.bpe.model"

hf download bartowski/Qwen2.5-7B-Instruct-GGUF Qwen2.5-7B-Instruct-Q4_K_M.gguf --local-dir models\llm

# yt-dlp для импорта по ссылке
New-Item -ItemType Directory -Force tools\yt-dlp | Out-Null
curl.exe -L -o tools\yt-dlp\yt-dlp.exe https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe
```

> Для bge-m3 в репозитории нет `model.safetensors` — только `pytorch_model.bin`. Это нормально.
> Не клонируйте репозиторий целиком: внутри ~13 ГБ ONNX-дублей, из которых нужны 2,3 ГБ.

**Про GPU:** сборка llama.cpp с CUDA не запустилась на драйвере 546 (ошибка `ggml-cuda.cu:110`),
поэтому используется Vulkan-сборка — она работает на любом GPU (NVIDIA/AMD/Intel) и на 7B
выдаёт ~30 tok/s. CUDA-сборка лежит в `tools/llama`, но по умолчанию не используется.

---

## Архитектура

```
┌──────────────────────────────┐        ┌─────────────────────────────────┐
│  React 19 + TypeScript       │  HTTP  │  Flask 3 (waitress)             │
│  Vite · Plyr · SSE           │ ─────► │  REST API · SSE · static SPA    │
└──────────────────────────────┘        └───────────┬─────────────────────┘
                                                    │
                     ┌──────────────────────────────┼───────────────────────────┐
                     │                              │                           │
              ┌──────▼──────┐               ┌───────▼────────┐          ┌───────▼───────┐
              │ PostgreSQL  │               │ Job worker     │          │ ML-сервисы    │
              │ схема + FTS │               │ (поток, БД-    │          │ Vosk · bge-m3 │
              │ очередь job │               │  очередь)      │          │ reranker · LLM│
              └─────────────┘               └───────┬────────┘          └───────┬───────┘
                                                    │                           │
                                            ┌───────▼────────┐          ┌───────▼───────┐
                                            │ ffmpeg         │          │ llama-server  │
                                            │ аудио, превью  │          │ (127.0.0.1)   │
                                            └────────────────┘          └───────┬───────┘
                                                                                │
                                                                   ┌────────────▼────────────┐
                                                                   │ FreeDeepseekAPI :9655   │
                                                                   │ DeepSeek Web (optional) │
                                                                   └─────────────────────────┘
```

### Пайплайн обработки

`upload → (download) → probe → (transcode) → thumbnail → audio 16k mono → Vosk → пунктуация →
чанки → эмбеддинги → конспект, структура и название → ready`

* Для импорта по ссылке первая стадия — `download` (yt-dlp), затем обычный пайплайн.
* Конспект выбирает один из трёх режимов (`api` / `local` / `offline`); API-режим добавляет
  подстадии `notes_map → notes_outline → notes_details → notes_summary`.
* Отдельная задача `kind=notes` пересобирает только конспект по сохранённому транскрипту —
  режимы можно сравнивать без повторного распознавания.

* Прогресс каждой стадии пишется в `lectures` и `jobs`; UI получает его через SSE.
* Обработка идёт в отдельном потоке, HTTP-запрос возвращается сразу (202 Accepted).
* При падении процесса незавершённые задачи перезапускаются при старте (recovery).
* Повторная обработка идемпотентна: старые сегменты/чанки/разделы заменяются только после
  успешного распознавания.

### Поиск

1. **Dense recall** — косинусная близость к чанкам (bge-m3, кэш матрицы в памяти).
2. **Lexical recall** — `websearch_to_tsquery('russian')` + `ts_rank_cd`, GIN-индекс.
3. **Fusion** — взвешенная сумма нормализованных скоров.
4. **Rerank** — bge-reranker-v2-m3 пересортировывает топ-6 (кэш по запросу).
5. **Дедупликация** — близкие фрагменты одной лекции схлопываются.

Подробности: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Технологии

| Слой | Стек |
|---|---|
| Фронтенд | React 19, TypeScript, Vite 7, React Router 7, Plyr 3, нативный CSS |
| Бэкенд | Python 3.12, Flask 3, SQLAlchemy 2, waitress, SSE |
| БД | PostgreSQL 17 (полнотекстовый поиск `russian`, JSONB, очередь задач) |
| ASR | Vosk 0.3.45, модели `ru-0.42` / `small-ru-0.22` |
| Эмбеддинги | sentence-transformers, BAAI/bge-m3 (1024d) |
| Реранкер | BAAI/bge-reranker-v2-m3 |
| LLM | Qwen2.5-7B-Instruct Q4_K_M, llama.cpp (Vulkan), OpenAI-совместимый API |
| LLM API | DeepSeek Web через FreeDeepseekAPI (OpenAI Chat Completions, сессии, ретраи) |
| Медиа | ffmpeg / ffprobe, WebVTT |

---

## Конфигурация

Все настройки — через `.env` (см. `.env.example`). Ключевые:

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://lectora:lectora@127.0.0.1:5433/lectora` | подключение к PostgreSQL |
| `ASR_DEFAULT_PROFILE` | `accurate` | профиль распознавания по умолчанию |
| `RERANKER_ENABLED` | `1` | включить реранкер |
| `RERANKER_TOP_K` | `6` | сколько кандидатов пересортировывать |
| `LLM_BASE_URL` | `http://127.0.0.1:8080/v1` | локальный llama-server |
| `LLM_MODE` | `local` | режим конспекта по умолчанию: `api` / `local` / `offline` |
| `API_LLM_BASE_URL` | `http://127.0.0.1:9655/v1` | FreeDeepseekAPI (DeepSeek Web) |
| `API_LLM_MODEL` | `deepseek-v4-flash` | алиас модели в прокси |
| `API_LLM_MAX_PROMPT_CHARS` | `42000` | предохранитель под лимит прокси |
| `API_LLM_MAX_CONCURRENT` | `1` | одновременных запросов к веб-аккаунту |
| `API_LLM_MIN_INTERVAL_SEC` | `3` | пауза между запросами |
| `API_LLM_RETRY_ATTEMPTS` | `3` | попыток при 429/5xx |
| `PUNCTUATION_MODE` | `rules` | `rules` — быстро, `llm` — редактура локальной моделью |
| `WORKER_THREADS` | `1` | параллельных обработок (ASR тяжёлый) |
| `MAX_UPLOAD_MB` | `4096` | лимит загрузки |

Если LLM недоступна, продукт не ломается: конспект и структура строятся экстрактивным
алгоритмом, а Q&A отвечает подборкой релевантных фрагментов (с пометкой в интерфейсе).

---

## API

REST + SSE, JSON. Полное описание с примерами — [docs/API.md](docs/API.md).

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/lectures` | список лекций (фильтры `status`, `q`) |
| `POST` | `/api/lectures` | загрузка файла (multipart) |
| `POST` | `/api/lectures/import` | импорт по ссылке |
| `GET` | `/api/lectures/{id}` | карточка + конспект + структура |
| `POST` | `/api/lectures/{id}/notes` | пересобрать конспект в другом режиме (без ASR) |
| `GET` | `/api/lectures/{id}/transcript` | транскрипт с таймкодами |
| `GET` | `/api/lectures/{id}/events` | SSE-прогресс обработки |
| `GET` | `/api/lectures/{id}/media` | видео с поддержкой Range |
| `GET` | `/api/lectures/{id}/subtitles.vtt` | субтитры |
| `GET` | `/api/search?q=…` | семантический поиск (по лекции или курсу) |
| `POST` | `/api/lectures/{id}/qa` | вопрос по лекции |
| `GET` | `/api/health`, `/api/stats` | состояние и статистика |

---

## CLI

```powershell
.venv\Scripts\python.exe backend\manage.py init-db
.venv\Scripts\python.exe backend\manage.py ingest videos_examples\пример_1.mp4 --title "Геометрия"
.venv\Scripts\python.exe backend\manage.py list
.venv\Scripts\python.exe backend\manage.py stats
```

---

## Структура репозитория

```
backend/
  app/
    api/          REST-эндпоинты (lectures, search, qa, system)
    services/     asr, media, embeddings, reranker, llm, llm_api, llm_modes,
                  summarizer, search, pipeline, jobs
    utils/        текст, таймкоды
    models.py     схема БД
    config.py     настройки из .env
  manage.py       CLI
  serve.py        production-запуск (waitress)
frontend/
  src/
    api/          типы и клиент
    components/   плеер, таймлайн, транскрипт, панели, модалки
    pages/        библиотека, лекция, поиск
    styles/       дизайн-система (CSS-переменные)
scripts/          setup / run / stop / start_server / start_api_llm / check_llm_modes
docs/             архитектура, API, сценарий демо, скриншоты
models/           (не коммитится) веса моделей
tools/            (не коммитится) ffmpeg, PostgreSQL, llama.cpp, FreeDeepseekAPI
storage/          (не коммитится) загруженные видео, аудио, превью
data/             (не коммитится) кластер PostgreSQL и логи
```

---

## Производительность

Замеры на RTX 2080 Super Max-Q (8 ГБ), i7-10875H, 16 ГБ RAM:

| Операция | Время |
|---|---|
| Загрузка модели Vosk ru-0.42 | ~3 мин (один раз, затем тёплая) |
| Транскрибация 7,5 мин лекции | ~2 мин (RTF ≈ 0,25) |
| Эмбеддинги 10 чанков | ~1 с (после прогрева) |
| Конспект + структура (локальная LLM) | 20–30 с |
| Конспект через DeepSeek API, 5-мин лекция | 30–45 с (6–8 разделов, ~5 КБ деталей) |
| Конспект через DeepSeek API, 30-мин лекция | 1,5–3 мин (10–14 разделов) |
| Поиск, первый запрос | ~3 с (холодный реранкер) |
| Поиск, повторный запрос | ~20 мс (кэш реранка) |
| Полная обработка 7,5 мин | ~4–6 мин (после прогрева) |

---

## Ограничения и развитие

* Vosk не расставляет знаки препинания — работает детерминированное восстановление,
  при `PUNCTUATION_MODE=llm` подключается редактура локальной моделью.
* ASR ошибается на формулах и латинице («A1B1C1D1» → «а один байден седен») — это ограничение
  акустической модели, а не поиска; при необходимости можно добавить второй движок (GigaAM/Whisper).
* Очередь рассчитана на один узел; для кластера достаточно вынести воркеры и заменить
  in-memory кэш эмбеддингов на pgvector.
* DeepSeek API — это веб-аккаунт через неофициальный прокси: DeepSeek может изменить
  контракт, а лимиты общие для всех клиентов аккаунта. Клиент изолирован интерфейсом
  `OpenAiCompatClient`, поэтому переход на официальный API — это смена `API_LLM_BASE_URL`,
  `API_LLM_MODEL` и `API_LLM_KEY`.
* Аутентификация локальная (сессии Flask + роли), без OAuth и подтверждения e-mail; для
  публикации нужен reverse-proxy с HTTPS и ограничением доступа.
* Конспект в режиме API собирается последовательно (один веб-аккаунт): параллельная
  обработка нескольких лекций в этом режиме выстроится в очередь.

---

## Лицензия

MIT. Модели и инструменты распространяются под своими лицензиями (Vosk — Apache 2.0,
bge-m3 — MIT, bge-reranker — Apache 2.0, Qwen2.5 — Apache 2.0, PostgreSQL — PostgreSQL License,
ffmpeg — LGPL/GPL, FreeDeepseekAPI — MIT). DeepSeek Web используется через прокси и
подчиняется условиям сервиса DeepSeek.
