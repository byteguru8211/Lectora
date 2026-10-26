import { useEffect } from "react";
import { CloseIcon } from "./icons";

interface Props {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Подтвердить",
  danger = false,
  busy = false,
  onConfirm,
  onClose,
}: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  return (
    <div className="modal-overlay" onMouseDown={(event) => event.target === event.currentTarget && !busy && onClose()}>
      <div className="modal" style={{ maxWidth: 440 }} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal__head">
          <h2 className="modal__title">{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Закрыть" disabled={busy}>
            <CloseIcon />
          </button>
        </div>
        <div className="modal__body">
          {description && <p className="muted" style={{ fontSize: 14 }}>{description}</p>}
        </div>
        <div className="modal__foot">
          <button className="btn btn--ghost" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button
            className="btn"
            style={danger ? { background: "var(--danger)", borderColor: "transparent", color: "#fff" } : undefined}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy && <span className="spinner" />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
