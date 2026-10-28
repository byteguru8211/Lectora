import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { LectureCard as LectureCardType, VideoGroup } from "../api/types";
import { LectureCard } from "../components/LectureCard";
import { ShareDialog, type ShareTarget } from "../components/ShareDialog";
import { BookIcon, FolderIcon, LinkIcon, SearchIcon, SparkIcon, UploadIcon, UserIcon } from "../components/icons";
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
  const [newGroupName, setNewGroupName] = useState("");
  const [newGroupVisibility, setNewGroupVisibility] = useState<"private" | "public">("private");
  const [editingGroupId, setEditingGroupId] = useState<string | null>(null);
  const [editingGroupName, setEditingGroupName] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [shareTarget, setShareTarget] = useState<ShareTarget | null>(null);

  const patchLecture = async (id: string, patch: { group_id?: string | null; visibility?: "private" | "public" }) => {
    setSavingId(id);
    try {
      const updated = await api.updateLecture(id, patch);
      setLectures((items) => items.map((item) => item.id === id ? { ...item, ...updated } : item));
      const groupList = await api.groups();
      setGroups(groupList.items);
      toast.success("Видео обновлено");
    } catch (err) { toast.error(err instanceof ApiError ? err.message : "Не удалось обновить видео"); }
    finally { setSavingId(null); }
  };

  const patchGroup = async (id: string, patch: { name?: string; visibility?: "private" | "public" }) => {
    setSavingId(id);
    try {
      const updated = await api.updateGroup(id, patch);
      setGroups((items) => items.map((item) => item.id === id ? { ...item, ...updated } : item));
      setEditingGroupId(null);
      toast.success("Группа обновлена");
    } catch (err) { toast.error(err instanceof ApiError ? err.message : "Не удалось обновить группу"); }
    finally { setSavingId(null); }
  };

  const createGroup = async () => {
    const name = newGroupName.trim();
    if (name.length < 2) return;
    try {
      const group = await api.createGroup(name, newGroupVisibility);
      setGroups((items) => [group, ...items]);
      setNewGroupName("");
      setSelectedGroupId(group.id);
      toast.success("Группа создана");
    } catch (err) { toast.error(err instanceof ApiError ? err.message : "Не удалось создать группу"); }
  };

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
      <aside className="account-sidebar card">
        <div className="account-sidebar__head"><FolderIcon size={16} /><span>Мои группы</span></div>
        <div className="group-create"><input className="input" value={newGroupName} onChange={(event) => setNewGroupName(event.target.value)} placeholder="Название группы" /><select className="select" value={newGroupVisibility} onChange={(event) => setNewGroupVisibility(event.target.value as "private" | "public")}><option value="private">Приватная</option><option value="public">Публичная</option></select><button className="btn btn--primary btn--sm" onClick={createGroup} disabled={newGroupName.trim().length < 2}>Создать</button></div>
        <div className="account-groups">{groups.map((group) => <div className="user-group-block" key={group.id}>
          {editingGroupId === group.id ? <div className="group-edit"><input className="input" value={editingGroupName} onChange={(event) => setEditingGroupName(event.target.value)} /><button className="btn btn--sm" disabled={savingId === group.id || editingGroupName.trim().length < 2} onClick={() => patchGroup(group.id, { name: editingGroupName.trim() })}>Сохранить</button></div> : <div className="user-group-row"><button className={`group-item ${selectedGroupId === group.id ? "is-active" : ""}`} onClick={() => { setSelectedGroupId(group.id); setTopic(null); }}><span>{group.name}</span><b>{group.video_count}</b></button><button title="Редактировать" onClick={() => { setEditingGroupId(group.id); setEditingGroupName(group.name); }}>✎</button><button title="Поделиться курсом" aria-label={`Поделиться курсом «${group.name}»`} onClick={() => setShareTarget({ kind: "group", id: group.id, title: group.name, visibility: group.visibility })}>↗</button></div>}
          <button className={`group-visibility ${group.visibility}`} disabled={savingId === group.id} onClick={() => patchGroup(group.id, { visibility: group.visibility === "public" ? "private" : "public" })}>{group.visibility === "public" ? "Публичная" : "Приватная"}</button>
        </div>)}</div>
        <div className="account-sidebar__head account-sidebar__head--categories"><SparkIcon size={16} /><span>Автокатегории</span></div><div className="account-categories"><button className={`group-item ${!selectedGroupId && category === "Все видео" ? "is-active" : ""}`} onClick={() => { setSelectedGroupId(null); setCategory("Все видео"); setTopic(null); }}><span>Все видео</span><b>{lectures.length}</b></button>{categories.map(([name, count]) => <button key={name} className={`group-item ${!selectedGroupId && category === name ? "is-active" : ""}`} onClick={() => { setSelectedGroupId(null); setCategory(name); setTopic(null); }}><span>{name}</span><b>{count}</b></button>)}</div><div className="account-sidebar__tip"><SparkIcon size={16} /><span>Lectora определяет область и тему после распознавания записи.</span></div>
      </aside>
      <section className="account-content">
        <div className="account-toolbar"><div><h2>{selectedGroupId ? groups.find((item) => item.id === selectedGroupId)?.name : topic ?? category}</h2><span>{visible.length} из {lectures.length}</span></div>{selectedGroupId && <Link className="btn btn--primary btn--sm" to={`/account/groups/${selectedGroupId}/exam`}><SparkIcon size={14} /> Шпаргалка к экзамену</Link>}{selectedGroupId && <button className="btn btn--ghost btn--sm" onClick={() => { const group = groups.find((item) => item.id === selectedGroupId); if (group) setShareTarget({ kind: "group", id: group.id, title: group.name, visibility: group.visibility }); }} title="Скопировать ссылку на курс"><LinkIcon size={14} /> Поделиться курсом</button>}<label className="account-search"><SearchIcon size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти видео…" /></label><select className="select account-sort" value={sort} onChange={(event) => setSort(event.target.value as Sort)}><option value="newest">Сначала новые</option><option value="title">По названию</option><option value="duration">По длительности</option></select></div>
        {!selectedGroupId && topics.length > 0 && <div className="topic-tabs"><button className={!topic ? "is-active" : ""} onClick={() => setTopic(null)}>Все подкатегории</button>{topics.map(([name, count]) => <button key={name} className={topic === name ? "is-active" : ""} onClick={() => setTopic(name)}>{name}<span>{count}</span></button>)}</div>}
        {error && <div className="error-box">{error}</div>}
        {loading ? <div className="grid">{[0, 1, 2].map((item) => <div key={item} className="skeleton" style={{ height: 300 }} />)}</div> : visible.length === 0 ? <div className="empty"><div className="empty__icon"><BookIcon size={22} /></div><div className="empty__title">Здесь пока нет видео</div><p>Загрузите запись — категория появится автоматически после обработки.</p><button className="btn btn--primary" onClick={() => ui.openUpload()}><UploadIcon size={16} />Загрузить видео</button></div> : <div className="grid account-grid">{visible.map((item) => <div className="account-video" key={item.id}><LectureCard lecture={item} onShare={(lecture) => setShareTarget({ kind: "lecture", id: lecture.id, title: lecture.title, visibility: lecture.visibility })} /><div className="account-video__manage"><select className="select" value={item.group_id ?? ""} disabled={savingId === item.id} onChange={(event) => patchLecture(item.id, { group_id: event.target.value || null })}><option value="">Без группы</option>{groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select><button className={`btn btn--sm ${item.visibility === "public" ? "btn--primary" : "btn--ghost"}`} disabled={savingId === item.id} onClick={() => patchLecture(item.id, { visibility: item.visibility === "public" ? "private" : "public" })}>{item.visibility === "public" ? "Публичное" : "Приватное"}</button></div><div className="account-video__classification"><span>{item.group_id ? groups.find((group) => group.id === item.group_id)?.name : "Без группы"}</span><b>·</b><span>{categoryOf(item)} → {topicOf(item)}</span></div></div>)}</div>}
      </section>
    </div>
    <ShareDialog target={shareTarget} onClose={() => setShareTarget(null)} />
  </div>;
}
