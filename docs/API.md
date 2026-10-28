# API

Базовый адрес: `http://127.0.0.1:8000/api`. Формат — JSON UTF-8. Ошибки приходят в едином
конверте:

```json
{ "error": { "code": "lecture_not_found", "message": "Лекция не найдена" } }
```

## Аутентификация

Сессия в подписанной cookie (`HttpOnly`, `SameSite=Lax`). Регистрация и вход сразу
устанавливают cookie, поэтому `curl` должен сохранять её (`-c cookies.txt -b cookies.txt`).

| Метод | Путь | Тело | Ответ |
|---|---|---|---|
| `POST` | `/auth/register` | `{ "name", "email", "password", "role": "student" \| "teacher" }` | `201 { "user": { … } }` |
| `POST` | `/auth/login` | `{ "email", "password" }` | `200 { "user": { … } }` |
| `POST` | `/auth/logout` | — | `204` |
| `GET` | `/auth/me` | — | `200 { "user": { … } }` |
| `PATCH` | `/auth/me` | `{ "name" }` | `200 { "user": { … } }` — имя от 2 до 120 символов |
| `POST` | `/auth/password` | `{ "current_password", "new_password" }` | `200 { "ok": true }` — новый пароль не короче 8 символов |

`/lectures*`, `/groups*`, `/recommendations` и `/stats` требуют входа; публичные маршруты
`/public/*` и `/shared/*` доступны гостям.

## Лекции

### `GET /lectures`

Параметры: `status` (`ready`, `processing`, `failed`, `all`), `q` (поиск по названию и
описанию), `limit`, `offset`.

```json
{ "items": [ { "id": "…", "title": "…", "status": "ready", "progress": 100, … } ],
  "total": 1 }
```

### `POST /lectures` (multipart)

Поля: `file` (обязательно), `title`, `description`, `asr_profile` (`accurate` | `fast`),
`asr_engine` (`vosk` | `whisper`), `use_gpu` (`true`/`false`), `llm_mode` (`api` | `local`),
`language` (`ru` | `en`), `target_language` (`ru` | `en`, необязательно), `voiceover`
(`true`/`false`), `visibility` (`private` | `public`), `group_id`.

`target_language` должен отличаться от исходного. Перевод разрешён только при
`llm_mode=api`; локальная модель не используется как переводчик. `voiceover=true`
допустим только вместе с переводом.

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/lectures `
  -F "file=@videos_examples\пример_1.mp4" `
  -F "title=Геометрия: тела вращения" `
  -F "asr_profile=accurate" `
  -F "llm_mode=api" `
  -F "language=ru" `
  -F "target_language=en" `
  -F "voiceover=true"
```

Ответ `202`:

```json
{ "id": "f5f14a72-…", "status": "queued", "job_id": 1, … }
```

### `POST /lectures/import`

```json
{ "url": "https://www.youtube.com/watch?v=…", "title": "Необязательно",
  "asr_profile": "fast", "llm_mode": "api", "language": "en",
  "target_language": "ru", "voiceover": true }
```

Требует `tools/yt-dlp/yt-dlp.exe`; иначе `501 ytdlp_missing`.

### `GET /lectures/{id}`

Карточка + конспект + структура. Увеличивает счётчик просмотров. Поле `title_auto` показывает,
что название сгенерировано по содержанию (и будет обновлено при переобработке).

### `PATCH /lectures/{id}`

```json
{ "title": "Новое название", "description": "…", "visibility": "public",
  "group_id": "uuid-или-null" }
```

### `DELETE /lectures/{id}`

Удаляет запись, файлы и индекс. Ответ `204`.

### `POST /lectures/{id}/reprocess`

Перезапускает пайплайн. Можно сменить профиль и режим конспекта:
`{ "asr_profile": "fast", "llm_mode": "api" }`.

### `POST /lectures/{id}/notes`

Пересобирает только конспект по сохранённому транскрипту — ASR и индекс не затрагиваются.
Ответ `202` с `job_id`; прогресс идёт через SSE, стадии `notes_*`.

```json
{ "llm_mode": "api" }
```

Режимы: `api` — DeepSeek Web (подробно, 6–14 разделов), `local` — локальная LLM.
Если выбранный бэкенд недоступен, сработает резервный, а в крайнем случае — экстрактивный
алгоритм без модели; фактический режим вернётся в поле `llm_mode_used` (может быть
`offline` — маркер аварийного фолбэка).

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
                  "timestamp": "0:00", "text": "Hello…",
                  "translated_text": "Привет…" } ] }
```

### `GET /lectures/{id}/structure`

```json
{ "summary": "…", "keywords": ["параллелепипед", "…"],
  "questions": ["Что такое параллелепипед?", "…"],
  "sections": [ { "idx": 0, "title": "Прямоугольный параллелепипед",
                  "start_sec": 0, "end_sec": 42, "timestamp": "0:00",
                  "summary": "…", "key_points": ["…"],
                  "details": "## Определение\n\nПодробный конспект раздела…" } ],
  "llm_model": "deepseek-chat",
  "llm_mode": "api", "llm_mode_used": "api" }
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
`GET /subtitles.vtt?lang=ru|en` — WebVTT на выбранном доступном языке.
`GET /subtitles.srt?lang=ru|en` — те же субтитры в SubRip для плееров и редакторов.
`GET /voiceover` — сгенерированная дополнительная MP3-дорожка перевода.

