import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { LectureCard, LectureDetail, VideoGroup } from "../api/types";
import { LogoMark, PlayIcon } from "../components/icons";
import { LecturePage } from "./LecturePage";

export function SharedPage({ publicMode = false, groupMode = false }: { publicMode?: boolean; groupMode?: boolean }) {
  const { token = "", lectureId = "" } = useParams();
  const [lecture, setLecture] = useState<LectureDetail | null>(null);
  const [group, setGroup] = useState<VideoGroup | null>(null);
  const [items, setItems] = useState<LectureCard[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const request = publicMode ? api.publicLecture(lectureId) : groupMode && lectureId ? api.sharedGroupLecture(token, lectureId) : groupMode ? api.sharedGroup(token) : api.sharedVideo(token);
    Promise.resolve(request).then((data) => { if ("group" in data && "items" in data) { setGroup(data.group); setItems(data.items); } else setLecture(data as LectureDetail); }).catch((err) => setError(err instanceof ApiError ? err.message : "Материал недоступен"));
  }, [token, lectureId, publicMode, groupMode]);
  return <main className="shared-page"><Link to="/" className="auth-brand shared-brand"><span className="brand__mark"><LogoMark /></span>Lectora</Link>{error ? <div className="error-box shared-error">{error}</div> : group ? <section className="shared-content"><span className="auth-kicker">Общая группа</span><h1>{group.name}</h1><p>{group.description}</p><div className="shared-list">{items.map((item) => <Link key={item.id} to={`/shared/groups/${token}/lectures/${item.id}`}><span><PlayIcon size={18}/></span><div><strong>{item.title}</strong><small>{item.duration_label}</small></div></Link>)}</div></section> : lecture ? <section className="shared-content"><span className="auth-kicker">Видео Lectora</span><h1>{lecture.title}</h1>{lecture.description && <p>{lecture.description}</p>}<video className="shared-video" src={lecture.media_url} controls preload="metadata" />{lecture.summary && <div className="card card--pad"><h2>Краткое содержание</h2><p className="summary-text">{lecture.summary}</p></div>}</section> : <div className="app-loader"><span className="spinner"/></div>}</main>;
}

export function SharedLecturePage({ groupMode = false }: { groupMode?: boolean }) {
  const { token = "", lectureId = "" } = useParams();
  const accessBase = groupMode
    ? `/api/shared/groups/${token}/lectures/${lectureId}`
    : `/api/shared/videos/${token}`;
  const backTo = groupMode ? `/shared/groups/${token}` : "/";
  return (
    <div className="page">
      <header className="header">
        <div className="container header__inner">
          <Link to={backTo} className="brand"><span className="brand__mark"><LogoMark /></span>Lectora</Link>
        </div>
      </header>
      <main className="main"><div className="container"><LecturePage accessBase={accessBase} backTo={backTo} backLabel={groupMode ? "К группе" : "На главную"} /></div></main>
    </div>
  );
}
