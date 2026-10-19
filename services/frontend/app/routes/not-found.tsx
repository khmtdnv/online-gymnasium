import { Link } from 'react-router';
import { AsyncState } from '../components/async-state';

export default function NotFound() {
  return (
    <>
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
    </>
  );
}
