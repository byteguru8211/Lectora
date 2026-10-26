import type { LectureStatus } from "../api/types";

const LABELS: Record<LectureStatus, string> = {
  ready: "Готова",
  processing: "Обработка",
  queued: "В очереди",
  failed: "Ошибка",
};

export function StatusBadge({ status, label }: { status: LectureStatus; label?: string | null }) {
  const text = label || LABELS[status] || status;
  return (
    <span className={`badge badge--${status}`}>
      <span className="badge__dot" />
      {text}
    </span>
  );
}
