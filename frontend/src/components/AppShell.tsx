import { NavLink } from "react-router-dom";
import { useUi } from "../context/UiContext";
import { useTheme } from "../hooks/useTheme";
import { LogoMark, MoonIcon, SearchIcon, SunIcon, UploadIcon, UserIcon } from "./icons";
import { useAuth } from "../context/AuthContext";

export function AppShell({ children }: { children: React.ReactNode }) {
  const ui = useUi();
  const { theme, toggle } = useTheme();
  const auth = useAuth();

  return (
    <div className="page">
      <header className="header">
        <div className="container header__inner">
          <NavLink to="/" className="brand" aria-label="Lectora — на главную">
            <span className="brand__mark">
              <LogoMark />
            </span>
            Lectora
          </NavLink>

          <nav className="nav">
            <NavLink to="/" end className={({ isActive }) => `nav__link ${isActive ? "is-active" : ""}`}>
              Библиотека
            </NavLink>
            <NavLink to="/account" className={({ isActive }) => `nav__link ${isActive ? "is-active" : ""}`}>
              Мой кабинет
            </NavLink>
            <NavLink to="/public" className={({ isActive }) => `nav__link ${isActive ? "is-active" : ""}`}>
              Публичные видео
            </NavLink>
            <a
              className="nav__link"
              href="#about"
              onClick={(event) => {
                event.preventDefault();
                ui.openPalette();
              }}
            >
              Поиск по курсу
            </a>
          </nav>

          <div className="header__spacer" />

          <button className="searchbox" onClick={() => ui.openPalette()} aria-label="Открыть поиск">
            <span className="searchbox__icon">
              <SearchIcon size={16} />
            </span>
            <input
              readOnly
              tabIndex={-1}
              placeholder="Найти фрагмент по смыслу…"
              style={{ pointerEvents: "none" }}
            />
            <span className="searchbox__hint">
              <kbd className="kbd">Ctrl</kbd>
              <kbd className="kbd">K</kbd>
            </span>
          </button>

          <div className="header__actions">
            <NavLink to="/account/settings" className="account-link" aria-label="Настройки аккаунта" title={`${auth.user?.email ?? ""} · настройки`}>
              <span className="account-link__avatar"><UserIcon size={15} /></span>
              <span className="account-link__name">{auth.user?.name}</span>
            </NavLink>
            <button className="icon-btn" onClick={toggle} aria-label="Сменить тему" title="Светлая / тёмная тема">
              {theme === "dark" ? <SunIcon size={17} /> : <MoonIcon size={17} />}
            </button>
            <button className="btn btn--primary" onClick={() => ui.openUpload()}>
              <UploadIcon size={16} />
              Загрузить
            </button>
            <button className="btn btn--ghost logout-btn" onClick={() => void auth.logout()}>Выйти</button>
          </div>
        </div>
      </header>

      <main className="main">
        <div className="container">{children}</div>
      </main>
    </div>
  );
}
