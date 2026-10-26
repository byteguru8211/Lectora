import { Link } from "react-router-dom";
import type { LectureCard as LectureCardType } from "../api/types";
import { formatDate, formatDurationLong } from "../utils/format";
import { ClockIcon, PlayIcon, TrashIcon } from "./icons";
import { StatusBadge } from "./StatusBadge";

interface Props {
  lecture: LectureCardType;
  onDelete?: (lecture: LectureCardType) => void;
}

export function LectureCard({ lecture, onDelete }: Props) {
  const isProcessing = lecture.status === "queued" || lecture.status === "processing";

  return (
    <article className="card lecture-card">
      <Link to={`/lectures/${lecture.id}`} className="lecture-card__media" aria-label={lecture.title}>
        {lecture.thumbnail_url ? (
          <img src={lecture.thumbnail_url} alt="" loading="lazy" />
        ) : (
          <div className="lecture-card__placeholder">
            <PlayIcon size={30} />
          </div>
        )}
        <span className="lecture-card__duration">{lecture.duration_label}</span>
        {isProcessing && (
          <span className="badge badge--processing" style={{ position: "absolute", top: 10, left: 10 }}>
            <span className="badge__dot" />
            {lecture.stage_label || "Обработка"}
          </span>
        )}
        {lecture.status === "failed" && (
          <span className="badge badge--failed" style={{ position: "absolute", top: 10, left: 10 }}>
            <span className="badge__dot" />
            Ошибка
          </span>
        )}
      </Link>

      <div className="lecture-card__body">
        <Link to={`/lectures/${lecture.id}`}>
          <h3 className="lecture-card__title">{lecture.title}</h3>
        </Link>

        {lecture.description ? (
          <p className="lecture-card__desc">{lecture.description}</p>
        ) : (
          <p className="lecture-card__desc muted">
            {lecture.word_count > 0
              ? `${lecture.word_count.toLocaleString("ru-RU")} слов · ${lecture.chunk_count} смысловых фрагментов`
              : "Транскрипт ещё готовится"}
          </p>
        )}

        {isProcessing && (
          <div>
            <div className="progress progress--thin">
              <div className="progress__bar" style={{ width: `${Math.max(4, lecture.progress)}%` }} />
            </div>
            <div className="row row--between" style={{ marginTop: 6 }}>
              <span className="small muted">{lecture.stage_label}</span>
              <span className="small muted">{Math.round(lecture.progress)}%</span>
            </div>
          </div>
        )}

        <div className="lecture-card__foot">
          <StatusBadge status={lecture.status} />
          <span className="lecture-card__date">
            <ClockIcon size={12} style={{ display: "inline", marginRight: 4, verticalAlign: -1 }} />
            {lecture.duration_sec > 0 ? formatDurationLong(lecture.duration_sec) : formatDate(lecture.created_at)}
          </span>
          {onDelete && (
            <button
              className="icon-btn"
              style={{ width: 28, height: 28 }}
              onClick={(event) => {
                event.preventDefault();
                onDelete(lecture);
              }}
              aria-label={`Удалить «${lecture.title}»`}
              title="Удалить лекцию"
            >
              <TrashIcon size={14} />
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
