import { useEffect, useState } from "react";
import { CloseIcon } from "./icons";

interface Props {
  open: boolean;
  initialTitle: string;
  busy?: boolean;
  onSave: (title: string) => void;
  onClose: () => void;
}

export function RenameDialog({ open, initialTitle, busy = false, onSave, onClose }: Props) {
  const [value, setValue] = useState(initialTitle);

  useEffect(() => {
    if (open) setValue(initialTitle);
  }, [open, initialTitle]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  const submit = () => {
    const title = value.trim();
    if (title.length < 2) return;
    onSave(title);
  };

  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => event.target === event.currentTarget && !busy && onClose()}
    >
      <div className="modal" style={{ maxWidth: 480 }} role="dialog" aria-modal="true" aria-label="Название лекции">
        <div className="modal__head">
          <h2 className="modal__title">Название лекции</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Закрыть" disabled={busy}>
            <CloseIcon />
          </button>
        </div>
        <div className="modal__body">
          <div className="field">
            <label className="field__label" htmlFor="rename-title">
              Как назвать лекцию
            </label>
            <input
              id="rename-title"
              className="input"
              autoFocus
              value={value}
              onChange={(event) => setValue(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && submit()}
              placeholder="Например: Теорема Пифагора — разбор"
              disabled={busy}
            />
            <p className="small muted">
              Автоматическое название больше не будет перезаписывать ваше.
            </p>
          </div>
        </div>
        <div className="modal__foot">
          <button className="btn btn--ghost" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button className="btn btn--primary" onClick={submit} disabled={busy || value.trim().length < 2}>
            {busy && <span className="spinner" />}
            Сохранить
          </button>
        </div>
      </div>
    </div>
  );
}
