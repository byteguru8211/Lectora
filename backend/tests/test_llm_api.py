"""Unit tests for the DeepSeek API client, mode registry and API notes pipeline.

No network and no database: the proxy session is faked, so these tests stay
fast and deterministic while still exercising retries, session isolation,
prompt limits and the multi-pass conspectus merge.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.asr import Segment
from app.services.llm_api import ApiLlmClient
from app.services.llm_base import LlmUnavailable, OpenAiCompatClient
from app.services.llm_modes import (
    MODE_API,
    MODE_LOCAL,
    MODE_OFFLINE,
    fallback_chain,
    normalize_mode,
)
from app.services.summarizer import Summarizer


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = text or json.dumps(self._payload)
        self.content = b"{}"

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls: list[tuple[str, dict]] = []

    def _next(self):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._next()

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._next()


def completion(text: str) -> FakeResponse:
    return FakeResponse(
        payload={
            "choices": [
                {
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"completion_tokens": 10},
        }
    )


def make_client(**kwargs) -> ApiLlmClient:
    options = {
        "enabled": True,
        "base_url": "http://proxy.local/v1",
        "model": "deepseek-chat",
        "api_key": "",
        "timeout": 5.0,
        "min_interval": 0.0,
        "max_concurrent": 1,
        "retries": 1,
        "retry_base": 0.0,
        "retry_max": 0.0,
        "queue_timeout": 5.0,
        "reset_session": True,
    }
    options.update(kwargs)
    return ApiLlmClient(**options)


# ---------------------------------------------------------------- json
def test_extract_json_accepts_raw_newlines_inside_strings():
    raw = '{"details": "первый абзац\n\nвторой абзац", "index": 1}'
    data = OpenAiCompatClient.extract_json(raw)
    assert data["index"] == 1
    assert "второй абзац" in data["details"]


def test_extract_json_strips_fence_and_trailing_comma():
    raw = '```json\n{"a": 1, "b": [1, 2,],}\n```'
    assert OpenAiCompatClient.extract_json(raw) == {"a": 1, "b": [1, 2]}


# ---------------------------------------------------------------- client
def test_chat_uses_ephemeral_session_and_resets_it():
    client = make_client()
    fake = FakeSession([completion("ответ"), FakeResponse()])
    client._session = fake

    assert client.chat([{"role": "user", "content": "привет"}]) == "ответ"

    chat_url, chat_kwargs = fake.calls[0]
    assert chat_url == "http://proxy.local/v1/chat/completions"
    session_key = chat_kwargs["json"]["user"]
    assert session_key.startswith("lectora-")
    assert chat_kwargs["json"]["model"] == "deepseek-chat"
    assert chat_kwargs["json"]["stream"] is False

    reset_url, reset_kwargs = fake.calls[-1]
    assert reset_url == "http://proxy.local/reset-session"
    assert reset_kwargs["params"]["agent"] == session_key


def test_chat_retries_rate_limit_and_honours_retry_after():
    client = make_client(retries=2)
    fake = FakeSession(
        [
            FakeResponse(status=429, headers={"Retry-After": "0"}, payload={"error": {}}),
            completion("после ретрая"),
            FakeResponse(),
        ]
    )
    client._session = fake

    assert client.chat([{"role": "user", "content": "вопрос"}]) == "после ретрая"
    assert len([call for call in fake.calls if call[0].endswith("/chat/completions")]) == 2


def test_chat_retries_proxy_rate_limit_embedded_in_json():
    client = make_client(retries=2)
    fake = FakeSession(
        [
            FakeResponse(
                payload={"error": {"message": "Too many messages"}},
                headers={"Retry-After": "0"},
            ),
            completion("после кулдауна"),
            FakeResponse(),
        ]
    )
    client._session = fake

    assert client.chat([{"role": "user", "content": "вопрос"}]) == "после кулдауна"
    assert len([call for call in fake.calls if call[0].endswith("/chat/completions")]) == 2


def test_chat_does_not_retry_auth_failures():
    client = make_client(retries=3)
    fake = FakeSession(
        [FakeResponse(status=401, text='{"error":{"message":"bad auth"}}'), FakeResponse()]
    )
    client._session = fake

    with pytest.raises(LlmUnavailable) as excinfo:
        client.chat([{"role": "user", "content": "вопрос"}])
    assert excinfo.value.kind == "auth"
    assert len([call for call in fake.calls if call[0].endswith("/chat/completions")]) == 1


def test_chat_rejects_prompt_above_budget():
    client = make_client(max_prompt_chars=50)
    fake = FakeSession([])
    client._session = fake

    with pytest.raises(LlmUnavailable) as excinfo:
        client.chat([{"role": "user", "content": "x" * 120}])
    assert excinfo.value.kind == "context"
    assert fake.calls == []


def test_health_reports_account_state():
    client = make_client()
    client._session = FakeSession(
        [
            FakeResponse(
                payload={
                    "status": "ok",
                    "service": "FreeDeepseekAPI",
                    "models": ["deepseek-chat"],
                    "config_ready": True,
                    "accounts": [{"id": "account_1", "ready": True, "cooldown": False}],
                }
            )
        ]
    )
    health = client.health(force=True)
    assert health.available is True
    assert health.extra["ready_accounts"] == 1

    client = make_client()
    client._session = FakeSession(
        [
            FakeResponse(
                payload={
                    "models": ["deepseek-chat"],
                    "config_ready": True,
                    "accounts": [{"id": "account_1", "ready": False, "cooldown": True}],
                }
            )
        ]
    )
    health = client.health(force=True)
    assert health.available is False
    assert "кулдауне" in (health.detail or "")


def test_health_falls_back_to_models_when_health_is_missing():
    client = make_client()
    client._session = FakeSession(
        [
            FakeResponse(status=404, text="not found"),
            FakeResponse(payload={"object": "list", "data": [{"id": "deepseek-chat"}]}),
        ]
    )
    health = client.health(force=True)
    assert health.available is True
    assert health.detail is None
    assert [url for url, _ in client._session.calls] == [
        "http://proxy.local/health",
        "http://proxy.local/v1/models",
    ]


# ---------------------------------------------------------------- modes
def test_normalize_mode_aliases():
    assert normalize_mode("api") == MODE_API
    assert normalize_mode("extractive") == MODE_OFFLINE
    assert normalize_mode("qwen") == MODE_LOCAL
    assert normalize_mode(None, "api") == MODE_API
    with pytest.raises(ValueError):
        normalize_mode("gpt-5")


def test_fallback_chains_never_send_local_lectures_to_cloud():
    assert fallback_chain(MODE_API) == [MODE_API, MODE_LOCAL, MODE_OFFLINE]
    assert fallback_chain(MODE_LOCAL) == [MODE_LOCAL, MODE_OFFLINE]
    assert fallback_chain(MODE_OFFLINE) == [MODE_OFFLINE]


def test_resolve_client_falls_back_to_local_when_api_is_down(monkeypatch):
    import app.services.llm_modes as modes

    class FakeClient:
        def __init__(self, available):
            self.available = available

    local = FakeClient(True)
    api = FakeClient(False)
    monkeypatch.setattr(modes, "client_for", lambda mode: {MODE_API: api, MODE_LOCAL: local}.get(mode))
    assert modes.resolve_client(MODE_API) == (MODE_LOCAL, local)
    assert modes.resolve_client(MODE_OFFLINE) == (MODE_OFFLINE, None)


# ---------------------------------------------------------------- summarizer
class ScriptedClient(OpenAiCompatClient):
    """Returns canned JSON depending on which pass calls it."""

    mode = "api"
    model = "fake-deepseek"

    def __init__(self, section_count: int = 6):
        self.section_count = section_count
        self.calls: list[str] = []

    def health(self, *, force: bool = False):  # pragma: no cover - unused
        raise NotImplementedError

    def chat(self, messages: list[dict], **kwargs) -> str:  # pragma: no cover - unused
        raise NotImplementedError

    def chat_json(self, messages, *, max_tokens=None, temperature=None, retries=1, **kwargs):
        prompt = messages[-1]["content"]
        self.calls.append(prompt)
        if "Составь план учебного конспекта" in prompt:
            return {
                "title": "Функторы в C++",
                "category": "Программирование",
                "subcategory": "Функторы",
                "sections": [
                    {
                        "title": f"Раздел {index + 1}",
                        "focus": "Кратко о разделе",
                        "start_sec": index * 60,
                        "end_sec": (index + 1) * 60,
                    }
                    for index in range(self.section_count)
                ],
            }
        if "Ниже фрагменты расшифровки по разделам" in prompt:
            indexes = [
                int(line.split("РАЗДЕЛ ")[1].split(":")[0])
                for line in prompt.splitlines()
                if line.startswith("РАЗДЕЛ ")
            ]
            return {
                "sections": [
                    {
                        "index": index,
                        "summary": (
                            "Подробное описание раздела с формулами и примерами, "
                            "достаточное для подготовки. " * 4
                        ).strip(),
                        "key_points": [f"Тезис {point}" for point in range(1, 6)],
                        "details": (
                            "Первый абзац конспекта.\n\n"
                            "- пункт списка\n- второй пункт\n\n"
                            "Формула \\(V = a^3\\) и итог."
                        ),
                    }
                    for index in indexes
                ]
            }
        if "Составь обзор всей лекции" in prompt:
            return {
                "title": "Функторы в C++: полный разбор",
                "category": "Программирование на C++",
                "subcategory": "Функторы и оператор вызова",
                "summary": " ".join(["слово"] * 155),
                "keywords": [f"термин {index}" for index in range(1, 18)],
                "questions": [f"Вопрос для самопроверки номер {index}?" for index in range(1, 8)],
            }
        raise AssertionError(f"unexpected prompt: {prompt[:120]}")


def test_api_notes_builds_multi_pass_conspectus():
    summarizer = Summarizer()
    client = ScriptedClient(section_count=6)
    segments = [
        Segment(start_sec=index * 10, end_sec=index * 10 + 9, text=f"Текст сегмента {index}.")
        for index in range(40)
    ]
    notes = summarizer._api_notes(
        client=client,
        title="Функторы",
        segments=segments,
        duration_sec=400,
        on_progress=None,
    )
    assert notes is not None
    assert notes.mode == MODE_API
    assert notes.model == "fake-deepseek"
    assert len(notes.sections) == 6
    assert len(notes.summary.split()) >= 140
    assert len(notes.keywords) == 17
    assert len(notes.questions) == 7
    assert all(section.details for section in notes.sections)
    assert all(len(section.key_points) == 5 for section in notes.sections)
    # map pass is skipped for short transcripts: outline + details + overview
    assert any("Составь план" in call for call in client.calls)
    assert any("Ниже фрагменты" in call for call in client.calls)
    assert any("Составь обзор" in call for call in client.calls)


def test_api_notes_falls_back_per_section_when_details_fail():
    class BrokenDetails(ScriptedClient):
        def chat_json(self, messages, **kwargs):
            if "Ниже фрагменты расшифровки по разделам" in messages[-1]["content"]:
                raise LlmUnavailable("boom", kind="server", status=500)
            return super().chat_json(messages, **kwargs)

    summarizer = Summarizer()
    notes = summarizer._api_notes(
        client=BrokenDetails(section_count=4),
        title="",
        segments=[
            Segment(start_sec=index * 10, end_sec=index * 10 + 9, text=f"Мысль номер {index} лекции.")
            for index in range(40)
        ],
        duration_sec=400,
        on_progress=None,
    )
    assert notes is not None
    assert notes.sections
    assert all(section.summary for section in notes.sections)


def test_validate_parses_details_questions_and_extends_short_summary():
    summarizer = Summarizer()
    data = {
        "title": "Тестовая лекция",
        "summary": "Слишком короткий обзор.",
        "sections": [
            {
                "title": f"Раздел {index}",
                "start_sec": index * 60,
                "end_sec": (index + 1) * 60,
                "summary": " ".join([f"предложение{index}"] * 30),
                "key_points": [f"тезис раздела {index} номер {point}" for point in range(5)],
                "details": "Абзац конспекта.\n\n- пункт",
            }
            for index in range(4)
        ],
        "keywords": [f"термин {index}" for index in range(15)],
        "questions": ["Что такое функтор?", "Зачем нужен оператор вызова?"],
    }
    notes = summarizer._validate(data, 240, mode=MODE_API, model="deepseek-chat")
    assert notes is not None
    assert len(notes.summary.split()) >= 140
    assert len(notes.sections) == 4
    assert notes.sections[0].details == "Абзац конспекта.\n\n- пункт"
    assert len(notes.questions) == 2
    assert notes.mode == MODE_API
