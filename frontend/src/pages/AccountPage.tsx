import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import type { LectureCard as LectureCardType, VideoGroup } from "../api/types";
import { LectureCard } from "../components/LectureCard";
import { BookIcon, FolderIcon, SearchIcon, SparkIcon, UploadIcon, UserIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useUi } from "../context/UiContext";
import { formatDurationLong } from "../utils/format";
import { useToast } from "../context/ToastContext";

type Sort = "newest" | "title" | "duration";
const categoryOf = (lecture: LectureCardType) => lecture.subject || "Без категории";
const topicOf = (lecture: LectureCardType) => lecture.topic || "Без подкатегории";

export function AccountPage() {
  const ui = useUi();
  const { user } = useAuth();
  const toast = useToast();
  const [lectures, setLectures] = useState<LectureCardType[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState("Все видео");
  const [topic, setTopic] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("newest");
  const [groups, setGroups] = useState<VideoGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [library, groupList] = await Promise.all([api.lectures({ limit: 200 }), api.groups()]);
      setLectures(library.items);
      setGroups(groupList.items);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось загрузить библиотеку");
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const categories = useMemo(() => {
    const counts = new Map<string, number>();
    lectures.forEach((item) => counts.set(categoryOf(item), (counts.get(categoryOf(item)) ?? 0) + 1));
    return [...counts.entries()].sort(([a], [b]) => a === "Без категории" ? 1 : b === "Без категории" ? -1 : a.localeCompare(b, "ru"));
  }, [lectures]);
  const topics = useMemo(() => {
    if (category === "Все видео" || category === "Без категории") return [];
    const counts = new Map<string, number>();
    lectures.filter((item) => categoryOf(item) === category).forEach((item) => counts.set(topicOf(item), (counts.get(topicOf(item)) ?? 0) + 1));
    return [...counts.entries()].sort(([a], [b]) => a.localeCompare(b, "ru"));
  }, [lectures, category]);
  const visible = useMemo(() => {
    const text = query.trim().toLowerCase();
    return lectures.filter((item) => !selectedGroupId || item.group_id === selectedGroupId)
      .filter((item) => selectedGroupId || category === "Все видео" || categoryOf(item) === category)
      .filter((item) => !topic || topicOf(item) === topic)
      .filter((item) => !text || `${item.title} ${item.description ?? ""}`.toLowerCase().includes(text))
      .sort((a, b) => sort === "title" ? a.title.localeCompare(b.title, "ru") : sort === "duration" ? b.duration_sec - a.duration_sec : (Date.parse(b.created_at ?? "") || 0) - (Date.parse(a.created_at ?? "") || 0));
  }, [lectures, query, category, topic, sort, selectedGroupId]);
  const totalDuration = lectures.reduce((sum, item) => sum + item.duration_sec, 0);

  return <div className="account-page">
    <section className="account-hero"><div className="account-hero__avatar"><UserIcon size={27} /></div><div><span className="account-hero__eyebrow">Личный кабинет</span><h1 className="account-hero__title">Библиотека {user?.name}</h1><p className="account-hero__text">Категории формируются автоматически по содержанию ваших видео.</p></div><div className="account-hero__stats"><div><strong>{lectures.length}</strong><span>видео</span></div><div><strong>{totalDuration ? formatDurationLong(totalDuration) : "—"}</strong><span>в библиотеке</span></div></div></section>
    <div className="account-layout">
      <aside className="account-sidebar card"><div className="account-sidebar__head"><FolderIcon size={16} /><span>Мои группы</span></div>{groups.map((group) => <div className="user-group-row" key={group.id}><button className={`group-item ${selectedGroupId === group.id ? "is-active" : ""}`} onClick={() => { setSelectedGroupId(group.id); setTopic(null); }}><span>{group.name}</span><b>{group.video_count}</b></button><button title="Скопировать ссылку" onClick={async () => { const result = await api.shareGroup(group.id); await navigator.clipboard.writeText(`${window.location.origin}${result.path}`); toast.success("Ссылка на группу скопирована"); }}>↗</button></div>)}<div className="account-sidebar__head account-sidebar__head--categories"><SparkIcon size={16} /><span>Автокатегории</span></div><button className={`group-item ${!selectedGroupId && category === "Все видео" ? "is-active" : ""}`} onClick={() => { setSelectedGroupId(null); setCategory("Все видео"); setTopic(null); }}><span>Все видео</span><b>{lectures.length}</b></button>{categories.map(([name, count]) => <button key={name} className={`group-item ${!selectedGroupId && category === name ? "is-active" : ""}`} onClick={() => { setSelectedGroupId(null); setCategory(name); setTopic(null); }}><span>{name}</span><b>{count}</b></button>)}<div className="account-sidebar__tip"><SparkIcon size={16} /><span>Lectora определяет область и тему после распознавания записи.</span></div></aside>
      <section className="account-content">
        <div className="account-toolbar"><div><h2>{selectedGroupId ? groups.find((item) => item.id === selectedGroupId)?.name : topic ?? category}</h2><span>{visible.length} из {lectures.length}</span></div><label className="account-search"><SearchIcon size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти видео…" /></label><select className="select account-sort" value={sort} onChange={(event) => setSort(event.target.value as Sort)}><option value="newest">Сначала новые</option><option value="title">По названию</option><option value="duration">По длительности</option></select></div>
        {!selectedGroupId && topics.length > 0 && <div className="topic-tabs"><button className={!topic ? "is-active" : ""} onClick={() => setTopic(null)}>Все подкатегории</button>{topics.map(([name, count]) => <button key={name} className={topic === name ? "is-active" : ""} onClick={() => setTopic(name)}>{name}<span>{count}</span></button>)}</div>}
        {error && <div className="error-box">{error}</div>}
        {loading ? <div className="grid">{[0, 1, 2].map((item) => <div key={item} className="skeleton" style={{ height: 300 }} />)}</div> : visible.length === 0 ? <div className="empty"><div className="empty__icon"><BookIcon size={22} /></div><div className="empty__title">Здесь пока нет видео</div><p>Загрузите запись — категория появится автоматически после обработки.</p><button className="btn btn--primary" onClick={() => ui.openUpload()}><UploadIcon size={16} />Загрузить видео</button></div> : <div className="grid account-grid">{visible.map((item) => <div className="account-video" key={item.id}><LectureCard lecture={item} onShare={async (lecture) => { const result = await api.shareLecture(lecture.id); await navigator.clipboard.writeText(`${window.location.origin}${result.path}`); toast.success("Ссылка на видео скопирована"); }} /><div className="account-video__classification"><span>{item.visibility === "public" ? "Публичное" : "Приватное"}</span><b>·</b><span>{categoryOf(item)} → {topicOf(item)}</span></div></div>)}</div>}
      </section>
    </div>
  </div>;
}
