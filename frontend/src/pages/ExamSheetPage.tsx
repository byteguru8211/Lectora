import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { ExamSheet, ExamSource, LlmMode } from "../api/types";
import { InlineText, MathFormula, RichText } from "../components/RichText";
import { ArrowLeftIcon, BookIcon, ClockIcon, RefreshIcon, SparkIcon } from "../components/icons";
import { useToast } from "../context/ToastContext";
import { LLM_MODES, LLM_MODE_META, llmModeLabel } from "../utils/llm";

const dateLabel = (value: string | null | undefined) =>
  value
    ? new Date(value).toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })
    : null;

function SourceLink({ source, publicMode }: { source: ExamSource; publicMode: boolean }) {
  const base = publicMode ? `/public/lectures/${source.lecture_id}` : `/lectures/${source.lecture_id}`;
  return (
    <Link
      className="exam-source"
      to={`${base}?t=${Math.floor(source.start_sec)}`}
      title="Открыть этот момент в лекции"
    >
      <ClockIcon size={12} />
      <span>{source.lecture_title}</span>
      <b>{source.timestamp}</b>
    </Link>
  );
}

export function ExamSheetPage({ publicMode = false }: { publicMode?: boolean }) {
  const { groupId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [sheet, setSheet] = useState<ExamSheet | null>(null);
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<LlmMode>("api");

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const data = publicMode ? await api.publicGroupExam(groupId) : await api.groupExam(groupId);
      setSheet(data);
      setMode(data.mode_hint);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось открыть шпаргалку");
    } finally {
      setLoading(false);
    }
  }, [groupId, publicMode]);

  useEffect(() => {
    void load();
  }, [load]);

  const build = async () => {
    setBuilding(true);
    try {
      const data = publicMode
        ? await api.buildPublicGroupExam(groupId, mode)
        : await api.buildGroupExam(groupId, mode);
      setSheet(data);
      toast.success("Шпаргалка готова");
      setError(null);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Не удалось собрать шпаргалку");
    } finally {
      setBuilding(false);
    }
  };

  const group = sheet?.group;
  const ready = sheet?.status === "ready";
  const generated = dateLabel(sheet?.generated_at);

  return (
    <div className="exam-page">
      <div className="exam-toolbar no-print">
        <button
          className="btn btn--ghost btn--sm"
          onClick={() => navigate(publicMode ? `/public/groups/${groupId}` : "/account")}
        >
          <ArrowLeftIcon size={14} /> {publicMode ? "К группе" : "К группам"}
        </button>
        <div className="exam-toolbar__actions">
          {!publicMode && (
            <label className="exam-mode">
              <span>Режим</span>
              <select
                className="select"
                value={mode}
                disabled={building}
                onChange={(event) => setMode(event.target.value as LlmMode)}
              >
                {LLM_MODES.map((item) => (
                  <option key={item} value={item}>{LLM_MODE_META[item].label}</option>
                ))}
              </select>
            </label>
          )}
          {ready && (
            <button className="btn" onClick={() => window.print()}>
              <BookIcon size={15} /> Печать / PDF
            </button>
          )}
          <button
            className="btn btn--primary"
            onClick={build}
            disabled={building || (sheet !== null && !sheet.can_generate)}
          >
            {building ? <span className="spinner" /> : <RefreshIcon size={15} />}
            {building ? "Собираем…" : ready ? "Обновить" : "Собрать шпаргалку"}
          </button>
        </div>
      </div>

      <header className="exam-hero">
        <span className="exam-hero__eyebrow">
          <SparkIcon size={14} /> Шпаргалка к экзамену
        </span>
        <h1>{group?.name ?? "Группа"}</h1>
        <p>
          Собрана из готовых конспектов группы: билеты с ответами, определения, формулы и
          ссылки на моменты в лекциях.
        </p>
        <div className="exam-hero__meta">
          {sheet && <span className="chip chip--tiny">{sheet.lecture_count} лекций</span>}
          {sheet?.llm_mode_used && (
            <span className="chip chip--tiny">{llmModeLabel(sheet.llm_mode_used, "short")}</span>
          )}
          {generated && <span className="small muted">обновлено {generated}</span>}
          {sheet?.generation_ms ? (
            <span className="small muted">
              сборка{" "}
              {sheet.generation_ms >= 1000
                ? `${(sheet.generation_ms / 1000).toFixed(1)} с`
                : `${sheet.generation_ms} мс`}
            </span>
          ) : null}
        </div>
      </header>

      {error && <div className="error-box">{error}</div>}

      {sheet?.stale && (
        <div className="exam-stale no-print">
          Конспекты изменились после сборки шпаргалки. Нажмите «Обновить», чтобы
          пересобрать её с учётом правок.
        </div>
      )}

      {loading ? (
        <div className="stack" style={{ gap: 12 }}>
          <div className="skeleton" style={{ height: 120 }} />
          <div className="skeleton" style={{ height: 220 }} />
        </div>
      ) : building && !ready ? (
        <div className="card card--pad exam-building">
          <span className="spinner" />
          <div>
            <strong>Собираем шпаргалку</strong>
            <p className="small muted">
              Модель читает конспекты группы и сводит их в билеты. Обычно это занимает
              15–60 секунд, конспекты при этом не пересчитываются.
            </p>
          </div>
        </div>
      ) : !ready ? (
        <div className="empty">
          <div className="empty__icon"><SparkIcon size={22} /></div>
          <div className="empty__title">
            {sheet?.can_generate ? "Шпаргалка ещё не собрана" : "В группе нет готовых лекций"}
          </div>
          <p style={{ maxWidth: 460, margin: "0 auto 18px" }}>
            {sheet?.can_generate
              ? "Соберём билеты, определения и формулы из конспектов. Это не меняет сами лекции и не запускает повторную обработку."
              : "Дождитесь, пока лекции обработаются, и вернитесь на эту страницу."}
          </p>
          {sheet?.can_generate && (
            <button className="btn btn--primary" onClick={build} disabled={building}>
              {building ? <span className="spinner" /> : <SparkIcon size={15} />}
              {building ? "Собираем…" : "Собрать шпаргалку"}
            </button>
          )}
        </div>
      ) : (
        <div className="exam-sheet">
          {sheet.tickets.length > 0 && (
            <section className="exam-section">
              <h2>
                <span className="exam-section__index">01</span>
                Билеты
                <span className="exam-section__count">{sheet.tickets.length}</span>
              </h2>
              <ol className="exam-tickets">
                {sheet.tickets.map((ticket, index) => (
                  <li key={`${ticket.question}-${index}`} className="exam-ticket">
                    <div className="exam-ticket__head">
                      <span className="exam-ticket__num">{String(index + 1).padStart(2, "0")}</span>
                      <h3><InlineText text={ticket.question} /></h3>
                    </div>
                    <RichText text={ticket.answer} className="exam-ticket__answer" />
                    <SourceLink source={ticket} publicMode={publicMode} />
                  </li>
                ))}
              </ol>
            </section>
          )}

          {sheet.definitions.length > 0 && (
            <section className="exam-section">
              <h2>
                <span className="exam-section__index">02</span>
                Определения
                <span className="exam-section__count">{sheet.definitions.length}</span>
              </h2>
              <div className="exam-definitions">
                {sheet.definitions.map((item, index) => (
                  <article key={`${item.term}-${index}`} className="exam-definition">
                    <h3><InlineText text={item.term} /></h3>
                    <RichText text={item.definition} />
                    <SourceLink source={item} publicMode={publicMode} />
                  </article>
                ))}
              </div>
            </section>
          )}

          {sheet.formulas.length > 0 && (
            <section className="exam-section">
              <h2>
                <span className="exam-section__index">03</span>
                Формулы
                <span className="exam-section__count">{sheet.formulas.length}</span>
              </h2>
              <div className="exam-formulas">
                {sheet.formulas.map((item, index) => (
                  <article key={`${item.formula}-${index}`} className="exam-formula">
                    <MathFormula tex={item.formula} block />
                    {item.meaning && <p><InlineText text={item.meaning} /></p>}
                    <SourceLink source={item} publicMode={publicMode} />
                  </article>
                ))}
              </div>
            </section>
          )}

          {sheet.cheatsheet_md && (
            <section className="exam-section exam-section--sheet">
              <h2>
                <span className="exam-section__index">04</span>
                Полная шпаргалка
              </h2>
              <div className="card card--pad">
                <RichText text={sheet.cheatsheet_md} className="exam-cheatsheet" />
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
