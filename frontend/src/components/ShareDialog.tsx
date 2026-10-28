import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { CheckIcon, CloseIcon, LinkIcon } from "./icons";

type Visibility = "private" | "public";

export type ShareTarget =
  | { kind: "url"; url: string; title: string; accessLabel: string; hint: string }
  | { kind: "lecture"; id: string; title: string; visibility: Visibility }
  | { kind: "group"; id: string; title: string; visibility: Visibility };

interface Props {
  target: ShareTarget | null;
  onClose: () => void;
}

const KIND_LABEL: Record<"lecture" | "group", string> = {
  lecture: "видео",
  group: "курс",
};

export function ShareDialog({ target, onClose }: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!target) return;
    setCopied(false);
    setError(null);
    setUrl(null);

    if (target.kind === "url") {
      setUrl(target.url);
      setLoading(false);
      return;
    }

    const origin = window.location.origin;
    if (target.visibility === "public") {
      setUrl(
        `${origin}${
          target.kind === "lecture"
            ? `/public/lectures/${target.id}`
            : `/public/groups/${target.id}`
        }`,
      );
      setLoading(false);
      return;
    }

    let alive = true;
    setLoading(true);
    const request =
      target.kind === "lecture" ? api.shareLecture(target.id) : api.shareGroup(target.id);
    request
      .then((result) => {
        if (alive) setUrl(`${origin}${result.path}`);
      })
      .catch((err) => {
        if (alive) {
          setError(err instanceof ApiError ? err.message : "Не удалось создать ссылку");
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [target]);

  useEffect(() => {
    if (!target) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [target, onClose]);

  if (!target) return null;

  const accessLabel =
    target.kind === "url"
      ? target.accessLabel
      : `${target.visibility === "public" ? "Публичная" : "Приватная"} ссылка на ${KIND_LABEL[target.kind]}`;
  const hint =
    target.kind === "url"
      ? target.hint
      : target.visibility === "public"
        ? "Ссылка публичная: откроется у всех, кто вошёл в Lectora."
        : "Ссылка приватная: откроется у любого, кому вы её отправите, без входа в аккаунт.";

  const copy = async () => {
    if (!url) return;
    setError(null);
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
      return;
    } catch {
      // Embedded browsers may deny the async clipboard API — fall back to a selection copy.
    }
    const input = inputRef.current;
    if (input) {
      input.focus();
      input.select();
    }
    try {
      if (!input || !document.execCommand("copy")) throw new Error("copy failed");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Не удалось скопировать — выделите ссылку и скопируйте вручную");
    }
  };

  return (
    <div className="modal-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 500 }} role="dialog" aria-modal="true" aria-label="Поделиться">
        <div className="modal__head">
          <h2 className="modal__title">Поделиться</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Закрыть">
            <CloseIcon />
          </button>
        </div>
        <div className="modal__body">
          <p className="share-dialog__lead">{target.title}</p>
          <span className="field__label">{accessLabel}</span>

          {loading ? (
            <div className="share-dialog__loading">
              <span className="spinner" /> Готовим ссылку…
            </div>
          ) : url ? (
            <>
              <div className="share-dialog__row">
                <input
                  ref={inputRef}
                  className="input share-dialog__url"
                  value={url}
                  readOnly
                  aria-label="Ссылка"
                  onFocus={(event) => event.currentTarget.select()}
                />
                <button className="btn btn--primary" onClick={copy}>
                  {copied ? <CheckIcon size={15} /> : <LinkIcon size={15} />}
                  {copied ? "Скопировано" : "Скопировать"}
                </button>
              </div>
              {error ? (
                <p className="small settings-error share-dialog__hint">{error}</p>
              ) : (
                <p className="small muted share-dialog__hint">{hint}</p>
              )}
            </>
          ) : (
            error && <p className="small settings-error">{error}</p>
          )}
        </div>
        <div className="modal__foot">
          <button className="btn btn--ghost" onClick={onClose}>
            Закрыть
          </button>
          {url && (
            <a className="btn btn--primary" href={url} target="_blank" rel="noreferrer">
              Открыть ссылку
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
