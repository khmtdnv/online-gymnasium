import { Link } from 'react-router';
import { AsyncState } from '../components/async-state';

/** 404: единый шаблон состояний с ссылкой возврата. */
export default function NotFound() {
  return (
    <div className="workspace-page state-page">
      <AsyncState
        state="empty"
        title="Страница не найдена"
        message="Возможно, адрес изменился. Вернитесь к доступным разделам."
      />
      <div className="form-actions">
        <Link to="/" className="button button-primary">
          На главную
        </Link>
      </div>
    </div>
  );
}
