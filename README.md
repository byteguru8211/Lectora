# Lectora — семантический поиск по видеолекциям

Платформа для работы с любыми образовательными и информационными видео: загрузите файл
или ссылку и получите транскрипт с таймкодами, семантический поиск, структурированный
конспект, перевод, двойные субтитры, дополнительную озвучку и Q&A по содержанию.

![Библиотека лекций](docs/screenshots/01-library.png)

<p align="center">
  <img src="docs/screenshots/03-lecture-search.png" width="49%" alt="Поиск внутри лекции" />
  <img src="docs/screenshots/06-player-subtitles.png" width="49%" alt="Двойные субтитры и настройки плеера" />
</p>

---

## Что умеет

| Возможность | Как реализовано |
|---|---|
| Загрузка MP4/WebM/MOV/MKV и ссылок YouTube/Vimeo | потоковая запись на диск, ffprobe/ffmpeg, `yt-dlp` |
| Автоматическое название лекции | LLM придумывает осмысленное имя по содержанию, если пользователь не задал своё |
| Регистрация и роли | аккаунты студентов и преподавателей, изолированные личные библиотеки |
| Автоматическая транскрибация | **Whisper** на CUDA/CPU для RU/EN и **Vosk** как быстрый офлайн-резерв |
| Таймкоды до секунды | сегменты и слова Whisper/Vosk → субтитры и кликабельный транскрипт |
| Перевод и озвучка | RU ↔ EN через DeepSeek API, один или два языка субтитров, дополнительная русская/английская дорожка |
| Семантический поиск | **bge-m3** (эмбеддинги) + полнотекстовый индекс PostgreSQL + **bge-reranker-v2-m3** |
| Поиск по всему курсу | гибридный поиск по всем готовым лекциям сразу, с переходом на таймкод |
| Конспект и структура лекции | локальная LLM **Qwen2.5-7B-Instruct (GGUF)** через `llama.cpp`, с экстрактивным фолбэком |
| Просмотр с навигацией | **Plyr**, главы прямо в плеере (работают и в полноэкранном режиме), синхронные субтитры, транскрипт по главам |
| Вопросы по лекции | RAG: поиск фрагментов + ответ локальной LLM со ссылками на таймкоды |
| Публичная библиотека | каталог публичных лекций и публичных групп, карточки авторов, ссылки на шаринг |
| Личный кабинет | ручные группы, автокатегории/подкатегории, видимость видео и коллекций, приватные ссылки |
| Поделиться | понятные кнопки «Поделиться видео» и «Поделиться курсом»: публичная ссылка или приватный токен |
| Настройки аккаунта | смена имени и пароля, завершение сессии на устройстве |
| Шпаргалка к экзамену | билеты с ответами, определения, формулы и полный конспект по группе — из готовых конспектов, без повторной обработки видео |
| Формулы и смысловые блоки | KaTeX с ленивой загрузкой, выделение определений/теорем/примеров, печать и PDF, экспорт субтитров в SRT |
| Рекомендации «Для Вас» | профиль интересов из загруженных лекций и просмотров, устойчивое к морфологии сопоставление тем, популярность и свежесть как тай-брейкеры |
| Красивый интерфейс | React 19 + TypeScript, тёмная/светлая тема, командная палитра `Ctrl+K` |

Дополнительно: очередь обработки с восстановлением после перезапуска, SSE-прогресс,
аналитика поиска, health-check, статистика, докачиваемые модели, CLI для пакетной обработки.

### Публичная библиотека

![Публичная библиотека](docs/screenshots/04-public-library.png)

### Личный кабинет и группы

![Личный кабинет и группы](docs/screenshots/05-account-groups.png)

### Шпаргалка к экзамену

![Шпаргалка к экзамену](docs/screenshots/08-exam-sheet.png)

### Поделиться видео или курсом

![Поделиться видео или курсом](docs/screenshots/09-share-dialog.png)

### Настройки аккаунта

![Настройки аккаунта](docs/screenshots/07-account-settings.png)

### Загрузка, перевод и озвучка

