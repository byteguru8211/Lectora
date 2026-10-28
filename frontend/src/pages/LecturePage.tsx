import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError, subscribeProgress } from "../api/client";
import type { LectureDetail, LectureStatus, LlmMode, SearchHit, Segment } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { NotesModeDialog } from "../components/NotesModeDialog";
import { NotesPane } from "../components/NotesPane";
import { QaPane } from "../components/QaPane";
import { RenameDialog } from "../components/RenameDialog";
import { SearchPane } from "../components/SearchPane";
import { ShareDialog, type ShareTarget } from "../components/ShareDialog";
import { SemanticTimeline } from "../components/SemanticTimeline";
import { TranscriptPane } from "../components/TranscriptPane";
import { VideoPlayer } from "../components/VideoPlayer";
import {
  ArrowLeftIcon,
  BookIcon,
  ChatIcon,
  ClockIcon,
  DownloadIcon,
  LayersIcon,
  LinkIcon,
  PencilIcon,
  RefreshIcon,
  SearchIcon,
  SparkIcon,
  TrashIcon,
} from "../components/icons";
import { useToast } from "../context/ToastContext";
import { formatClock, formatDate, pluralize } from "../utils/format";
import { llmModeLabel } from "../utils/llm";
import { StatusBadge } from "../components/StatusBadge";

type Tab = "notes" | "search" | "qa";

const TABS: { key: Tab; label: string; icon: typeof BookIcon }[] = [
  { key: "notes", label: "Конспект", icon: BookIcon },
  { key: "search", label: "Поиск", icon: SearchIcon },
  { key: "qa", label: "Вопросы", icon: ChatIcon },
];

interface LecturePageProps {
  accessBase?: string;
  backTo?: string;
  backLabel?: string;
}

