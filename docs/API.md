# API

Базовый адрес: `http://127.0.0.1:8000/api`. Формат — JSON UTF-8. Аутентификации нет
(локальный запуск). Ошибки приходят в едином конверте:

```json
{ "error": { "code": "lecture_not_found", "message": "Лекция не найдена" } }
```

## Лекции

### `GET /lectures`

Параметры: `status` (`ready`, `processing`, `failed`, `all`), `q` (поиск по названию и
описанию), `limit`, `offset`.

```json
{ "items": [ { "id": "…", "title": "…", "status": "ready", "progress": 100, … } ],
  "total": 1 }
```

### `POST /lectures` (multipart)

Поля: `file` (обязательно), `title`, `description`, `asr_profile` (`accurate` | `fast`).

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/lectures `
  -F "file=@videos_examples\пример_1.mp4" `
  -F "title=Геометрия: тела вращения" `
  -F "asr_profile=accurate"
```

Ответ `202`:

```json
{ "id": "f5f14a72-…", "status": "queued", "job_id": 1, … }
```

### `POST /lectures/import`

```json
{ "url": "https://www.youtube.com/watch?v=…", "title": "Необязательно", "asr_profile": "fast" }
```

Требует `tools/yt-dlp/yt-dlp.exe`; иначе `501 ytdlp_missing`.

### `GET /lectures/{id}`

Карточка + конспект + структура. Увеличивает счётчик просмотров.

### `PATCH /lectures/{id}`

```json
{ "title": "Новое название", "description": "…" }
```

### `DELETE /lectures/{id}`

Удаляет запись, файлы и индекс. Ответ `204`.

### `POST /lectures/{id}/reprocess`

Перезапускает пайплайн. Можно сменить профиль: `{ "asr_profile": "fast" }`.

### `GET /lectures/{id}/status`

Лёгкий эндпоинт для поллинга:

```json
{ "status": "processing", "stage": "transcribe", "stage_label": "Распознавание речи",
  "progress": 42.5, "error_message": null, "job": { … } }
```

### `GET /lectures/{id}/transcript`

```json
{ "duration_sec": 451.86,
  "segments": [ { "idx": 0, "start_sec": 0.0, "end_sec": 9.2,
                  "timestamp": "0:00", "text": "Всем привет…" } ] }
```

### `GET /lectures/{id}/structure`

```json
{ "summary": "…", "keywords": ["параллелепипед", "…"],
  "sections": [ { "idx": 0, "title": "Прямоугольный параллелепипед",
                  "start_sec": 0, "end_sec": 42, "timestamp": "0:00",
                  "summary": "…", "key_points": ["…"] } ],
  "llm_model": "qwen2.5-7b-instruct" }
```

### `GET /lectures/{id}/events` (SSE)

```
event: progress
data: {"status":"processing","stage":"transcribe","progress":42.5,…}

event: done
data: {"status":"ready","progress":100,…}
```

### `GET /lectures/{id}/media`

Видео с `Accept-Ranges: bytes` (перемотка). `GET /thumbnail` — превью JPEG.
`GET /subtitles.vtt` — субтитры WebVTT.

## Поиск

### `GET /search`

Параметры: `q` (обязательно, ≥2 символов), `lecture_id` (поиск внутри лекции),
`limit` (1–50), `rerank` (`0`/`1`).

```json
{
  "query": "формула объёма конуса",
  "scope": "course",
  "took_ms": 1893,
  "reranked": true,
  "candidates": 10,
  "results": [
    {
      "chunk_id": 7,
      "lecture": { "id": "…", "title": "пример_1" },
      "start_sec": 272.4, "end_sec": 310.1, "timestamp": "4:32",
      "snippet": "…объём конуса…",
      "spans": [ { "start": 42, "end": 55 } ],
      "scores": { "dense": 0.71, "lexical": 0.32, "fused": 1.04, "rerank": 0.99, "final": 0.99 }
    }
  ]
}
```

`spans` — диапазоны для подсветки в исходном `snippet`.

### `GET /search/suggest?q=…`

Подсказки из названий лекций, разделов и истории запросов.

## Q&A

### `GET /lectures/{id}/qa`

История диалога (последние 40 сообщений).

### `POST /lectures/{id}/qa`

```json
{ "question": "Что такое прямоугольный параллелепипед?" }
```

```json
{
  "llm_used": true,
  "answer": {
    "role": "assistant",
    "content": "Прямоугольный параллелепипед — это…",
    "citations": [
      { "lecture_id": "…", "timestamp": "0:00", "start_sec": 0, "text": "…" }
    ],
    "grounded": true
  },
  "question": { "role": "user", "content": "…" }
}
```

## Служебные

| Метод | Путь | Ответ |
|---|---|---|
| `GET` | `/health` | проверки БД, ffmpeg, моделей, LLM; `503` при критических проблемах |
| `GET` | `/system/info` | конфигурация и пути к инструментам |
| `GET` | `/stats` | счётчики лекций, длительность, поиск, хранилище |
| `GET` | `/lectures/queue/status` | размер очереди и последние задачи |

`GET /health`:

```json
{
  "status": "ok",
  "checks": {
    "database": { "ok": true },
    "ffmpeg": { "ok": true },
    "asr_models": { "ok": true, "profiles": { "accurate": true, "fast": true } },
    "embeddings": { "ok": true },
    "reranker": { "ok": true },
    "llm": { "enabled": true, "available": true, "model": "qwen2.5-7b-instruct" },
    "url_import": { "ok": false }
  },
  "took_ms": 12
}
```

## Коды ошибок

| Код | HTTP | Когда |
|---|---|---|
| `file_required` | 400 | нет файла в загрузке |
| `unsupported_media` | 415 | расширение не из белого списка |
| `file_too_large` | 413 | превышен `MAX_UPLOAD_MB` |
| `lecture_not_found` | 404 | нет лекции |
| `lecture_not_ready` | 409 | поиск/вопрос до окончания обработки |
| `already_processing` | 409 | повторный запуск обработки |
| `asr_model_missing` | 503 | нет моделей Vosk |
| `ffmpeg_missing` | 503 | не найден ffmpeg |
| `ytdlp_missing` | 501 | импорт по ссылке недоступен |
| `query_too_short` | 400 | запрос короче 2 символов |
| `internal_error` | 500 | непредвиденная ошибка (детали в логе) |
