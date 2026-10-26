import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { CheckIcon, AlertIcon, CloseIcon } from "../components/icons";

export type ToastKind = "success" | "error" | "info";

interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  push: (kind: ToastKind, message: string) => void;
  success: (message: string) => void;
  error: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let counter = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const remove = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = ++counter;
      setToasts((current) => [...current.slice(-2), { id, kind, message }]);
      window.setTimeout(() => remove(id), kind === "error" ? 6500 : 3800);
    },
    [remove],
  );

  const value = useMemo<ToastContextValue>(
    () => ({
      push,
      success: (message: string) => push("success", message),
      error: (message: string) => push("error", message),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-host" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast--${toast.kind}`}>
            <span style={{ color: toast.kind === "error" ? "var(--danger)" : "var(--success)" }}>
              {toast.kind === "error" ? <AlertIcon size={17} /> : <CheckIcon size={17} />}
            </span>
            <div className="toast__body">{toast.message}</div>
            <button className="icon-btn" style={{ width: 24, height: 24 }} onClick={() => remove(toast.id)} aria-label="Закрыть">
              <CloseIcon size={13} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
