import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { LlmMode, LlmModeInfo, NotesModeUsed } from "../api/types";
import { LLM_MODES, LLM_MODE_META, isLlmMode } from "../utils/llm";
import { CloseIcon, SparkIcon } from "./icons";

interface Props {
  open: boolean;
  initialMode: NotesModeUsed;
  usedMode: NotesModeUsed | null;
  busy?: boolean;
  onSubmit: (mode: LlmMode) => void;
  onClose: () => void;
}

export function NotesModeDialog({ open, initialMode, usedMode, busy = false, onSubmit, onClose }: Props) {
  const [mode, setMode] = useState<LlmMode>(() => (isLlmMode(initialMode) ? initialMode : "api"));
  const [modes, setModes] = useState<Record<LlmMode, LlmModeInfo> | null>(null);

  useEffect(() => {
    if (!open) return;
    setMode(isLlmMode(initialMode) ? initialMode : "api");
  }, [open, initialMode]);

  useEffect(() => {
    if (!open) return;
    api.systemInfo().then((info) => {
      const next = info.llm?.modes ?? null;
      setModes(next);
      const current = next && isLlmMode(initialMode) ? next[initialMode] : null;
      if (current && !current.selectable) {
        const fallback = LLM_MODES.find((value) => next?.[value]?.selectable);
        if (fallback) setMode(fallback);
      }
    }).catch(() => setModes(null));
  }, [open, initialMode]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  const availability = (value: LlmMode): string | null => {
    const info = modes?.[value];
    if (!info) return null;
    if (!info.enabled) return "отключено в настройках";
    if (!info.available) return info.detail || "сейчас недоступно";
    if (info.mode === "api" && info.latency_ms != null) return `готово · ${info.model}`;
    if (info.mode === "local") return `готово · ${info.model}`;
    return "всегда доступно";
  };

  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => event.target === event.currentTarget && !busy && onClose()}
    >
      <div className="modal" style={{ maxWidth: 560 }} role="dialog" aria-modal="true" aria-label="Режим конспекта">
        <div className="modal__head">
          <div>
            <h2 className="modal__title">Собрать конспект заново</h2>
            <p className="small muted" style={{ marginTop: 4 }}>
              Расшифровка и поисковый индекс сохранятся — изменится только конспект.
            </p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Закрыть" disabled={busy}>
            <CloseIcon />
          </button>
        </div>

        <div className="modal__body">
          <div className="stack" style={{ gap: 8 }}>
            {LLM_MODES.map((value) => {
              const info = modes?.[value];
              const status = availability(value);
              const selectable = info ? info.selectable : true;
              return (
                <button
                  key={value}
                  className={`llm-mode-card ${mode === value ? "is-active" : ""}`}
                  onClick={() => setMode(value)}
                  disabled={busy || !selectable}
                  title={status ?? undefined}
                >
                  <span className="llm-mode-card__icon">
                    <SparkIcon size={17} />
                  </span>
                  <span className="llm-mode-card__text">
                    <strong>{LLM_MODE_META[value].label}</strong>
                    <small>{LLM_MODE_META[value].description}</small>
                    {status && (
                      <span className={`llm-mode-card__status ${info?.available ? "is-ok" : "is-off"}`}>
                        {status}
                      </span>
                    )}
                  </span>
                  {usedMode === value && <span className="chip chip--tiny">текущий</span>}
                </button>
              );
            })}
          </div>

          <p className="small muted" style={{ marginTop: 12 }}>
            {mode === "api"
              ? "DeepSeek собирает конспект по частям: обычно 2–4 минуты. Прогресс виден на странице лекции."
              : "Локальная модель отвечает быстрее, но конспект компактнее."}
          </p>
        </div>

        <div className="modal__foot">
          <button className="btn btn--ghost" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button
            className="btn btn--primary"
            onClick={() => onSubmit(isLlmMode(mode) ? mode : "api")}
            disabled={busy}
          >
            {busy ? <span className="spinner" /> : <SparkIcon size={15} />}
            {usedMode === mode ? "Собрать заново" : "Собрать конспект"}
          </button>
        </div>
      </div>
    </div>
  );
}