## Поиск

### `GET /search`

Параметры: `q` (обязательно, ≥2 символов), `lecture_id` (поиск внутри лекции),
`limit` (1–50), `rerank` (`0`/`1`).

```json
{
  "query": "C++ указатели",
  "scope": "course",
  "took_ms": 2490,
  "reranked": true,
  "candidates": 8,
  "results": [
    {
      "chunk_id": 7,
      "lecture": { "id": "…", "title": "Функторы в C++" },
      "start_sec": 272.4, "end_sec": 310.1, "timestamp": "4:32",
      "snippet": "…в C++ указатель…",
      "spans": [ { "start": 2, "end": 5 } ],
      "scores": {
        "dense": 0.52, "lexical": 0.0, "exact": 1.0,
        "fused": 0.72, "rerank": 0.37, "final": 0.72
      }
    }
  ]
}
```

`scores`:

| Поле | Значение |
|---|---|
| `dense` | сырая косинусная близость bge-m3 |
| `lexical` | `ts_rank_cd` полнотекстового поиска (для запроса без обычных слов — `0`) |
| `exact` | покрытие технических терминов (`C++`, `C#`, `.NET`) с учётом IDF и названия лекции; есть только если в запросе был такой термин |
| `fused` | итог гибридного ранжирования до реранка |
| `rerank` | вероятность bge-reranker (если реранкер доступен) |
| `final` | итоговая релевантность: `fused`, скорректированный реранком и отсечённый порогом |

`spans` — диапазоны для подсветки в исходном `snippet`. Технические термины подсвечиваются
целиком (`C++`, а не буква «c»). Если ни один фрагмент не прошёл порог релевантности,
`results` пустой — поиск не подменяет ответ «первыми попавшимися» лекциями.

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
  "llm_mode": "api",
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

