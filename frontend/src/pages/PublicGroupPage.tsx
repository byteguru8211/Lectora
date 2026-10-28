import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { PublicGroupDetail } from "../api/types";
import { LectureCard } from "../components/LectureCard";
import { ShareDialog, type ShareTarget } from "../components/ShareDialog";
import { ArrowLeftIcon, BookIcon, FolderIcon, LinkIcon, SparkIcon } from "../components/icons";
import { formatDurationLong } from "../utils/format";

export function PublicGroupPage() {
  const { groupId = "" } = useParams();
  const [data, setData] = useState<PublicGroupDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [shareTarget, setShareTarget] = useState<ShareTarget | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api
      .publicGroup(groupId)
      .then((payload) => {
        if (alive) setData(payload);
      })
      .catch((err) => {
        if (alive) setError(err instanceof ApiError ? err.message : "Не удалось открыть группу");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [groupId]);

  const group = data?.group;
  const items = data?.items ?? [];

  return (
    <div className="public-group-page">
      <div className="exam-toolbar">
        <Link className="btn btn--ghost btn--sm" to="/public">
          <ArrowLeftIcon size={14} /> Публичные видео
        </Link>
        <div className="row" style={{ gap: 8 }}>
          <button
            className="btn btn--ghost btn--sm"
            onClick={() =>
              setShareTarget({
                kind: "url",
                url: `${window.location.origin}/public/groups/${groupId}`,
                title: group?.name ?? "Курс",
                accessLabel: "Публичная ссылка на курс",
                hint: "Откроется у всех, кто вошёл в Lectora.",
              })
            }
            title="Скопировать ссылку на курс"
          >
            <LinkIcon size={14} /> Поделиться курсом
          </button>
          {data && items.length > 0 && (
            <Link className="btn btn--primary" to={`/public/groups/${groupId}/exam`}>
              <SparkIcon size={15} /> Шпаргалка к экзамену
            </Link>
          )}
        </div>
      </div>

      <header className="exam-hero">
        <span className="exam-hero__eyebrow">
          <FolderIcon size={14} /> Публичный курс
        </span>
        <h1>{group?.name ?? "Группа"}</h1>
        <p>
          {group?.description ||
            "Курс из публичной библиотеки: лекции, конспекты и общая шпаргалка к экзамену."}
        </p>
        <div className="exam-hero__meta">
          {group && <span className="chip chip--tiny">{group.video_count} видео</span>}
          {group && group.duration_sec > 0 && (
            <span className="chip chip--tiny">{formatDurationLong(group.duration_sec)}</span>
          )}
          {group && <span className="small muted">автор: {group.owner_name}</span>}
          {data?.exam_ready && <span className="small muted">шпаргалка собрана</span>}
        </div>
      </header>

      {error && <div className="error-box">{error}</div>}

      {loading ? (
        <div className="grid">
          {[0, 1, 2].map((item) => (
            <div className="skeleton" style={{ height: 280 }} key={item} />
          ))}
        </div>
      ) : items.length ? (
        <div className="grid">
          {items.map((item) => (
            <LectureCard key={item.id} lecture={item} href={`/public/lectures/${item.id}`} />
          ))}
        </div>
      ) : (
        !error && (
          <div className="empty">
            <div className="empty__icon">
              <BookIcon size={22} />
            </div>
            <div className="empty__title">В группе пока нет готовых видео</div>
            <p>Как только автор опубликует лекции, они появятся здесь.</p>
          </div>
        )
      )}

      <ShareDialog target={shareTarget} onClose={() => setShareTarget(null)} />
    </div>
  );
}
