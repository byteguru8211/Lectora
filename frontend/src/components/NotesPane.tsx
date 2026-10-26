import type { Section } from "../api/types";
import { BookIcon, SparkIcon } from "./icons";

interface Props {
  summary: string | null;
  sections: Section[];
  keywords: string[];
  currentTime: number;
  onSeek: (seconds: number) => void;
}

export function NotesPane({ summary, sections, keywords, currentTime, onSeek }: Props) {
  const activeSection = sections.find(
    (section) => currentTime >= section.start_sec && currentTime < section.end_sec,
  );

  return (
    <div className="stack" style={{ gap: 14 }}>
      <section className="card card--pad">
        <div className="row row--between" style={{ marginBottom: 10 }}>
          <span className="row" style={{ gap: 8 }}>
            <SparkIcon size={16} style={{ color: "var(--accent)" }} />
            <span className="panel__title">Кратко о лекции</span>
          </span>
        </div>
        <p className="summary-text">{summary || "Конспект появится после обработки лекции."}</p>

        {keywords.length > 0 && (
          <>
            <div className="field__label" style={{ marginTop: 16 }}>Ключевые термины</div>
            <div className="keywords">
              {keywords.map((keyword) => (
                <span key={keyword} className="chip">
                  {keyword}
                </span>
              ))}
            </div>
          </>
        )}
      </section>

      <section className="card card--pad">
        <div className="row row--between" style={{ marginBottom: 12 }}>
          <span className="row" style={{ gap: 8 }}>
            <BookIcon size={16} style={{ color: "var(--accent-2)" }} />
            <span className="panel__title">Структура лекции</span>
          </span>
          <span className="panel__hint">{sections.length} разделов · клик перематывает</span>
        </div>

        {sections.length === 0 ? (
          <p className="small muted">Разделы появятся после обработки.</p>
        ) : (
          <div className="outline">
            {sections.map((section) => (
              <button
                key={section.id}
                className={`outline__item ${activeSection?.id === section.id ? "is-active" : ""}`}
                onClick={() => onSeek(section.start_sec)}
              >
                <div className="outline__top">
                  <span className="outline__index">{String(section.idx + 1).padStart(2, "0")}</span>
                  <span className="outline__title">{section.title}</span>
                  <span className="outline__time">{section.timestamp}</span>
                </div>
                {section.summary && <p className="outline__summary">{section.summary}</p>}
                {section.key_points.length > 0 && (
                  <ul className="outline__points">
                    {section.key_points.map((point, index) => (
                      <li key={index} className="outline__point">
                        {point}
                      </li>
                    ))}
                  </ul>
                )}
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
