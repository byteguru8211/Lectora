import type { Section, SearchHit } from "../api/types";
import { formatClock } from "../utils/format";

interface Props {
  duration: number;
  current: number;
  sections: Section[];
  hits: SearchHit[];
  onSeek: (seconds: number) => void;
}

export function SemanticTimeline({ duration, current, sections, hits, onSeek }: Props) {
  const total = duration || 1;
  const percent = Math.min(100, Math.max(0, (current / total) * 100));

  return (
    <div className="timeline">
      <div
        className="timeline__track"
        role="slider"
        aria-label="Позиция в лекции"
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(current)}
        tabIndex={0}
        onClick={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const ratio = (event.clientX - rect.left) / rect.width;
          onSeek(Math.max(0, Math.min(duration, ratio * duration)));
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowRight") onSeek(Math.min(duration, current + 10));
          if (event.key === "ArrowLeft") onSeek(Math.max(0, current - 10));
        }}
        title="Структура лекции: клик перематывает"
      >
        {sections.map((section) => (
          <div
            key={section.id}
            className="timeline__section"
            style={{
              left: `${(section.start_sec / total) * 100}%`,
              width: `${Math.max(0.6, ((section.end_sec - section.start_sec) / total) * 100)}%`,
            }}
            title={`${section.title} · ${section.timestamp}`}
          />
        ))}
        <div className="timeline__progress" style={{ width: `${percent}%` }} />
        {hits.map((hit) => (
          <span
            key={`${hit.chunk_id}-${hit.start_sec}`}
            className="timeline__hit"
            style={{ left: `${(hit.start_sec / total) * 100}%` }}
            title={`Совпадение: ${hit.timestamp}`}
          />
        ))}
      </div>
      <div className="timeline__labels">
        <span>0:00</span>
        <span>{formatClock(duration / 4)}</span>
        <span>{formatClock(duration / 2)}</span>
        <span>{formatClock((duration * 3) / 4)}</span>
        <span>{formatClock(duration)}</span>
      </div>
    </div>
  );
}