![Язык, перевод, видимость и группы при загрузке](docs/screenshots/02-upload-translation.png)

---

## Быстрый старт

> Проверено на Windows 11, Python 3.12, Node.js 24, PostgreSQL 17.6, GPU RTX 2080 Super (8 ГБ).

```powershell
# Одна команда: установит зависимости и модели, соберёт и запустит проект
.\start.bat
```

При первом запуске будет скачано около 12–15 ГБ. Скрипт автоматически:

* при необходимости устанавливает Python 3.12 и Node.js LTS через `winget`;
* создаёт `.venv`, выбирает CUDA- или CPU-сборку PyTorch и ставит backend-пакеты;
* скачивает обе модели Vosk, faster-whisper-small, bge-m3, reranker и Qwen GGUF;
* устанавливает portable PostgreSQL, FFmpeg, llama.cpp Vulkan, yt-dlp и FreeDeepseekAPI;
* создаёт базу, собирает React-фронтенд и запускает весь стек.

Загрузка возобновляется после обрыва, а уже установленные многогигабайтные файлы
пропускаются. Если DeepSeek ещё не авторизован, при первом запуске откроется однократный
интерактивный вход. Последующие запуски выполняются той же командой и ничего не скачивают.

Принудительно использовать только CPU:

```powershell
.\start.bat -Cpu
```

Для автоматизированной установки без окна авторизации DeepSeek:

```powershell
.\start.bat -SkipDeepSeekAuth -LlmBackend local
```

Откройте <http://127.0.0.1:8000>. Остановить всё: `scripts\stop.ps1`.
Подробная установка, параметры и диагностика: [docs/INSTALLATION.md](docs/INSTALLATION.md).

**Первые 2–4 минуты после старта** может идти прогрев моделей.
Интерфейс доступен сразу, но первая загрузка лекции будет ждать загрузку ASR-модели.
Для защиты нажмите «Загрузить» через пару минут после `start.bat`.

### Два режима конспекта

Транскрибация всегда остаётся локальной (Vosk или Whisper). Для конспекта, структуры,
ключевых терминов и Q&A есть два режима; режим по умолчанию задаёт `LLM_MODE` в `.env`,
а конкретное видео можно переключить в диалоге загрузки или кнопкой «Конспект» на
странице лекции (расшифровка при этом не пересчитывается).

| Режим | Что делает | Когда использовать |
|---|---|---|
| `api` | DeepSeek Web через локальный прокси `tools/FreeDeepseekAPI` | самый подробный конспект: 6–14 разделов, 180–300 слов обзора, 4–6 тезисов и markdown-конспект по каждому разделу, вопросы для самопроверки |
| `local` | Qwen2.5-7B через llama.cpp на этом компьютере | без интернета, компактный конспект |

Если оба бэкенда недоступны, конспект собирается детерминированным экстрактивным
алгоритмом без модели — это аварийный фолбэк, а не отдельный пункт выбора. Фактический
режим всегда виден по `llm_mode_used` в интерфейсе.

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
* ~16 ГБ RAM, 6 ГБ VRAM для API-режима или 8 ГБ для одновременной локальной 7B-модели,
  15 ГБ на диске под модели и инструменты
* GPU не обязателен: `setup.ps1` сам ставит CUDA-сборку PyTorch при наличии NVIDIA GPU,
  иначе — CPU-сборку; без GPU LLM пойдёт на CPU (медленнее, но работает)

---

## Установка моделей и инструментов

Рекомендуемый способ — `start.bat` из раздела «Быстрый старт». Он автоматически скачивает
всё ниже, продолжает прерванные загрузки и пропускает уже готовые файлы. Для установки
только весов и portable-инструментов запустите `scripts\install_assets.ps1`.

Всё складывается в `models/` и `tools/` — эти папки не коммитятся. Полный список:

