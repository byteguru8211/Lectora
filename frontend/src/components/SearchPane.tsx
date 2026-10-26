import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { SearchHit } from "../api/types";
import { splitBySpans } from "../utils/format";
import { SearchIcon, SparkIcon } from "./icons";

interface Props {
  lectureId: string;
  keywords: string[];
  initialQuery?: string;
  onSeek: (seconds: number) => void;
  onHits: (hits: SearchHit[]) => void;
  onQueryChange: (query: string) => void;
}

export function SearchPane({ lectureId, keywords, initialQuery, onSeek, onHits, onQueryChange }: Props) {
  const [query, setQuery] = useState(initialQuery ?? "");
  const [results, setResults] = useState<SearchHit[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<{ took: number; reranked: boolean } | null>(null);

  useEffect(() => {
    onQueryChange(query);
  }, [query, onQueryChange]);

  useEffect(() => {
    if (!query.trim()) {
      setResults(null);
      setMeta(null);
      onHits([]);
    }
  }, [query, onHits]);

  const submit = async (value?: string) => {
    const text = (value ?? query).trim();
    if (text.length < 2) return;
    setQuery(text);
    setLoading(true);
    setError(null);
    try {
      const response = await api.search(text, lectureId, 12);
      setResults(response.results);
      setMeta({ took: response.took_ms, reranked: response.reranked });
      onHits(response.results);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Поиск не удался");
    } finally {
      setLoading(false);
    }
  };

  const bootstrapped = useRef(false);
  useEffect(() => {
    if (bootstrapped.current) return;
    const text = (initialQuery ?? "").trim();
    if (text.length < 2) return;
    bootstrapped.current = true;
    void submit(text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery]);

  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="searchbar">
        <div style={{ position: "relative", flex: 1 }}>
          <span style={{ position: "absolute", left: 12, top: 12, color: "var(--faint)" }}>
            <SearchIcon size={16} />
          </span>
          <input
            className="input"
            style={{ paddingLeft: 36 }}
            placeholder="Искать по смыслу внутри лекции…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && submit()}
          />
        </div>
        <button className="btn btn--primary" onClick={() => submit()} disabled={loading}>
          {loading ? <span className="spinner" /> : "Найти"}
        </button>
      </div>

      {keywords.length > 0 && !results && (
        <div className="stack" style={{ gap: 8 }}>
          <span className="panel__hint">Часто спрашивают</span>
          <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
            {keywords.slice(0, 4).map((keyword) => (
              <button key={keyword} className="chip chip--button" onClick={() => submit(keyword)}>
                <SparkIcon size={12} />
                {keyword}
              </button>
            ))}
          </div>
        </div>
      )}

      {error && <div className="error-box">{error}</div>}

      {results && (
        <>
          <div className="results-meta">
            <span>
              Найдено <strong>{results.length}</strong> фрагментов
            </span>
            {meta && <span>за {meta.took} мс</span>}
            {meta?.reranked && <span>· реранкер bge</span>}
          </div>
          {results.length === 0 ? (
            <div className="empty" style={{ padding: 28 }}>
              <div className="empty__title">Ничего не нашлось</div>
              <p className="small">Попробуйте переформулировать запрос — поиск идёт по смыслу.</p>
            </div>
          ) : (
            <div className="results">
              {results.map((hit) => (
                <button
                  key={hit.chunk_id}
                  className="result"
                  onClick={() => onSeek(hit.start_sec)}
                >
                  <div className="result__head">
                    <span className="result__time">{hit.timestamp}</span>
                    <span className="result__score">релевантность {Math.round((hit.scores.final ?? 0) * 100)}%</span>
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
    </div>
  );
}
