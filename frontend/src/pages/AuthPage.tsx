import { FormEvent, useState } from "react";
import { ApiError } from "../api/client";
import { LogoMark } from "../components/icons";
import { useAuth } from "../context/AuthContext";

export function AuthPage() {
  const auth = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"student" | "teacher">("student");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") await auth.register(name, email, password, role);
      else await auth.login(email, password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось выполнить вход");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-promo">
        <div className="auth-brand"><span className="brand__mark"><LogoMark /></span>Lectora</div>
        <div className="auth-promo__body">
          <span className="auth-kicker">Ваша видеобиблиотека</span>
          <h1>Видео превращаются<br />в знания</h1>
          <p>Загружайте любые записи. Lectora сама распознает содержание, создаст категории и поможет найти нужный момент.</p>
          <div className="auth-features"><span>Автокатегоризация</span><span>Смысловой поиск</span><span>Личная библиотека</span></div>
        </div>
      </section>
      <section className="auth-panel">
        <form className="auth-card" onSubmit={submit}>
          <div><span className="auth-card__eyebrow">{mode === "login" ? "С возвращением" : "Начнём работу"}</span><h2>{mode === "login" ? "Вход в аккаунт" : "Создать аккаунт"}</h2><p>{mode === "login" ? "Войдите, чтобы открыть свою библиотеку." : "Ваши видео будут доступны только вам."}</p></div>
          {error && <div className="error-box">{error}</div>}
          {mode === "register" && <label className="field"><span>Имя</span><input className="input" value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" required minLength={2} placeholder="Как к вам обращаться" /></label>}
          {mode === "register" && <div className="field"><span>Кто вы?</span><div className="role-options"><button type="button" className={role === "student" ? "is-active" : ""} onClick={() => setRole("student")}>Студент</button><button type="button" className={role === "teacher" ? "is-active" : ""} onClick={() => setRole("teacher")}>Преподаватель</button></div></div>}
          <label className="field"><span>Email</span><input className="input" type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required placeholder="name@example.com" /></label>
          <label className="field"><span>Пароль</span><input className="input" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} required minLength={8} placeholder="Не менее 8 символов" /></label>
          <button className="btn btn--primary auth-submit" disabled={busy}>{busy && <span className="spinner" />}{mode === "login" ? "Войти" : "Зарегистрироваться"}</button>
          <button type="button" className="auth-switch" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}>{mode === "login" ? "Нет аккаунта? Зарегистрироваться" : "Уже есть аккаунт? Войти"}</button>
        </form>
      </section>
    </main>
  );
}
