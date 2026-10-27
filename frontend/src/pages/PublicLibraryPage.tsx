import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { InterestChip, PublicLecture, RecommendationFeed } from "../api/types";
import { LectureCard } from "../components/LectureCard";
import { BookIcon, SparkIcon, UploadIcon } from "../components/icons";
import { useUi } from "../context/UiContext";

type Tab = "all" | "for-you";

const KIND_LABELS: Record<InterestChip["kind"], string> = {
  subject: "Предмет",
  topic: "Тема",
  keyword: "Термин",
};

const FEED_COPY = {
  personalized: {
    title: "Подборка по вашим интересам",
    text: "Темы собраны из ваших лекций и просмотренных публичных видео.",
  },
  trending: {
    title: "Похожего пока нет",
    text: "В публичной библиотеке пока нет видео по вашим темам — показываем популярные материалы.",
  },
  cold_start: {
    title: "Подберём лекции под ваши интересы",
    text: "Загрузите лекцию или посмотрите публичное видео — мы запомним темы и начнём рекомендовать похожие материалы.",
  },
} as const;

export function PublicLibraryPage() {
  const ui = useUi();
  const [tab, setTab] = useState<Tab>("all");
  const [items, setItems] = useState<PublicLecture[]>([]);
  const [feed, setFeed] = useState<RecommendationFeed | null>(null);
  const [loadingAll, setLoadingAll] = useState(true);
  const [loadingFeed, setLoadingFeed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedError, setFeedError] = useState<string | null>(null);

  useEffect(() => {
    api
      .publicLectures()
      .then((data) => setItems(data.items))
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Не удалось загрузить публичные видео"),
      )
      .finally(() => setLoadingAll(false));
  }, []);

  const loadFeed = useCallback(async () => {
    setLoadingFeed(true);
    setFeedError(null);
    try {
      setFeed(await api.recommendations());
    } catch (err) {
      setFeedError(
        err instanceof ApiError ? err.message : "Не удалось построить рекомендации",
      );
    } finally {
      setLoadingFeed(false);
    }
  }, []);

  useEffect(() => {
    if (tab === "for-you" && !feed && !loadingFeed) void loadFeed();
  }, [tab, feed, loadingFeed, loadFeed]);

  const copy = feed ? FEED_COPY[feed.mode] : FEED_COPY.cold_start;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-head__title">Публичные видео</h1>
          <p className="page-head__subtitle">
            Открытые материалы сообщества — и персональная подборка по вашим темам.
          </p>
        </div>
      </div>

      <div className="library-toolbar">
        <h2 className="library-toolbar__title">Каталог</h2>
        <span className="library-toolbar__count">
          {tab === "all" ? items.length : feed?.items.length ?? ""}
        </span>
        <div className="filters" role="tablist" aria-label="Режим каталога">
          <button
            role="tab"
            aria-selected={tab === "all"}
            className={`filter ${tab === "all" ? "is-active" : ""}`}
            onClick={() => setTab("all")}
          >
            Все видео
          </button>
          <button
            role="tab"
            aria-selected={tab === "for-you"}
            className={`filter ${tab === "for-you" ? "is-active" : ""}`}
            onClick={() => setTab("for-you")}
          >
            <SparkIcon size={13} style={{ marginRight: 5, verticalAlign: -2 }} />
            Для Вас
          </button>
        </div>
      </div>

      {tab === "all" ? (
        <>
          {error && <div className="error-box">{error}</div>}
          {loadingAll ? (
            <SkeletonGrid />
          ) : items.length ? (
            <div className="grid">
              {items.map((item) => (
                <PublicCard key={item.id} item={item} />
              ))}
            </div>
          ) : (
            <EmptyState
              title="Публичных видео пока нет"
              text="Опубликуйте свою лекцию — она появится здесь и поможет рекомендациям."
              onUpload={() => ui.openUpload("file")}
            />
          )}
        </>
      ) : (
        <>
          <div className="rec-panel">
            <span className="rec-panel__icon">
              <SparkIcon size={20} />
            </span>
            <div className="rec-panel__body">
              <strong>{copy.title}</strong>
              <p>{copy.text}</p>
              {feed?.fallback && (
                <p className="rec-panel__hint">
                  Часть подборки — популярные видео: по вашим темам пока мало материалов.
                </p>
              )}
              {feed && feed.interests.length > 0 && (
                <div className="interest-chips" aria-label="Ваши интересы">
                  {feed.interests.map((interest) => (
                    <span
                      className={`interest-chip interest-chip--${interest.kind}`}
                      key={`${interest.kind}-${interest.label}`}
                      title={`${KIND_LABELS[interest.kind]} · вес ${interest.weight}`}
                    >
                      {interest.label}
                    </span>
                  ))}
                </div>
              )}
            </div>
            {(!feed || feed.mode === "cold_start") && (
              <button className="btn btn--primary" onClick={() => ui.openUpload("file")}>
                <UploadIcon size={15} />
                Загрузить лекцию
              </button>
            )}
          </div>

          {feedError && <div className="error-box">{feedError}</div>}

          {loadingFeed ? (
            <SkeletonGrid />
          ) : feed && feed.items.length ? (
            <div className="grid">
              {feed.items.map((item) => (
                <PublicCard key={item.id} item={item} showReason />
              ))}
            </div>
          ) : !feedError ? (
            <EmptyState
              title="Подборка пока пуста"
              text="Как только появятся публичные видео, мы подберём их по вашим темам."
              onUpload={() => ui.openUpload("file")}
            />
          ) : null}
        </>
      )}
    </>
  );
}

function PublicCard({ item, showReason = false }: { item: PublicLecture; showReason?: boolean }) {
  const reason = showReason ? item.recommendation : undefined;
  return (
    <div className="public-card">
      <LectureCard lecture={item} href={`/public/lectures/${item.id}`} />
      {reason && (
        <div className={`recommendation-reason ${reason.personalized ? "is-personalized" : ""}`}>
          <SparkIcon size={13} />
          <span>{reason.reason}</span>
          {reason.personalized && <b>{Math.round(reason.score * 100)}%</b>}
        </div>
      )}
      <div className="public-card__meta">
        <span>{item.owner_name}</span>
        {item.group_name && <b>{item.group_name}</b>}
      </div>
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid">
      {[1, 2, 3].map((i) => (
        <div className="skeleton" style={{ height: 280 }} key={i} />
      ))}
    </div>
  );
}

function EmptyState({
  title,
  text,
  onUpload,
}: {
  title: string;
  text: string;
  onUpload: () => void;
}) {
  return (
    <div className="empty">
      <div className="empty__icon">
        <BookIcon size={22} />
      </div>
      <div className="empty__title">{title}</div>
      <p style={{ maxWidth: 440, margin: "0 auto 18px" }}>{text}</p>
      <button className="btn btn--primary" onClick={onUpload}>
        <UploadIcon size={16} />
        Загрузить лекцию
      </button>
    </div>
  );
}
