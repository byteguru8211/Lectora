import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { SearchSuggestion } from "../api/types";
import { useDebounced } from "../hooks/useTheme";
import { BookIcon, ListIcon, SearchIcon, ClockIcon, ArrowRightIcon } from "./icons";

interface Props {
  open: boolean;
  onClose: () => void;
}

type Row = {
  key: string;
  label: string;
  hint?: string;
  type: "search" | "lecture" | "section" | "history";
  action: () => void;
};

export function CommandPalette({ open, onClose }: Props) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([]);
  const [active, setActive] = useState(0);
  const debounced = useDebounced(query, 220);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSuggestions([]);
      setActive(0);
      window.setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  useEffect(() => {
    if (!open || debounced.trim().length < 2) {
      setSuggestions([]);
      return;
    }
    let cancelled = false;
    api
      .suggest(debounced.trim())
      .then((response) => {
        if (!cancelled) setSuggestions(response.items);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [open, debounced]);

  const rows = useMemo<Row[]>(() => {
    const trimmed = query.trim();
    const list: Row[] = [];
    if (trimmed.length >= 2) {
      list.push({
        key: "search",
        label: `Искать «${trimmed}» во всех лекциях`,
        hint: "Enter",
        type: "search",
        action: () => navigate(`/search?q=${encodeURIComponent(trimmed)}`),
      });
    }
    for (const item of suggestions) {
      if (item.type === "section" && item.lecture_id) {
        list.push({
          key: `section-${item.lecture_id}-${item.start_sec}`,
          label: item.text,
          hint: item.lecture_title,
          type: "section",
          action: () =>
            navigate(`/lectures/${item.lecture_id}?t=${Math.floor(item.start_sec ?? 0)}`),
        });
      } else if (item.type === "lecture") {
        list.push({
          key: `lecture-${item.text}`,
          label: item.text,
          hint: "Лекция",
          type: "lecture",
          action: () => navigate(`/search?q=${encodeURIComponent(item.text)}`),
        });
      } else {
        list.push({
          key: `history-${item.text}`,
          label: item.text,
          hint: "Недавний запрос",
          type: "history",
          action: () => navigate(`/search?q=${encodeURIComponent(item.text)}`),
        });
      }
    }
    return list;
  }, [query, suggestions, navigate]);

  useEffect(() => {
    setActive(0);
  }, [rows.length]);

  if (!open) return null;

  const run = (row: Row | undefined) => {
    if (!row) return;
    row.action();
    onClose();
  };

  return (
    <div className="modal-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Поиск по курсу">
        <input
          ref={inputRef}
          className="palette__input"
          placeholder="Что хотите найти? Например: «объяснение теоремы Пифагора»"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") onClose();
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActive((current) => Math.min(current + 1, Math.max(rows.length - 1, 0)));
            }
            if (event.key === "ArrowUp") {
              event.preventDefault();
              setActive((current) => Math.max(current - 1, 0));
            }
            if (event.key === "Enter") {
              event.preventDefault();
              run(rows[active]);
            }
          }}
        />
        <div className="palette__list">
          {rows.length === 0 && (
            <div className="palette__empty">
              {query.trim().length < 2
                ? "Введите запрос — ищем по смыслу, а не по ключевым словам."
                : "Ничего не нашлось. Попробуйте сформулировать иначе."}
            </div>
          )}
          {rows.map((row, index) => (
            <button
              key={row.key}
              className={`palette__item ${index === active ? "is-active" : ""}`}
              onMouseEnter={() => setActive(index)}
              onClick={() => run(row)}
            >
              <span className="palette__icon">
                {row.type === "search" ? (
                  <SearchIcon size={15} />
                ) : row.type === "section" ? (
                  <ListIcon size={15} />
                ) : row.type === "history" ? (
                  <ClockIcon size={15} />
                ) : (
                  <BookIcon size={15} />
                )}
              </span>
              <span className="palette__text">{row.label}</span>
              {row.hint && <span className="palette__type">{row.hint}</span>}
              <ArrowRightIcon size={14} />
            </button>
          ))}
        </div>
        <div className="palette__foot">
          <span>↑↓ навигация</span>
          <span>Enter открыть</span>
          <span>Esc закрыть</span>
        </div>
      </div>
    </div>
  );
}
