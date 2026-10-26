import { Link } from "react-router-dom";
import { ArrowLeftIcon, LayersIcon } from "../components/icons";

export function NotFoundPage() {
  return (
    <div className="empty" style={{ marginTop: 60 }}>
      <div className="empty__icon">
        <LayersIcon size={22} />
      </div>
      <div className="empty__title">Страница не найдена</div>
      <p style={{ marginBottom: 18 }}>Возможно, ссылка устарела или лекция была удалена.</p>
      <Link className="btn btn--primary" to="/">
        <ArrowLeftIcon size={15} /> В библиотеку
      </Link>
    </div>
  );
}
