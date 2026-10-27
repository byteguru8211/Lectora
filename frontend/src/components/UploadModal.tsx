import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, uploadLecture } from "../api/client";
import { useToast } from "../context/ToastContext";
import { formatBytes } from "../utils/format";
import { LLM_MODES, LLM_MODE_META, readStoredLlmMode, storeLlmMode } from "../utils/llm";
import { CloseIcon, DownloadIcon, LinkIcon, SparkIcon, UploadIcon, BookIcon } from "./icons";
import type { LlmMode, LlmModeInfo, VideoGroup } from "../api/types";

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
  const [asrEngine, setAsrEngine] = useState<"vosk" | "whisper">("whisper");
  const [llmMode, setLlmMode] = useState<LlmMode>(() => readStoredLlmMode("api"));
  const [llmModes, setLlmModes] = useState<Record<LlmMode, LlmModeInfo> | null>(null);
  const [useGpu, setUseGpu] = useState(() => localStorage.getItem("lectora-use-gpu") !== "false");
  const [gpuStatus, setGpuStatus] = useState("Проверяем доступное ускорение…");
  const [visibility, setVisibility] = useState<"private" | "public">("private");
  const [groups, setGroups] = useState<VideoGroup[]>([]);
  const [groupId, setGroupId] = useState("");
  const [newGroupName, setNewGroupName] = useState("");
  const [newGroupVisibility, setNewGroupVisibility] = useState<"private" | "public">("private");
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
    setVisibility("private");
    setGroupId("");
    setNewGroupName("");
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, initialMode, busy, onClose]);

  useEffect(() => {
    if (open) api.groups().then((response) => setGroups(response.items)).catch(() => setGroups([]));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    api.systemInfo().then(({ acceleration, llm }) => {
      if (acceleration.cuda && acceleration.nvenc) setGpuStatus(`${acceleration.cuda_device ?? "NVIDIA GPU"}: CUDA и NVENC доступны`);
      else if (acceleration.nvenc) setGpuStatus("NVENC доступен, CUDA выключена. Запустите scripts\\install_gpu.ps1");
      else if (acceleration.cuda) setGpuStatus(`${acceleration.cuda_device ?? "CUDA"}: CUDA доступна; для NVENC обновите драйвер NVIDIA — сейчас видео кодируется на CPU`);
      else setGpuStatus("GPU-ускорение не найдено — будет использован CPU");
      if (llm?.modes) {
        setLlmModes(llm.modes);
        setLlmMode(readStoredLlmMode(llm.default_mode));
      }
    }).catch(() => setGpuStatus("Не удалось проверить GPU — доступен автоматический откат на CPU"));
  }, [open]);

  const pickFile = useCallback((next: File | null) => {
    if (!next) return;
    setFile(next);
    setError(null);
  }, []);

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
        { file, title: title.trim() || undefined, description: description.trim() || undefined, asrProfile: profile, asrEngine, useGpu, visibility, groupId: groupId || undefined, llmMode },
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
      const result = await api.importUrl(url.trim(), title.trim() || undefined, profile, useGpu, asrEngine, visibility, groupId || undefined, llmMode);
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

  const modeStatus = (value: LlmMode): string => {
    const info = llmModes?.[value];
    if (!info) return LLM_MODE_META[value].description;
    if (!info.enabled) return "Отключено в настройках";
    if (!info.available) return info.detail ? `Недоступно: ${info.detail}` : "Недоступно — сработает резервный режим";
    if (value === "api") return `Готово · ${info.model} · ${info.extra?.ready_accounts ?? 1} аккаунт`;
    return `Готово · ${info.model}`;
  };

  return (
    <div className="modal-overlay" onMouseDown={(event) => event.target === event.currentTarget && !busy && onClose()}>
      <div className="modal modal--wide" role="dialog" aria-modal="true" aria-label="Загрузка лекции">
        <div className="modal__head">
          <div>
            <h2 className="modal__title">Новая лекция</h2>
            <p className="small muted" style={{ marginTop: 4 }}>
              Загрузите запись — расшифровка, конспект и поиск появятся автоматически.
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
                Поддерживаются ссылки YouTube и Vimeo. Видео скачается и появится в библиотеке.
              </p>
            </div>
          )}

          <div className="field">
            <label className="field__label" htmlFor="lecture-title">
              Название{" "}
              <span style={{ textTransform: "none", fontWeight: 400 }}>
                (оставьте пустым — придумаем по содержанию)
              </span>
            </label>
            <input
              id="lecture-title"
              className="input"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Название придумается автоматически"
              disabled={busy}
            />
          </div>

          <div className="upload-access-grid">
            <div className="field">
              <span className="field__label">Доступ к видео</span>
              <select className="select" value={visibility} onChange={(event) => setVisibility(event.target.value as "private" | "public")} disabled={busy}>
                <option value="private">Приватное</option><option value="public">Публичное</option>
              </select>
              <p className="small muted">Публичное видео появится в общей библиотеке.</p>
            </div>
            <div className="field">
              <span className="field__label">Моя группа</span>
              <select className="select" value={groupId} onChange={(event) => setGroupId(event.target.value)} disabled={busy}>
                <option value="">Без группы</option>{groups.map((group) => <option value={group.id} key={group.id}>{group.name} · {group.visibility === "public" ? "публичная" : "приватная"}</option>)}
              </select>
              <p className="small muted">Видео можно объединять в собственные коллекции.</p>
            </div>
          </div>

          <div className="new-group-row">
            <input className="input" value={newGroupName} onChange={(event) => setNewGroupName(event.target.value)} placeholder="Новая группа…" disabled={busy} />
            <select className="select" value={newGroupVisibility} onChange={(event) => setNewGroupVisibility(event.target.value as "private" | "public")} disabled={busy}><option value="private">Приватная</option><option value="public">Публичная</option></select>
            <button className="btn btn--sm" disabled={busy || newGroupName.trim().length < 2} onClick={async () => { try { const group = await api.createGroup(newGroupName.trim(), newGroupVisibility); setGroups((items) => [group, ...items]); setGroupId(group.id); setNewGroupName(""); toast.success("Группа создана"); } catch (err) { toast.error(err instanceof ApiError ? err.message : "Не удалось создать группу"); } }}>Создать</button>
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
            <span className="field__label">Движок распознавания</span>
            <div className="asr-options">
              <button className={`asr-option ${asrEngine === "whisper" ? "is-active" : ""}`} onClick={() => { setAsrEngine("whisper"); setUseGpu(true); }} disabled={busy}>
                <SparkIcon size={17} /><span><strong>Whisper GPU</strong><small>Быстрее и точнее, рекомендуется</small></span>
              </button>
              <button className={`asr-option ${asrEngine === "vosk" ? "is-active" : ""}`} onClick={() => setAsrEngine("vosk")} disabled={busy}>
                <DownloadIcon size={17} /><span><strong>Vosk CPU</strong><small>Экономный резервный режим</small></span>
              </button>
            </div>
            {asrEngine === "whisper" && <p className="small muted">При первом запуске модель small загрузится автоматически. При ошибке Lectora продолжит обработку через Vosk.</p>}
          </div>

          {asrEngine === "vosk" && <div className="field">
            <span className="field__label">Качество Vosk</span>
            <div className="row" style={{ gap: 8 }}>
              <button
                className={`chip chip--button ${profile === "accurate" ? "is-active" : ""}`}
                onClick={() => setProfile("accurate")}
                disabled={busy}
                style={profile === "accurate" ? { borderColor: "var(--accent)", color: "var(--text)" } : undefined}
              >
                <DownloadIcon size={13} /> Точное
              </button>
              <button
                className={`chip chip--button ${profile === "fast" ? "is-active" : ""}`}
                onClick={() => setProfile("fast")}
                disabled={busy}
                style={profile === "fast" ? { borderColor: "var(--accent)", color: "var(--text)" } : undefined}
              >
                <DownloadIcon size={13} /> Быстрое
              </button>
            </div>
            <p className="small muted" style={{ marginTop: 6 }}>
              Точный режим медленнее примерно в 3 раза. Для демонстрации подойдёт быстрый.
            </p>
          </div>}

          <div className="field">
            <span className="field__label">Конспект и структура</span>
            <div className="llm-mode-options">
              {LLM_MODES.map((value) => {
                const info = llmModes?.[value];
                const Icon = value === "api" ? SparkIcon : value === "local" ? DownloadIcon : BookIcon;
                return (
                  <button
                    key={value}
                    className={`asr-option ${llmMode === value ? "is-active" : ""}`}
                    onClick={() => {
                      setLlmMode(value);
                      storeLlmMode(value);
                    }}
                    disabled={busy || (info ? !info.selectable : false)}
                    title={modeStatus(value)}
                  >
                    <Icon size={17} />
                    <span>
                      <strong>{LLM_MODE_META[value].label}</strong>
                      <small>{modeStatus(value)}</small>
                    </span>
                  </button>
                );
              })}
            </div>
            <p className="small muted">
              {llmMode === "api"
                ? "DeepSeek API даёт самый подробный конспект: больше разделов, тезисов и пояснений. Обычно 2–4 минуты."
                : "Локальная модель работает без интернета, конспект компактнее."}
            </p>
          </div>

          <label className={`gpu-option ${useGpu ? "is-active" : ""}`}>
            <span className="gpu-option__icon"><SparkIcon size={18} /></span>
            <span className="gpu-option__text">
              <strong>Использовать видеокарту</strong>
              <small>{gpuStatus}</small>
            </span>
            <input
              type="checkbox"
              checked={useGpu}
              disabled={busy}
              onChange={(event) => {
                setUseGpu(event.target.checked);
                localStorage.setItem("lectora-use-gpu", String(event.target.checked));
              }}
            />
            <span className="gpu-switch" aria-hidden="true" />
          </label>
          <p className="small muted" style={{ marginTop: -10 }}>
            Распознавание Vosk продолжит работать на процессоре. При недоступной CUDA включится CPU автоматически.
          </p>

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