| Что | Куда | Размер | Ссылка |
|---|---|---|---|
| Vosk RU (точная) | `models/vosk/vosk-model-ru-0.42/` | 1,8 ГБ | <https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip> |
| Vosk RU (быстрая) | `models/vosk/vosk-model-small-ru-0.22/` | 45 МБ | <https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip> |
| faster-whisper-small | `models/whisper/` (HF cache) | ~500 МБ | <https://huggingface.co/Systran/faster-whisper-small> |
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

hf download Systran/faster-whisper-small --cache-dir models\whisper

# yt-dlp для импорта по ссылке
New-Item -ItemType Directory -Force tools\yt-dlp | Out-Null
curl.exe -L -o tools\yt-dlp\yt-dlp.exe https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe
```

> Для bge-m3 в репозитории нет `model.safetensors` — только `pytorch_model.bin`. Это нормально.
> Не клонируйте репозиторий целиком: внутри ~13 ГБ ONNX-дублей, из которых нужны 2,3 ГБ.

**Про GPU.** Галочка «Использовать видеокарту» включает три независимых ускорения:

* **CUDA (PyTorch)** — эмбеддинги и Whisper. `scripts/setup.ps1` автоматически определяет
  NVIDIA GPU, версию драйвера и ставит подходящую CUDA-сборку; без GPU или при несовместимом
  драйвере остаётся рабочая CPU-сборка. Переустановить вручную:
  `powershell -ExecutionPolicy Bypass -File scripts\install_gpu.ps1` (флаг `-Force` — заново).
* **NVENC (ffmpeg)** — аппаратное перекодирование видео. Доступность проверяется реальным
  тестовым кадром, а не только списком кодеков: свежие сборки ffmpeg требуют драйвер NVIDIA
  610+, поэтому на старом драйвере видео перекодируется на CPU, а CUDA-ускорение продолжает
  работать.
* **LLM** — Vulkan-сборка llama.cpp работает на любом GPU (NVIDIA/AMD/Intel) и на 7B выдаёт
  ~30 tok/s. CUDA-сборка llama.cpp требует более нового драйвера и по умолчанию не используется.

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

`upload → (download) → probe → (transcode) → thumbnail → audio 16k mono → Whisper/Vosk →
пунктуация → (перевод → озвучка) → чанки → эмбеддинги → конспект и структура → ready`

* Для импорта по ссылке первая стадия — `download` (yt-dlp), затем обычный пайплайн.
* Конспект выбирает один из двух режимов (`api` / `local`); API-режим добавляет
  подстадии `notes_map → notes_outline → notes_details → notes_summary`. Если оба
  бэкенда недоступны, срабатывает экстрактивный фолбэк без модели.
* Отдельная задача `kind=notes` пересобирает только конспект по сохранённому транскрипту —
  режимы можно сравнивать без повторного распознавания.

* Прогресс каждой стадии пишется в `lectures` и `jobs`; UI получает его через SSE.
* Обработка идёт в отдельном потоке, HTTP-запрос возвращается сразу (202 Accepted).
* При падении процесса незавершённые задачи перезапускаются при старте (recovery).
* Повторная обработка идемпотентна: старые сегменты/чанки/разделы заменяются только после
  успешного распознавания.

### Поиск

1. **Dense recall** — косинусная близость к чанкам (bge-m3, кэш матрицы в памяти), откалиброванная
   z-скорингом по корпусу: «лучший из плохих» не превращается в 100 % релевантности.
2. **Lexical recall** — `websearch_to_tsquery('russian')` + `ts_rank_cd`, GIN-индекс.
3. **Точные термины** — `C++`, `C#`, `.NET`: полнотекстовый поиск теряет пунктуацию, а эмбеддинги
   не отличают C++ от Java, поэтому термин ищется буквально (с алиасами ASR «плюс плюс»),
   взвешивается по IDF и учитывается в названии лекции.
4. **Fusion** — dense/lexical поддержка, ограниченная покрытием точных терминов.
5. **Rerank** — bge-reranker-v2-m3 пересортировывает топ-6 по окну вокруг найденного слова
   (кэш по запросу); его оценка корректирует, но не отменяет результат поиска.
6. **Отсечка** — фрагменты ниже порога релевантности не показываются; если совпадений нет,
   выдача честно пустая, а не «первые попавшиеся лекции».
