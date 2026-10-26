import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { QaMessage } from "../api/types";
import { useToast } from "../context/ToastContext";
import { ChatIcon, SparkIcon } from "./icons";

interface Props {
  lectureId: string;
  suggestions: string[];
  onSeek: (seconds: number) => void;
  askRequest?: (question: string) => Promise<import("../api/types").QaResponse>;
  hideHistory?: boolean;
}

export function QaPane({ lectureId, suggestions, onSeek, askRequest, hideHistory = false }: Props) {
  const toast = useToast();
  const [messages, setMessages] = useState<QaMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    if (hideHistory) {
      setLoadingHistory(false);
      setMessages([]);
      return;
    }
    api
      .qaHistory(lectureId)
      .then((response) => {
        if (!cancelled) setMessages(response.items);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setLoadingHistory(false);
      });
    return () => {
      cancelled = true;
    };
  }, [lectureId, hideHistory]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const ask = async (text?: string) => {
    const value = (text ?? question).trim();
    if (value.length < 3 || busy) return;
    setQuestion("");
    setBusy(true);
    const optimistic: QaMessage = {
      id: Date.now(),
      role: "user",
      content: value,
      citations: [],
      grounded: true,
      created_at: null,
    };
    setMessages((current) => [...current, optimistic]);
    try {
      const response = await (askRequest ? askRequest(value) : api.ask(lectureId, value));
      setMessages((current) => [
        ...current.filter((message) => message.id !== optimistic.id),
        response.question,
        response.answer,
      ]);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Не удалось получить ответ";
      toast.error(message);
      setMessages((current) => current.filter((item) => item.id !== optimistic.id));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="qa">
      <div className="row row--between">
        <span className="row" style={{ gap: 8 }}>
          <ChatIcon size={16} style={{ color: "var(--accent-2)" }} />
          <span className="panel__title">Вопросы по лекции</span>
        </span>
        <span className="panel__hint">ответы по фрагментам, без выдумок</span>
      </div>

      <div className="qa__scroll" ref={scrollRef}>
        {loadingHistory && <span className="small muted">Загружаем историю…</span>}
        {!loadingHistory && messages.length === 0 && (
          <div className="empty" style={{ padding: 26 }}>
            <div className="empty__icon" style={{ width: 42, height: 42 }}>
              <SparkIcon size={18} />
            </div>
            <div className="empty__title">Спросите что угодно по этой лекции</div>
            <p className="small">
              Ответ строится только на расшифровке — каждое утверждение можно проверить по таймкоду.
            </p>
          </div>
        )}

        {messages.map((message) => (
          <div key={message.id} className={`qa__msg ${message.role === "user" ? "qa__msg--user" : ""}`}>
            <div className="qa__bubble">{message.content}</div>
            {message.citations.length > 0 && (
              <div className="qa__citations">
                {message.citations.map((citation, index) => (
                  <button
                    key={`${citation.start_sec}-${index}`}
                    className="chip chip--button"
                    onClick={() => onSeek(citation.start_sec)}
                    title={citation.text}
                  >
                    <span className="chip__time">{citation.timestamp}</span>
                    {citation.lecture_title.slice(0, 28)}
                    {citation.lecture_title.length > 28 ? "…" : ""}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}

        {busy && (
          <div className="qa__msg">
            <div className="qa__bubble">
              <span className="typing">
                <span />
                <span />
                <span />
              </span>
            </div>
          </div>
        )}
      </div>

      {messages.length === 0 && suggestions.length > 0 && (
        <div className="qa__suggestions">
          {suggestions.slice(0, 3).map((suggestion) => (
            <button key={suggestion} className="chip chip--button" onClick={() => ask(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
      )}

      <div className="qa__input">
        <textarea
          placeholder="Спросите что-нибудь по этой лекции…"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void ask();
            }
          }}
          rows={1}
          disabled={busy}
        />
        <button className="btn btn--primary" onClick={() => ask()} disabled={busy || question.trim().length < 3}>
          {busy ? <span className="spinner" /> : "Спросить"}
        </button>
      </div>
    </div>
  );
}