## Публичная библиотека и группы

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/groups` | группы пользователя со счётчиком видео |
| `POST` | `/groups` | создать группу (`name`, `description`, `visibility`) |
| `PATCH` | `/groups/{id}` | переименовать или сменить видимость |
| `POST` | `/groups/{id}/share` | выпустить токен приватной ссылки |
| `GET` | `/groups/{id}/exam` | сохранённая шпаргалка к экзамену по группе |
| `POST` | `/groups/{id}/exam` | собрать или пересобрать шпаргалку (`mode`: `api`/`local`) |
| `POST` | `/lectures/{id}/share` | выпустить токен ссылки на лекцию |
| `GET` | `/public/lectures` | каталог: публичные лекции и лекции публичных групп |
| `GET` | `/public/lectures/{id}` | карточка, конспект и структура публичной лекции |
| `GET` | `/public/lectures/{id}/media` | видео с поддержкой Range |
| `GET` | `/public/lectures/{id}/transcript` | транскрипт с таймкодами |
| `GET` | `/public/lectures/{id}/subtitles.vtt?lang=…` | субтитры выбранного языка |
| `GET` | `/public/lectures/{id}/subtitles.srt?lang=…` | те же субтитры в SubRip |
| `GET` | `/public/lectures/{id}/voiceover` | дополнительная озвучка |
| `GET` | `/public/lectures/{id}/search?q=…` | поиск внутри лекции |
| `POST` | `/public/lectures/{id}/qa` | вопрос по лекции |
| `GET` | `/public/groups` | каталог публичных групп с готовыми лекциями |
| `GET` | `/public/groups/{id}` | группа: карточки лекций, автор и признак готовой шпаргалки |
| `GET` | `/public/groups/{id}/exam` | шпаргалка публичной группы (только чтение) |
| `POST` | `/public/groups/{id}/exam` | собрать или пересобрать шпаргалку публичной группы (нужен вход) |
| `GET` | `/shared/videos/{token}` | лекция по приватной ссылке |
| `GET` | `/shared/groups/{token}` | группа по приватной ссылке |
| `GET` | `/shared/groups/{token}/exam` | шпаргалка группы по приватной ссылке (только чтение) |
| `GET` | `/shared/groups/{token}/lectures/{id}/subtitles.srt?lang=…` | SubRip в общей группе |
| `GET` | `/shared/videos/{token}/transcript` | транскрипт по приватной ссылке |
| `GET` | `/shared/videos/{token}/subtitles.vtt?lang=…` | субтитры по приватной ссылке |
| `GET` | `/shared/videos/{token}/subtitles.srt?lang=…` | SubRip по приватной ссылке |
| `GET` | `/shared/videos/{token}/voiceover` | озвучка по приватной ссылке |

Каталог: `{ "items": [ { "id": "…", "title": "…", "owner_name": "…", "group_name": "…",
"thumbnail_url": "/api/public/lectures/{id}/thumbnail", … } ] }`.

### Шпаргалка к экзамену

`GET /groups/{id}/exam` отдаёт сохранённую шпаргалку группы, `POST` — собирает её заново.
Новых стадий обработки нет: шпаргалка строится по уже готовым конспектам (билеты, определения,
формулы, полный текст), один вызов модели на слияние либо детерминированное извлечение, если
модель недоступна.

```json
{
  "status": "ready", "stale": false,
  "lecture_count": 2, "current_lecture_count": 2,
  "tickets": [ { "question": "…", "answer": "…", "lecture_id": "…",
                 "lecture_title": "…", "start_sec": 41, "timestamp": "0:41" } ],
  "definitions": [ { "term": "…", "definition": "…", "timestamp": "…" } ],
  "formulas": [ { "formula": "\\int_a^b f(x)\\,dx", "meaning": "…", "timestamp": "…" } ],
  "cheatsheet_md": "## Тема\n\n…",
  "llm_mode": "api", "llm_mode_used": "offline", "generation_ms": 26,
  "generated_at": "2026-10-28T02:43:00+03:00",
  "can_generate": true, "mode_hint": "api"
}
```

`status` — `missing` или `ready`. `stale: true` означает, что конспекты изменились после
сборки (сравнивается отпечаток заголовков, сводок, тезисов и разделов — счётчики просмотров
на него не влияют). `POST` без готовых лекций отвечает `409 no_ready_lectures`.
`GET /shared/groups/{token}/exam` возвращает то же без права пересборки.

Публичная группа читается без входа: `GET /public/groups` отдаёт `id`, `name`, `description`,
`owner_name`, `video_count`, `duration_sec` и `exam_ready`, поэтому шпаргалку можно открыть,
даже если вы не владелец группы. `POST /public/groups/{id}/exam` требует авторизации —
сборка запускает модель, и анонимный вызов был бы бесплатной нагрузкой на сервер.

## Рекомендации

### `GET /recommendations?limit=12`

Персональная лента «Для Вас». Профиль строится из готовых лекций пользователя (сильный
сигнал) и первых просмотров публичных видео (слабый сигнал). Свои лекции в выдачу не
попадают; `limit` — 1–30.

```json
{
  "mode": "personalized",
  "fallback": false,
  "interests": [
    { "label": "Программирование на C++", "kind": "subject", "weight": 5.0 },
    { "label": "Функторы в C++", "kind": "topic", "weight": 3.5 }
  ],
  "items": [
    {
      "id": "…", "title": "Продвинутые функторы C++", "owner_name": "…",
      "thumbnail_url": "/api/public/lectures/…/thumbnail",
      "recommendation": {
        "score": 1.0,
        "reason": "Темы: «Программирование на C++», «Функторы в C++»",
        "matched_topics": ["Программирование на C++", "Функторы в C++"],
        "personalized": true
      }
    }
  ],
  "generated_at": "2026-10-27T18:37:10Z"
}
```

`mode`: `personalized` — есть совпадения по интересам; `trending` — профиль есть, но
совпадений нет; `cold_start` — сигналов ещё нет, лента собрана по популярности и свежести.
В `trending`/`cold_start` карточки приходят с `personalized: false`. Если совпадений
меньше четырёх, лента добирается популярными видео с пометкой «Популярное на платформе».

### `POST /public/lectures/{id}/view`

Счётчик просмотров. Гость увеличивает `view_count` и получает `tracked: false`;
авторизованный пользователь дополнительно попадает в `lecture_views`, а при первом
просмотре пересобирается его профиль интересов.

```json
{ "tracked": true, "view_count": 12, "first_view": true }
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
    "llm": { "enabled": true, "available": true, "model": "qwen2.5-7b-instruct", "mode": "local" },
    "llm_api": { "enabled": true, "available": true, "model": "deepseek-chat", "mode": "api",
                 "extra": { "ready_accounts": 1, "accounts": 1 } },
    "url_import": { "ok": false }
  },
  "took_ms": 12
}
```

## Коды ошибок

| Код | HTTP | Когда |
|---|---|---|
| `authentication_required` | 401 | нет активной сессии |
| `invalid_credentials` | 401 | неверный email или пароль |
| `email_exists` | 409 | аккаунт с таким email уже есть |
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
| `bad_llm_mode` | 400 | неизвестный режим конспекта |
| `translation_requires_api` | 400 | перевод выбран вместе с локальной LLM |
| `translation_api_unavailable` | 503 | DeepSeek API недоступен во время перевода |
| `translation_incomplete` | 503 | API вернул не все сегменты перевода |
| `voiceover_requires_translation` | 400 | озвучка включена без языка перевода |
| `tts_unavailable` | 503 | модуль озвучки не установлен |
| `tts_failed` | 503 | не удалось создать фрагмент или собрать дорожку |
| `transcript_missing` | 409 | пересборка конспекта до расшифровки |
| `worker_disabled` | 503 | фоновый воркер не запущен |
| `internal_error` | 500 | непредвиденная ошибка (детали в логе) |
