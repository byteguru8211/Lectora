import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { LectureCard as LectureCardType } from "../api/types";
import { LectureCard } from "../components/LectureCard";
import { BookIcon } from "../components/icons";

type PublicLecture = LectureCardType & { owner_name: string; group_name: string | null };

export function PublicLibraryPage() {
  const [items, setItems] = useState<PublicLecture[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.publicLectures().then((data) => setItems(data.items)).catch((err) => setError(err instanceof ApiError ? err.message : "Не удалось загрузить публичные видео")).finally(() => setLoading(false)); }, []);
  return <><div className="page-head"><div><h1 className="page-head__title">Публичные видео</h1><p className="page-head__subtitle">Открытые материалы всех пользователей платформы.</p></div></div>{error && <div className="error-box">{error}</div>}{loading ? <div className="grid">{[1,2,3].map((i) => <div className="skeleton" style={{height:280}} key={i}/>)}</div> : items.length ? <div className="grid">{items.map((item) => <div className="public-card" key={item.id}><LectureCard lecture={item} href={`/public/lectures/${item.id}`} /><div className="public-card__meta"><span>{item.owner_name}</span>{item.group_name && <b>{item.group_name}</b>}</div></div>)}</div> : <div className="empty"><div className="empty__icon"><BookIcon size={22}/></div><div className="empty__title">Публичных видео пока нет</div></div>}</>;
}
