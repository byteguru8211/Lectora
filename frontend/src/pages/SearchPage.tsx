import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { SearchHit } from "../api/types";
import { SearchIcon, SparkIcon } from "../components/icons";
import { splitBySpans } from "../utils/format";

const EXAMPLES = [
  "объяснение теоремы Пифагора",
  "как найти объём конуса",
  "примеры из жизни",
  "что будет на экзамене",
];

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const initial = params.get("q") ?? "";

  const [query, setQuery] = useState(initial);
  const [results, setResults] = useState<SearchHit[]>([]);
  const [meta, setMeta] = useState<{ took: number; reranked: boolean; candidates: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const run = async (value: string) => {
    const text = value.trim();
    if (text.length < 2) return;
    setLoading(true);
    setError(null);
    try {
      const response = await api.search(text, undefined, 24);
      setResults(response.results);
      setMeta({ took: response.took_ms, reranked: response.reranked, candidates: response.candidates });
      setSearched(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Поиск не удался");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (initial) {
      setQuery(initial);
      void run(initial);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  const submit = (value?: string) => {
    const text = (value ?? query).trim();
    if (text.length < 2) return;
    setParams({ q: text });
    if (text === initial) void run(text);
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-head__title">Поиск по всему курсу</h1>
          <p className="page-head__subtitle">
            Ищем по смыслу во всех лекциях сразу: эмбеддинги bge-m3, полнотекстовый индекс PostgreSQL
            и реранкер. Каждый результат — с таймкодом и переходом в плеер.
          </p>
        </div>
      </div>

      <div className="card card--pad" style={{ marginBottom: 20 }}>
        <div className="searchbar">
          <div style={{ position: "relative", flex: 1 }}>
            <span style={{ position: "absolute", left: 13, top: 14, color: "var(--faint)" }}>
              <SearchIcon size={17} />
            </span>
            <input
              className="input"
              style={{ paddingLeft: 38 }}
              autoFocus
              placeholder="Например: объяснение теоремы Пифагора"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && submit()}
            />
          </div>
          <button className="btn btn--primary" onClick={() => submit()} disabled={loading}>
            {loading ? <span className="spinner" /> : <SearchIcon size={16} />}
            Найти
          </button>
        </div>

        <div className="row" style={{ flexWrap: "wrap", gap: 6, marginTop: 12 }}>
          <span className="small muted" style={{ marginRight: 4 }}>
            Попробуйте:
          </span>
          {EXAMPLES.map((example) => (
            <button key={example} className="chip chip--button" onClick={() => submit(example)}>
              {example}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="error-box" style={{ marginBottom: 16 }}>{error}</div>}

      {loading && (
        <div className="stack">
          {[0, 1, 2].map((index) => (
            <div key={index} className="skeleton" style={{ height: 92 }} />
          ))}
        </div>
      )}

      {!loading && !searched && (
        <div className="empty">
          <div className="empty__icon">
            <SparkIcon size={22} />
          </div>
          <div className="empty__title">Спросите так, как думаете</div>
          <p style={{ maxWidth: 460, margin: "0 auto" }}>
            «Где объясняют, зачем нужен интеграл?» — работает лучше, чем одно слово. Поиск понимает
            смысл, а не только совпадения слов.
          </p>
        </div>
      )}

      {!loading && searched && (
        <>
          <div className="results-meta">
            <span>
              Найдено <strong>{results.length}</strong> фрагментов
            </span>
            {meta && <span>за {meta.took} мс</span>}
            {meta && <span>· проанализировано {meta.candidates} фрагментов</span>}
            {meta?.reranked && <span>· реранкер bge включён</span>}
          </div>

          {results.length === 0 ? (
            <div className="empty">
              <div className="empty__icon">
                <SearchIcon size={22} />
              </div>
              <div className="empty__title">Ничего не нашлось</div>
              <p>Попробуйте другой запрос или загрузите больше лекций.</p>
            </div>
          ) : (
            <div className="results">
              {results.map((hit) => (
                <button
                  key={`${hit.lecture.id}-${hit.chunk_id}`}
                  className="result"
                  onClick={() =>
                    navigate(`/lectures/${hit.lecture.id}?t=${Math.floor(hit.start_sec)}`)
                  }
                >
                  <div className="result__head">
                    <span className="result__time">{hit.timestamp}</span>
                    <span className="result__lecture">{hit.lecture.title}</span>
                    <span className="result__score">
                      {Math.round((hit.scores.final ?? 0) * 100)}%
                    </span>
                  </div>
                  <p className="result__text">
                    {splitBySpans(hit.snippet, hit.spans).map((part, index) =>
                      part.mark ? <mark key={index}>{part.text}</mark> : part.text,
                    )}
                  </p>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}
