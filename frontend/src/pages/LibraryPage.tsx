import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import type { LectureCard as LectureCardType, Stats } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { LectureCard } from "../components/LectureCard";
import { BookIcon, ClockIcon, LayersIcon, SearchIcon, SparkIcon, UploadIcon } from "../components/icons";
import { useToast } from "../context/ToastContext";
import { useUi } from "../context/UiContext";
import { formatDurationLong, pluralize } from "../utils/format";

type Filter = "all" | "ready" | "processing" | "failed";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Все" },
  { key: "ready", label: "Готовые" },
  { key: "processing", label: "В обработке" },
  { key: "failed", label: "С ошибкой" },
];

export function LibraryPage() {
  const ui = useUi();
  const toast = useToast();
  const [lectures, setLectures] = useState<LectureCardType[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<LectureCardType | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(
    async (silent = false) => {
      try {
        if (!silent) setLoading(true);
        const [list, statsResponse] = await Promise.all([
          api.lectures({ status: filter === "all" ? undefined : filter, limit: 120 }),
          api.stats(),
        ]);
        setLectures(list.items);
        setStats(statsResponse);
        setError(null);
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "Не удалось загрузить библиотеку";
        setError(message);
        if (!silent) toast.error(message);
      } finally {
        setLoading(false);
      }
    },
    [filter, toast],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const hasProcessing = useMemo(
    () => lectures.some((lecture) => lecture.status === "processing" || lecture.status === "queued"),
    [lectures],
  );

  useEffect(() => {
    if (!hasProcessing) return;
    const timer = window.setInterval(() => void load(true), 3500);
    return () => window.clearInterval(timer);
  }, [hasProcessing, load]);

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await api.deleteLecture(pendingDelete.id);
      toast.success(`«${pendingDelete.title}» удалена`);
      setPendingDelete(null);
      await load(true);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Не удалось удалить лекцию");
    } finally {
      setDeleting(false);
    }
  };

  const totalSeconds = stats?.content.duration_sec ?? 0;
  const totalHours = totalSeconds / 3600;
  const durationValue =
    totalSeconds === 0 ? "—" : totalHours >= 1 ? totalHours.toFixed(1) : String(Math.round(totalSeconds / 60));
  const durationLabel = totalHours >= 1 ? "часов записи" : "минут записи";

  return (
    <>
      <section className="hero">
        <h1 className="hero__title">
          Найдите нужный момент в лекции <em>по смыслу</em>, а не по словам
        </h1>
        <p className="hero__text">
          Загрузите запись — Lectora распознает речь, разложит её на смысловые фрагменты,
          построит конспект с таймкодами и позволит задавать вопросы прямо по содержанию.
        </p>

        <div className="hero__stats">
          <div className="stat">
            <span className="stat__value">{stats?.lectures.total ?? "—"}</span>
            <span className="stat__label">
              {pluralize(stats?.lectures.total ?? 0, ["лекция", "лекции", "лекций"])}
            </span>
          </div>
          <div className="stat">
            <span className="stat__value">{durationValue}</span>
            <span className="stat__label">{durationLabel}</span>
          </div>
          <div className="stat">
            <span className="stat__value">{stats?.content.chunks ?? "—"}</span>
            <span className="stat__label">смысловых фрагментов</span>
          </div>
          <div className="stat">
            <span className="stat__value">{stats?.search.total ?? "—"}</span>
            <span className="stat__label">поисковых запросов</span>
          </div>
        </div>

        <div className="row" style={{ marginTop: 26, flexWrap: "wrap", gap: 10 }}>
          <button className="btn btn--primary" onClick={() => ui.openUpload("file")}>
            <UploadIcon size={16} />
            Загрузить лекцию
          </button>
          <button className="btn" onClick={() => ui.openPalette()}>
            <SearchIcon size={16} />
            Поиск по курсу
            <kbd className="kbd">Ctrl K</kbd>
          </button>
          {stats && stats.content.duration_sec > 0 && (
            <span className="demo-banner" style={{ marginLeft: "auto" }}>
              <LayersIcon size={13} />
              {formatDurationLong(stats.content.duration_sec)} в индексе
            </span>
          )}
        </div>
      </section>

      {stats && stats.lectures.processing > 0 && (
        <div className="card card--pad" style={{ marginBottom: 22 }}>
          <div className="processing-card">
            <div className="processing-card__top">
              <span className="processing-card__stage">
                <span className="spinner" style={{ display: "inline-block", marginRight: 8, verticalAlign: -3 }} />
                Обрабатываем {stats.lectures.processing}{" "}
                {pluralize(stats.lectures.processing, ["лекцию", "лекции", "лекций"])}
              </span>
              <span className="processing-card__pct">это может занять несколько минут</span>
            </div>
            <p className="small muted">
              Распознаём речь и строим индекс. Можно уйти со страницы — прогресс сохранится.
            </p>
          </div>
        </div>
      )}

      <div className="library-toolbar">
        <h2 className="library-toolbar__title">Библиотека</h2>
        <span className="library-toolbar__count">{lectures.length}</span>
        <div className="filters">
          {FILTERS.map((item) => (
            <button
              key={item.key}
              className={`filter ${filter === item.key ? "is-active" : ""}`}
              onClick={() => setFilter(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="error-box" style={{ marginBottom: 16 }}>{error}</div>}

      {loading ? (
        <div className="grid">
          {[0, 1, 2].map((index) => (
            <div key={index} className="skeleton" style={{ height: 280 }} />
          ))}
        </div>
      ) : lectures.length === 0 ? (
        <div className="empty">
          <div className="empty__icon">
            {filter === "all" ? <BookIcon size={22} /> : <SearchIcon size={22} />}
          </div>
          <div className="empty__title">
            {filter === "all" ? "Пока ни одной лекции" : "В этом статусе пусто"}
          </div>
          <p style={{ maxWidth: 430, margin: "0 auto 18px" }}>
            {filter === "all"
              ? "Загрузите первую запись — MP4 или WebM. Всё остальное Lectora сделает сама: транскрипт, поиск, конспект."
              : "Переключите фильтр или загрузите новую лекцию."}
          </p>
          <button className="btn btn--primary" onClick={() => ui.openUpload("file")}>
            <UploadIcon size={16} />
            Загрузить лекцию
          </button>
        </div>
      ) : (
        <div className="grid">
          {lectures.map((lecture) => (
            <LectureCard key={lecture.id} lecture={lecture} onDelete={(item) => setPendingDelete(item)} />
          ))}
        </div>
      )}

      <div className="grid" style={{ marginTop: 34, gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
        <div className="card card--pad">
          <div className="row" style={{ color: "var(--accent)" }}>
            <SparkIcon size={18} />
            <strong style={{ fontSize: 14 }}>Смысловой поиск</strong>
          </div>
          <p className="small muted" style={{ marginTop: 8 }}>
            Находит фрагменты по смыслу, даже если вы не помните точную формулировку.
          </p>
        </div>
        <div className="card card--pad">
          <div className="row" style={{ color: "var(--accent-2)" }}>
            <ClockIcon size={18} />
            <strong style={{ fontSize: 14 }}>Таймкоды до секунды</strong>
          </div>
          <p className="small muted" style={{ marginTop: 8 }}>
            Каждый фрагмент привязан к видео — один клик, и плеер перематывается в нужный момент.
          </p>
        </div>
        <div className="card card--pad">
          <div className="row" style={{ color: "var(--amber)" }}>
            <BookIcon size={18} />
            <strong style={{ fontSize: 14 }}>Конспект и структура</strong>
          </div>
          <p className="small muted" style={{ marginTop: 8 }}>
            Автоматический обзор, разделы с таймкодами и ключевые термины — как конспект после лекции.
          </p>
        </div>
      </div>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Удалить лекцию?"
        description={
          pendingDelete
            ? `«${pendingDelete.title}» будет удалена вместе с видео, транскриптом и индексом. Действие необратимо.`
            : undefined
        }
        confirmLabel="Удалить"
        danger
        busy={deleting}
        onClose={() => setPendingDelete(null)}
        onConfirm={confirmDelete}
      />
    </>
  );
}
