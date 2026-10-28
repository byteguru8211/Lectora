import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { ArrowLeftIcon, CheckIcon, SparkIcon, UserIcon } from "../components/icons";
import { formatDate } from "../utils/format";

export function AccountSettingsPage() {
  const { user, updateName } = useAuth();
  const toast = useToast();

  const [name, setName] = useState(user?.name ?? "");
  const [savingName, setSavingName] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [repeatPassword, setRepeatPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);

  useEffect(() => {
    setName(user?.name ?? "");
  }, [user?.name]);

  const trimmedName = name.trim();
  const nameDirty = Boolean(user) && trimmedName !== user?.name;
  const nameValid = trimmedName.length >= 2 && trimmedName.length <= 120;

  const saveName = async () => {
    if (!nameValid || !nameDirty || savingName) return;
    setSavingName(true);
    try {
      await updateName(trimmedName);
      toast.success("Имя обновлено");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Не удалось сохранить имя");
    } finally {
      setSavingName(false);
    }
  };

  const passwordError = (() => {
    if (!currentPassword) return "Введите текущий пароль";
    if (newPassword.length < 8) return "Новый пароль должен содержать не менее 8 символов";
    if (newPassword === currentPassword) return "Новый пароль совпадает с текущим";
    if (newPassword !== repeatPassword) return "Пароли не совпадают";
    return null;
  })();

  const savePassword = async () => {
    if (passwordError || savingPassword) return;
    setSavingPassword(true);
    try {
      await api.changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setRepeatPassword("");
      toast.success("Пароль изменён");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Не удалось изменить пароль");
    } finally {
      setSavingPassword(false);
    }
  };

  return (
    <div className="account-page settings-page">
      <section className="account-hero">
        <div className="account-hero__avatar">
          <UserIcon size={27} />
        </div>
        <div>
          <span className="account-hero__eyebrow">Настройки</span>
          <h1 className="account-hero__title">Аккаунт</h1>
          <p className="account-hero__text">
            {user?.email} · {user?.role === "teacher" ? "преподаватель" : "студент"}
          </p>
        </div>
        <Link className="btn btn--ghost btn--sm settings-back" to="/account">
          <ArrowLeftIcon size={14} /> В кабинет
        </Link>
      </section>

      <div className="settings-grid">
        <form
          className="card card--pad settings-card"
          onSubmit={(event) => {
            event.preventDefault();
            void saveName();
          }}
        >
          <div className="settings-card__head">
            <span className="settings-card__icon">
              <UserIcon size={17} />
            </span>
            <div>
              <strong>Профиль</strong>
              <p className="small muted">Имя видно в шапке и на карточках ваших лекций.</p>
            </div>
          </div>

          <label className="field">
            <span className="field__label">Имя</span>
            <input
              className="input"
              value={name}
              maxLength={120}
              autoComplete="name"
              onChange={(event) => setName(event.target.value)}
            />
          </label>

          <label className="field">
            <span className="field__label">Email</span>
            <input className="input" value={user?.email ?? ""} readOnly disabled />
          </label>

          <div className="settings-hint">
            <span>Роль: {user?.role === "teacher" ? "преподаватель" : "студент"}</span>
            {user?.created_at && <span>С нами с {formatDate(user.created_at)}</span>}
          </div>

          <div className="settings-actions">
            <button
              className="btn btn--primary"
              type="submit"
              disabled={!nameDirty || !nameValid || savingName}
            >
              {savingName ? <span className="spinner" /> : <CheckIcon size={15} />}
              {savingName ? "Сохраняем…" : "Сохранить имя"}
            </button>
            {user && nameDirty && (
              <button
                className="btn btn--ghost btn--sm"
                type="button"
                onClick={() => setName(user.name)}
                disabled={savingName}
              >
                Отменить
              </button>
            )}
          </div>
        </form>

        <form
          className="card card--pad settings-card"
          onSubmit={(event) => {
            event.preventDefault();
            void savePassword();
          }}
        >
          <div className="settings-card__head">
            <span className="settings-card__icon">
              <SparkIcon size={17} />
            </span>
            <div>
              <strong>Пароль</strong>
              <p className="small muted">Минимум 8 символов. После смены вход останется активным.</p>
            </div>
          </div>

          <label className="field">
            <span className="field__label">Текущий пароль</span>
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
            />
          </label>

          <label className="field">
            <span className="field__label">Новый пароль</span>
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
            />
          </label>

          <label className="field">
            <span className="field__label">Повторите новый пароль</span>
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={repeatPassword}
              onChange={(event) => setRepeatPassword(event.target.value)}
            />
          </label>

          {currentPassword && newPassword && passwordError && (
            <p className="small settings-error">{passwordError}</p>
          )}

          <div className="settings-actions">
            <button
              className="btn btn--primary"
              type="submit"
              disabled={Boolean(passwordError) || savingPassword}
            >
              {savingPassword ? <span className="spinner" /> : <CheckIcon size={15} />}
              {savingPassword ? "Меняем…" : "Изменить пароль"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