7. **Дедупликация** — близкие фрагменты одной лекции схлопываются.

Подробности: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Технологии

| Слой | Стек |
|---|---|
| Фронтенд | React 19, TypeScript, Vite 7, React Router 7, Plyr 3, нативный CSS |
| Бэкенд | Python 3.12, Flask 3, SQLAlchemy 2, waitress, SSE |
| БД | PostgreSQL 17 (полнотекстовый поиск `russian`, JSONB, очередь задач) |
| ASR | faster-whisper + CUDA/CPU, Vosk 0.3.45 (`ru-0.42` / `small-ru-0.22`) |
| Перевод / TTS | DeepSeek API, edge-tts, фрагментная сборка через FFmpeg |
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
| `LLM_MODE` | `local` | режим конспекта по умолчанию: `api` / `local` |
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
| `GET` | `/api/lectures/{id}/subtitles.srt` | те же субтитры в SubRip |
| `GET` | `/api/lectures/{id}/voiceover` | дополнительная дорожка перевода |
| `GET` | `/api/search?q=…` | семантический поиск (по лекции или курсу) |
| `POST` | `/api/lectures/{id}/qa` | вопрос по лекции |
| `GET` | `/api/public/lectures` | публичный каталог |
| `GET` | `/api/public/groups` | публичные группы с видео и готовой шпаргалкой |
| `GET` | `/api/public/groups/{id}/exam` | шпаргалка публичной группы для любого пользователя |
| `GET`/`POST` | `/api/groups/{id}/exam` | шпаргалка к экзамену: чтение и пересборка |
| `GET` | `/api/recommendations` | персональная лента «Для Вас» |
| `POST` | `/api/public/lectures/{id}/view` | учёт просмотра и сигнал для рекомендаций |
| `POST` | `/api/auth/register`, `/api/auth/login` | сессия пользователя |
| `GET` | `/api/health`, `/api/stats` | состояние и статистика |

---

## CLI

```powershell
.venv\Scripts\python.exe backend\manage.py init-db
.venv\Scripts\python.exe backend\manage.py ingest videos_examples\пример_1.mp4 --title "Геометрия"
.venv\Scripts\python.exe backend\manage.py list
.venv\Scripts\python.exe backend\manage.py stats
.venv\Scripts\python.exe backend\manage.py normalize-categories
```

---

## Структура репозитория

```
backend/
  app/
    api/          REST-эндпоинты (lectures, search, qa, sharing, recommendations, system)
    services/     asr/whisper, translation/TTS, media, embeddings, reranker,
                  llm, summarizer, search, recommendations, pipeline, jobs
    utils/        текст, таймкоды
    models.py     схема БД
    config.py     настройки из .env
  manage.py       CLI
  serve.py        production-запуск (waitress)
frontend/
  src/
    api/          типы и клиент
    components/   плеер, таймлайн, транскрипт, панели, модалки
    pages/        библиотека, публичная библиотека, лекция, поиск, вход
    styles/       дизайн-система (CSS-переменные)
scripts/          bootstrap / setup / install_assets / run / stop / capture_screenshots
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
| Поиск, первый запрос | ~2,5 с (реранкер на CPU) |
| Поиск, повторный запрос | ~20 мс (кэш эмбеддинга и реранка) |
| Полная обработка 7,5 мин | ~4–6 мин (после прогрева) |

---

## Ограничения и развитие

* Vosk не расставляет знаки препинания — работает детерминированное восстановление,
  при `PUNCTUATION_MODE=llm` подключается редактура локальной моделью.
* Качество ASR зависит от записи и языка. Whisper выбран основным точным движком, Vosk —
  полностью локальным резервом для русской речи.
* Перевод доступен только в режиме DeepSeek API: локальная Qwen предназначена для
  конспектов и Q&A и не подменяет переводчик.
* edge-tts зависит от внешнего сервиса. Текст режется на части, каждая часть повторяется до
  трёх раз и кэшируется, а готовая дорожка собирается через FFmpeg.
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
