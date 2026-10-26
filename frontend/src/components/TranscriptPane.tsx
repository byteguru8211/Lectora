import { useEffect, useMemo, useRef, useState } from "react";
import type { Section, Segment } from "../api/types";
import { CaptionsIcon, ListIcon } from "./icons";

interface Props {
  segments: Segment[];
  sections: Section[];
  currentTime: number;
  onSeek: (seconds: number) => void;
  highlightQuery?: string;
  activeHitSeconds?: number | null;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlight(text: string, query?: string) {
  const terms = (query ?? "")
    .split(/\s+/)
    .map((term) => term.trim().toLowerCase())
    .filter((term) => term.length >= 3);
  if (!terms.length) return text;
  const pattern = new RegExp(`(${terms.map(escapeRegExp).join("|")})`, "gi");
  const parts = text.split(pattern);
  return parts.map((part, index) => (index % 2 === 1 ? <mark key={index}>{part}</mark> : part));
}

interface Chapter {
  section: Section | null;
  segments: Segment[];
}

export function TranscriptPane({
  segments,
  sections,
  currentTime,
  onSeek,
  highlightQuery,
  activeHitSeconds,
}: Props) {
  const [follow, setFollow] = useState(true);
  const rowRefs = useRef<Map<number, HTMLButtonElement>>(new Map());

  const activeIndex = useMemo(() => {
    let index = -1;
    for (let i = 0; i < segments.length; i += 1) {
      if (segments[i].start_sec <= currentTime + 0.15) index = i;
      else break;
    }
    return index;
  }, [segments, currentTime]);

  const chapters = useMemo<Chapter[]>(() => {
    if (!segments.length) return [];
    if (!sections.length) return [{ section: null, segments }];

    const result: Chapter[] = sections.map((section) => ({ section, segments: [] }));
    const first = sections[0];
    const leading: Segment[] = [];
    for (const segment of segments) {
      if (segment.start_sec < first.start_sec) {
        leading.push(segment);
        continue;
      }
      let bucket = result[result.length - 1];
      for (const chapter of result) {
        if (
          chapter.section &&
          segment.start_sec >= chapter.section.start_sec &&
          segment.start_sec < chapter.section.end_sec
        ) {
          bucket = chapter;
          break;
        }
      }
      bucket.segments.push(segment);
    }
    if (leading.length) {
      result.unshift({ section: null, segments: leading });
    }
    return result.filter((chapter) => chapter.segments.length > 0);
  }, [segments, sections]);

  const activeChapterStart = useMemo(() => {
    let start = sections[0]?.start_sec ?? 0;
    for (const section of sections) {
      if (currentTime >= section.start_sec) start = section.start_sec;
    }
    return start;
  }, [sections, currentTime]);

  useEffect(() => {
    if (!follow || activeIndex < 0) return;
    const row = rowRefs.current.get(activeIndex);
    row?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeIndex, follow]);

  useEffect(() => {
    if (activeHitSeconds == null) return;
    const target = segments.find(
      (segment) => Math.abs(segment.start_sec - activeHitSeconds) < 1.2,
    );
    if (target) {
      rowRefs.current.get(target.idx)?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [activeHitSeconds, segments]);

  return (
    <section className="card">
      <div className="panel__head" style={{ padding: "16px 20px 10px", margin: 0 }}>
        <div className="row" style={{ gap: 8 }}>
          <CaptionsIcon size={16} style={{ color: "var(--accent-2)" }} />
          <span className="panel__title">Транскрипт по главам</span>
          <span className="panel__hint">
            {chapters.length} {chapters.length === 1 ? "глава" : "главы"} · {segments.length} фрагментов
          </span>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <button
            className={`chip chip--button ${follow ? "is-active" : ""}`}
            onClick={() => setFollow((current) => !current)}
            style={follow ? { borderColor: "var(--accent)", color: "var(--text)" } : undefined}
            title="Автопрокрутка за воспроизведением"
          >
            <ListIcon size={12} />
            {follow ? "Слежу за видео" : "Автопрокрутка выкл."}
          </button>
        </div>
      </div>

      <div className="transcript">
        {segments.length === 0 && (
          <p className="muted small" style={{ padding: 16 }}>
            Транскрипт пока пуст.
          </p>
        )}

        {chapters.map((chapter, chapterIndex) => (
          <div key={chapter.section?.id ?? `chapter-${chapterIndex}`}>
            <button
              className={`transcript__chapter ${
                (chapter.section?.start_sec ?? 0) === activeChapterStart ? "is-active" : ""
              }`}
              onClick={() => onSeek(chapter.section?.start_sec ?? chapter.segments[0].start_sec)}
              title={chapter.section ? "Перейти к началу главы" : undefined}
            >
              <span className="transcript__chapter-time">
                {chapter.section?.timestamp ?? chapter.segments[0].timestamp}
              </span>
              <span className="transcript__chapter-title">
                {chapter.section?.title ?? "Начало лекции"}
              </span>
              <span className="transcript__chapter-count">{chapter.segments.length}</span>
            </button>

            {chapter.segments.map((segment) => (
              <button
                key={segment.idx}
                ref={(element) => {
                  if (element) rowRefs.current.set(segment.idx, element);
                  else rowRefs.current.delete(segment.idx);
                }}
                className={`transcript__row ${segment.idx === activeIndex ? "is-active" : ""}`}
                onClick={() => {
                  setFollow(true);
                  onSeek(segment.start_sec);
                }}
                title={`Перейти к ${segment.timestamp}`}
              >
                <span className="transcript__time">{segment.timestamp}</span>
                <span className="transcript__text">{highlight(segment.text, highlightQuery)}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