export function LecturePage({ accessBase, backTo = "/", backLabel = "Библиотека" }: LecturePageProps = {}) {
  const { lectureId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [searchParams, setSearchParams] = useSearchParams();

  const [lecture, setLecture] = useState<LectureDetail | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTabState] = useState<Tab>(() => {
    const requested = searchParams.get("tab");
    return requested === "search" || requested === "qa" || requested === "notes" ? requested : "notes";
  });
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [seekRequest, setSeekRequest] = useState<{ sec: number; nonce: number } | null>(null);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [transcriptQuery, setTranscriptQuery] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmReprocess, setConfirmReprocess] = useState(false);
  const [notesDialogOpen, setNotesDialogOpen] = useState(false);
  const [notesBusy, setNotesBusy] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameBusy, setRenameBusy] = useState(false);
  const [working, setWorking] = useState(false);
  const [shareTarget, setShareTarget] = useState<ShareTarget | null>(null);

  const initialSeek = useRef<number | null>(
    searchParams.get("t") ? Number(searchParams.get("t")) : null,
  );

  const setTab = useCallback(
    (next: Tab) => {
      setTabState(next);
      const params = new URLSearchParams(searchParams);
      params.set("tab", next);
      setSearchParams(params, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const refresh = useCallback(
    async (silent = false) => {
      try {
        if (!silent) setLoading(true);
        const detail = accessBase ? await api.accessLecture(accessBase) : await api.lecture(lectureId);
        setLecture(detail);
        if (detail.status === "ready") {
          const transcript = accessBase ? await api.accessTranscript(accessBase) : await api.transcript(lectureId);
          setSegments(transcript.segments);
          setDuration((current) => current || transcript.duration_sec);
        }
        setError(null);
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "Не удалось открыть лекцию";
        setError(message);
        if (!silent) toast.error(message);
      } finally {
        setLoading(false);
      }
    },
    [lectureId, toast, accessBase],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // live processing progress
  useEffect(() => {
    if (!lecture || accessBase) return;
    if (lecture.status === "ready" || lecture.status === "failed") return;

    const dispose = subscribeProgress(lecture.id, (payload) => {
      setLecture((current) =>
        current
          ? {
              ...current,
              status: payload.status as LectureStatus,
              stage: payload.stage,
              stage_label: payload.stage_label,
              progress: payload.progress,
              error_message: payload.error_message,
            }
          : current,
      );
      if (payload.status === "ready") {
        void refresh(true);
      }
    });
    return dispose;
  }, [lecture?.id, lecture?.status, refresh, accessBase]);

  // explicit deep link ?t=123
  useEffect(() => {
    if (lecture?.status !== "ready" || initialSeek.current == null) return;
    const target = initialSeek.current;
    initialSeek.current = null;
    const timer = window.setTimeout(() => seek(target), 700);
    return () => window.clearTimeout(timer);
  }, [lecture?.status]);

  const seek = useCallback((seconds: number) => {
    const safe = Math.max(0, Math.min(seconds, duration || seconds));
    setCurrentTime(safe);
    setSeekRequest({ sec: safe, nonce: Date.now() });
  }, [duration]);

  const copyMomentLink = async () => {
    const url = `${window.location.origin}${window.location.pathname}?t=${Math.floor(currentTime)}`;
    try {
      await navigator.clipboard.writeText(url);
      toast.success(`Ссылка на ${formatClock(currentTime)} скопирована`);
    } catch {
      toast.error("Браузер запретил доступ к буферу обмена");
    }
  };

  const openShare = () => {
    if (!lecture) return;
    if (accessBase) {
      const isPublicView = accessBase.startsWith("/api/public");
      setShareTarget({
        kind: "url",
        url: `${window.location.origin}${window.location.pathname}`,
        title: lecture.title,
        accessLabel: "Ссылка на видео",
        hint: isPublicView
          ? "Публичная ссылка: откроется у всех, кто вошёл в Lectora."
          : "Ссылка откроется у любого, кому вы её отправите.",
      });
      return;
    }
    setShareTarget({
      kind: "lecture",
      id: lecture.id,
      title: lecture.title,
      visibility: lecture.visibility,
    });
  };

  const downloadTranscript = () => {
    const body = segments
      .map((segment) => `[${segment.timestamp}] ${segment.text}`)
      .join("\n");
    const blob = new Blob([body], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${lecture?.title ?? "lecture"}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const removeLecture = async () => {
    setWorking(true);
    try {
      await api.deleteLecture(lectureId);
      toast.success("Лекция удалена");
      navigate("/");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Не удалось удалить лекцию");
    } finally {
      setWorking(false);
      setConfirmDelete(false);
    }
  };

  const renameLecture = async (title: string) => {
    setRenameBusy(true);
    try {
      const updated = await api.updateLecture(lectureId, { title });
      setLecture((current) => (current ? { ...current, title: updated.title, title_auto: updated.title_auto } : current));
      toast.success("Название обновлено");
      setRenameOpen(false);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Не удалось переименовать");
    } finally {
      setRenameBusy(false);
    }
  };

  const reprocess = async () => {    setWorking(true);
    try {
      await api.reprocess(lectureId);
      toast.success("Лекция отправлена на повторную обработку");
      setConfirmReprocess(false);
      await refresh(true);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Не удалось запустить обработку");
    } finally {
      setWorking(false);
    }
  };

  const rebuildNotes = async (mode: LlmMode) => {
    setNotesBusy(true);
    try {
      await api.regenerateNotes(lectureId, mode);
      setNotesDialogOpen(false);
      toast.success(`Конспект собирается заново · ${llmModeLabel(mode)}`);
      await refresh(true);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Не удалось запустить сборку конспекта");
    } finally {
      setNotesBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="stack" style={{ gap: 18 }}>
        <div className="skeleton" style={{ height: 30, width: 320 }} />
        <div className="skeleton" style={{ height: 460 }} />
      </div>
    );
  }

  if (error || !lecture) {
    return (
      <div className="empty" style={{ marginTop: 40 }}>
        <div className="empty__icon">
          <LayersIcon size={22} />
        </div>
        <div className="empty__title">Лекция не открылась</div>
        <p style={{ marginBottom: 18 }}>{error ?? "Возможно, она была удалена."}</p>
        <Link className="btn" to={backTo}>
          <ArrowLeftIcon size={15} /> {backLabel}
        </Link>
      </div>
    );
  }

  const processing = lecture.status === "queued" || lecture.status === "processing";
  const suggestions = [
    ...lecture.sections.slice(0, 2).map((section) => `О чём раздел «${section.title}»?`),
    ...lecture.keywords.slice(0, 2).map((keyword) => `Что такое ${keyword}?`),
  ];

  return (
    <>
      <div className="lecture-head">
        <div className="lecture-head__main">
          <Link className="back-link" to={backTo}>
            <ArrowLeftIcon size={14} /> {backLabel}
          </Link>
          <h1 className="lecture-head__title">{lecture.title}</h1>
          <div className="lecture-meta">
            <StatusBadge status={lecture.status} label={processing ? lecture.stage_label : undefined} />
            <span className="lecture-meta__dot" />
            <span>
              <ClockIcon size={12} style={{ display: "inline", verticalAlign: -1, marginRight: 4 }} />
              {lecture.duration_label}
            </span>
            {lecture.resolution && (
              <>
                <span className="lecture-meta__dot" />
                <span>{lecture.resolution}</span>
              </>
            )}
            {lecture.word_count > 0 && (
              <>
                <span className="lecture-meta__dot" />
                <span>
                  {lecture.word_count.toLocaleString("ru-RU")}{" "}
                  {pluralize(lecture.word_count, ["слово", "слова", "слов"])}
                </span>
              </>
            )}
            <span className="lecture-meta__dot" />
            <span>{formatDate(lecture.created_at)}</span>
            {lecture.llm_mode_used && (
              <>
                <span className="lecture-meta__dot" />
                <span>конспект: {llmModeLabel(lecture.llm_mode_used, "short")}</span>
              </>
            )}
          </div>
        </div>

        <div className="row" style={{ gap: 8 }}>
          <button
            className="btn btn--ghost btn--sm"
            onClick={openShare}
            title="Скопировать ссылку на видео"
          >
            <LinkIcon size={14} /> Поделиться
          </button>
          {!accessBase && (
            <>
              <button
                className="btn btn--ghost btn--sm"
                onClick={() => setNotesDialogOpen(true)}
                disabled={processing}
                title="Собрать конспект заново в другом режиме"
              >
                <SparkIcon size={14} /> Конспект
              </button>
              <button className="btn btn--ghost btn--sm" onClick={() => setRenameOpen(true)}>
                <PencilIcon size={14} /> Переименовать
              </button>
              <button className="btn btn--ghost btn--sm" onClick={() => setConfirmReprocess(true)}>
                <RefreshIcon size={14} /> Переобработать
              </button>
              <button className="icon-btn" onClick={() => setConfirmDelete(true)} aria-label="Удалить лекцию" title="Удалить">
                <TrashIcon size={16} />
              </button>
            </>
          )}
        </div>
      </div>

      {processing && (
        <div className="card card--pad" style={{ marginBottom: 20 }}>
          <div className="processing-card">
            <div className="processing-card__top">
              <span className="processing-card__stage">
                <span className="spinner" style={{ display: "inline-block", marginRight: 8, verticalAlign: -3 }} />
                {lecture.stage_label ?? "Обработка"}
              </span>
              <span className="processing-card__pct">{Math.round(lecture.progress)}%</span>
            </div>
            <div className="progress">
              <div className="progress__bar" style={{ width: `${Math.max(3, lecture.progress)}%` }} />
            </div>
            <p className="small muted">
              Распознаём речь и собираем конспект. Можно закрыть страницу — обработка продолжится.
            </p>
          </div>
        </div>
      )}

      {lecture.status === "failed" && (
        <div className="card card--pad" style={{ marginBottom: 20 }}>
          <div className="error-box" style={{ marginBottom: 12 }}>
            {lecture.error_message ?? "Обработка завершилась ошибкой."}
          </div>
          <button className="btn btn--primary btn--sm" onClick={() => setConfirmReprocess(true)}>
            <RefreshIcon size={14} /> Попробовать снова
          </button>
        </div>
      )}

      <div className="lecture-layout">
        <div className="stack" style={{ gap: 0 }}>
          {lecture.status === "ready" ? (
            <>
              <VideoPlayer
                src={lecture.media_url}
                poster={lecture.thumbnail_url}
                subtitlesUrl={lecture.subtitles_url}
                segments={segments}
                sourceLanguage={lecture.language}
                targetLanguage={lecture.target_language}
                voiceoverUrl={lecture.voiceover_url}
                voiceoverAligned={lecture.voiceover_aligned}
                sections={lecture.sections}
                currentTime={currentTime}
                seekRequest={seekRequest}
                onTime={setCurrentTime}
                onDuration={(value) => setDuration(value || lecture.duration_sec)}
                onSeek={seek}
              />
              <div style={{ border: "1px solid var(--border)", borderTop: "none", borderRadius: "0 0 18px 18px", overflow: "hidden" }}>
                <SemanticTimeline
                  duration={duration || lecture.duration_sec}
                  current={currentTime}
                  sections={lecture.sections}
                  hits={hits}
                  onSeek={seek}
                />
                <div className="player-toolbar" style={{ borderTop: "1px solid var(--border)" }}>
                  <button className="chip chip--button" onClick={copyMomentLink} title="Скопировать ссылку на текущий момент">
                    <span className="chip__time">{formatClock(currentTime)}</span>
                    ссылка на момент
                  </button>
                  <button className="chip chip--button" onClick={downloadTranscript}>
                    <DownloadIcon size={12} /> транскрипт .txt
                  </button>
                  <a className="chip chip--button" href={`${lecture.subtitles_url}?lang=${lecture.language}`} download={`lecture-${lecture.language}.vtt`}>
                    <DownloadIcon size={12} /> субтитры {lecture.language.toUpperCase()}
                  </a>
                  <a className="chip chip--button" href={`${lecture.subtitles_srt_url}?lang=${lecture.language}`} download={`lecture-${lecture.language}.srt`}>
                    <DownloadIcon size={12} /> SRT
                  </a>
                  {lecture.target_language && <a className="chip chip--button" href={`${lecture.subtitles_url}?lang=${lecture.target_language}`} download={`lecture-${lecture.target_language}.vtt`}><DownloadIcon size={12} /> субтитры {lecture.target_language.toUpperCase()}</a>}
                  <span className="player-toolbar__time">
                    <strong>{formatClock(currentTime)}</strong> / {formatClock(duration || lecture.duration_sec)}
                  </span>
                </div>
              </div>
            </>
          ) : (
            <div className="player-card">
              <div className="player-card__holder">
                {lecture.thumbnail_url ? (
                  <img
                    src={lecture.thumbnail_url}
                    alt=""
                    style={{ width: "100%", height: "100%", objectFit: "cover", opacity: 0.5 }}
                  />
                ) : null}
                <div className="player-card__placeholder" style={{ background: "transparent" }}>
                  {processing ? (
                    <>
                      <span className="spinner" style={{ width: 26, height: 26 }} />
                      <span style={{ fontWeight: 600 }}>Готовим лекцию…</span>
                      <span className="small muted">{lecture.stage_label}</span>
                    </>
                  ) : (
                    <>
                      <LayersIcon size={28} />
                      <span style={{ fontWeight: 600 }}>Видео станет доступно после обработки</span>
                      <span className="small muted">{lecture.error_message}</span>
                    </>
                  )}
                </div>
              </div>
            </div>
          )}

          {lecture.status === "ready" && (
            <div className="lecture-transcript">
              <TranscriptPane
                segments={segments}
                sections={lecture.sections}
                currentTime={currentTime}
                onSeek={seek}
                highlightQuery={tab === "search" ? transcriptQuery : ""}
              />
            </div>
          )}
        </div>

        <aside className="lecture-side">
          <div className="tabs">
            {TABS.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.key}
                  className={`tab ${tab === item.key ? "is-active" : ""}`}
                  onClick={() => setTab(item.key)}
                  disabled={lecture.status !== "ready"}
                >
                  <Icon size={13} style={{ display: "inline", marginRight: 5, verticalAlign: -2 }} />
                  {item.label}
                </button>
              );
            })}
          </div>

          {lecture.status !== "ready" ? (
            <div className="card card--pad">
              <p className="small muted">
                Поиск, конспект и вопросы станут доступны, когда закончится распознавание речи.
              </p>
            </div>
          ) : (
            <div className="card">
              <div className={`panel${tab === "notes" ? " panel--scroll" : ""}`}>
                {tab === "notes" && (
                  <NotesPane
                    summary={lecture.summary}
                    sections={lecture.sections}
                    keywords={lecture.keywords}
                    questions={lecture.questions ?? []}
                    currentTime={currentTime}
                    onSeek={seek}
                    requestedMode={lecture.llm_mode}
                    usedMode={lecture.llm_mode_used}
                    llmModel={lecture.llm_model}
                  />
                )}
                {tab === "search" && (
                  <SearchPane
                    lectureId={lecture.id}
                    keywords={lecture.keywords}
                    initialQuery={searchParams.get("q") ?? ""}
                    onSeek={seek}
                    onHits={setHits}
                    onQueryChange={setTranscriptQuery}
                    searchRequest={accessBase ? (query) => api.accessSearch(accessBase, query) : undefined}
                  />
                )}
                {tab === "qa" && (
                  <QaPane lectureId={lecture.id} suggestions={suggestions} onSeek={seek} hideHistory={Boolean(accessBase)} askRequest={accessBase ? (question) => api.accessQa(accessBase, question) : undefined} />
                )}
              </div>
            </div>
          )}
        </aside>
      </div>

      {!accessBase && <ConfirmDialog
        open={confirmDelete}
        title="Удалить лекцию?"
        description={`«${lecture.title}» будет удалена вместе с видео, транскриптом и индексом.`}
        confirmLabel="Удалить"
        danger
        busy={working}
        onClose={() => setConfirmDelete(false)}
        onConfirm={removeLecture}
      />}

      {!accessBase && <ConfirmDialog
        open={confirmReprocess}
        title="Переобработать лекцию?"
        description="Транскрипт, индекс, конспект и история вопросов будут построены заново. Текущие результаты заменятся новыми."
        confirmLabel="Запустить заново"
        busy={working}
        onClose={() => setConfirmReprocess(false)}
        onConfirm={reprocess}
      />}

      {!accessBase && <NotesModeDialog
        open={notesDialogOpen}
        initialMode={lecture.llm_mode}
        usedMode={lecture.llm_mode_used}
        busy={notesBusy}
        onSubmit={rebuildNotes}
        onClose={() => setNotesDialogOpen(false)}
      />}

      {!accessBase && <RenameDialog
        open={renameOpen}
        initialTitle={lecture.title}
        busy={renameBusy}
        onSave={renameLecture}
        onClose={() => setRenameOpen(false)}
      />}

      <ShareDialog target={shareTarget} onClose={() => setShareTarget(null)} />
    </>
  );
}
