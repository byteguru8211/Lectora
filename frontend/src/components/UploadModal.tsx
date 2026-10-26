import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, uploadLecture } from "../api/client";
import { useToast } from "../context/ToastContext";
import { formatBytes } from "../utils/format";
import { CloseIcon, DownloadIcon, LinkIcon, UploadIcon } from "./icons";

interface Props {
  open: boolean;
  onClose: () => void;
  initialMode?: "file" | "url";
}

const ACCEPT = ".mp4,.webm,.mov,.m4v,.mkv,.avi,.mp3,.m4a,.wav,.ogg";

export function UploadModal({ open, onClose, initialMode = "file" }: Props) {
  const navigate = useNavigate();
  const toast = useToast();
  const inputRef = useRef<HTMLInputElement>(null);

  const [mode, setMode] = useState<"file" | "url">(initialMode);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [profile, setProfile] = useState<"accurate" | "fast">("accurate");
  const [url, setUrl] = useState("");
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (!open) return;
    setMode(initialMode);
    setFile(null);
    setTitle("");
    setDescription("");
    setUrl("");
    setError(null);
    setProgress(0);
    setBusy(false);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, initialMode, busy, onClose]);

  const pickFile = useCallback((next: File | null) => {
    if (!next) return;
    setFile(next);
    setError(null);
    if (!title) {
      setTitle(next.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim());
    }
  }, [title]);

  const submitFile = async () => {
    if (!file) {
      setError("Выберите видеофайл");
      return;
    }
    setBusy(true);
    setError(null);
    setProgress(0);
    try {
      const result = await uploadLecture(
        { file, title: title.trim() || undefined, description: description.trim() || undefined, asrProfile: profile },
        setProgress,
      );
      toast.success("Видео загружено, начинаем обработку");
      onClose();
      navigate(`/lectures/${result.id}`);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Не удалось загрузить файл";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  };

  const submitUrl = async () => {
    if (!/^https?:\/\//.test(url.trim())) {
      setError("Вставьте ссылку, начинающуюся с http:// или https://");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.importUrl(url.trim(), title.trim() || undefined, profile);
      toast.success("Ссылка принята, видео скачивается");
      onClose();
      navigate(`/lectures/${result.id}`);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Не удалось импортировать видео";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return (
    <div className="modal-overlay" onMouseDown={(event) => event.target === event.currentTarget && !busy && onClose()}>
      <div className="modal modal--wide" role="dialog" aria-modal="true" aria-label="Загрузка лекции">
        <div className="modal__head">
          <div>
            <h2 className="modal__title">Новая лекция</h2>
            <p className="small muted" style={{ marginTop: 4 }}>
              Видео останется на этом компьютере — обработка полностью локальная.
            </p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Закрыть" disabled={busy}>
            <CloseIcon />
          </button>
        </div>

        <div className="modal__body">
          <div className="tabs" style={{ maxWidth: 280 }}>
            <button className={`tab ${mode === "file" ? "is-active" : ""}`} onClick={() => setMode("file")}>
              Файл
            </button>
            <button className={`tab ${mode === "url" ? "is-active" : ""}`} onClick={() => setMode("url")}>
              По ссылке
            </button>
          </div>

          {mode === "file" ? (
            <>
              {file ? (
                <div className="upload-file">
                  <div className="dropzone__icon" style={{ margin: 0, width: 40, height: 40 }}>
                    <UploadIcon size={18} />
                  </div>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="upload-file__name">{file.name}</div>
                    <div className="upload-file__meta">{formatBytes(file.size)}</div>
                  </div>
                  <button className="btn btn--ghost btn--sm" onClick={() => inputRef.current?.click()} disabled={busy}>
                    Заменить
                  </button>
                </div>
              ) : (
                <div
                  className={`dropzone ${dragging ? "is-over" : ""}`}
                  onClick={() => inputRef.current?.click()}
                  onDragOver={(event) => {
                    event.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(event) => {
                    event.preventDefault();
                    setDragging(false);
                    pickFile(event.dataTransfer.files?.[0] ?? null);
                  }}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(event) => event.key === "Enter" && inputRef.current?.click()}
                >
                  <div className="dropzone__icon">
                    <UploadIcon size={20} />
                  </div>
                  <div className="dropzone__title">Перетащите видео сюда</div>
                  <div className="dropzone__hint">MP4, WebM, MOV, MKV — до 4 ГБ</div>
                </div>
              )}
              <input
                ref={inputRef}
                type="file"
                accept={ACCEPT}
                hidden
                onChange={(event) => pickFile(event.target.files?.[0] ?? null)}
              />
            </>
          ) : (
            <div className="field">
              <label className="field__label" htmlFor="import-url">
                Ссылка на видео
              </label>
              <div style={{ position: "relative" }}>
                <span style={{ position: "absolute", left: 12, top: 11, color: "var(--faint)" }}>
                  <LinkIcon size={17} />
                </span>
                <input
                  id="import-url"
                  className="input"
                  style={{ paddingLeft: 36 }}
                  placeholder="https://www.youtube.com/watch?v=…"
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  disabled={busy}
                />
              </div>
              <p className="small muted">
                Нужен yt-dlp в <span className="mono">tools/yt-dlp</span> и доступ в интернет на момент скачивания.
              </p>
            </div>
          )}

          <div className="field">
            <label className="field__label" htmlFor="lecture-title">
              Название
            </label>
            <input
              id="lecture-title"
              className="input"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Например: Теорема Пифагора — разбор"
              disabled={busy}
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="lecture-desc">
              Описание <span style={{ textTransform: "none", fontWeight: 400 }}>(необязательно)</span>
            </label>
            <textarea
              id="lecture-desc"
              className="textarea"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Курс, тема, преподаватель…"
              disabled={busy}
            />
          </div>

          <div className="field">
            <span className="field__label">Качество распознавания</span>
            <div className="row" style={{ gap: 8 }}>
              <button
                className={`chip chip--button ${profile === "accurate" ? "is-active" : ""}`}
                onClick={() => setProfile("accurate")}
                disabled={busy}
                style={profile === "accurate" ? { borderColor: "var(--accent)", color: "var(--text)" } : undefined}
              >
                <DownloadIcon size={13} /> Точное · ru-0.42
              </button>
              <button
                className={`chip chip--button ${profile === "fast" ? "is-active" : ""}`}
                onClick={() => setProfile("fast")}
                disabled={busy}
                style={profile === "fast" ? { borderColor: "var(--accent)", color: "var(--text)" } : undefined}
              >
                <DownloadIcon size={13} /> Быстрое · small
              </button>
            </div>
            <p className="small muted" style={{ marginTop: 6 }}>
              Точное качество медленнее примерно в 3 раза. Для демонстрации на защите — быстрое.
            </p>
          </div>

          {busy && mode === "file" && (
            <div>
              <div className="progress">
                <div className="progress__bar" style={{ width: `${progress}%` }} />
              </div>
              <div className="progress__label">
                <span>Загрузка файла</span>
                <strong>{progress}%</strong>
              </div>
            </div>
          )}

          {error && <div className="error-box">{error}</div>}
        </div>

        <div className="modal__foot">
          <button className="btn btn--ghost" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button
            className="btn btn--primary"
            onClick={mode === "file" ? submitFile : submitUrl}
            disabled={busy || (mode === "file" ? !file : url.trim().length < 8)}
          >
            {busy ? <span className="spinner" /> : mode === "file" ? <UploadIcon size={16} /> : <LinkIcon size={16} />}
            {busy ? "Отправляем…" : mode === "file" ? "Загрузить и обработать" : "Импортировать"}
          </button>
        </div>
      </div>
    </div>
  );
}
